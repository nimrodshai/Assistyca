#!/usr/bin/env python3
"""Render a technical/product spec JSON file into a PDF document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from generate_spec_pdf import (
    ACCENT,
    build_styles,
    draw_footer,
    draw_header,
    is_rtl,
    paragraph_text,
    register_body_font,
    register_brand_font,
    render_list,
    render_numbered_list,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer


SECTION_ORDER: list[tuple[str, str]] = [
    ("Goals", "goals"),
    ("Architecture", "architecture"),
    ("Data model", "data_model"),
    ("Automation", "automation"),
    ("Workflows", "workflows"),
    ("Implementation plan", "implementation_plan"),
    ("Non-goals", "non_goals"),
    ("Acceptance criteria", "acceptance_criteria"),
    ("Risks", "risks"),
    ("Open questions", "open_questions"),
    ("Future ideas", "future_ideas"),
]

NUMBERED_SECTIONS = {"workflows", "implementation_plan"}


def load_spec(spec_path: Path) -> dict[str, Any]:
    with spec_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_definition_block(
    story: list[Any], label: str, value: Any, styles: dict[str, ParagraphStyle], rtl: bool
) -> None:
    content = "" if value is None else str(value)
    if not content.strip():
        return
    label_html = paragraph_text(label, rtl)
    body_html = paragraph_text(content, rtl)
    story.append(Paragraph(f"<b>{label_html}:</b> {body_html}", styles["BodyTextSpec"]))


def render_overview(
    story: list[Any], overview: dict[str, Any], styles: dict[str, ParagraphStyle], rtl: bool
) -> None:
    if not overview:
        return

    story.append(Paragraph(paragraph_text("Overview", rtl), styles["SectionTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.1, color=ACCENT, spaceBefore=0, spaceAfter=6))
    for key, value in overview.items():
        render_definition_block(story, key.replace("_", " ").title(), value, styles, rtl)
    story.append(Spacer(1, 5))


def render_section(
    story: list[Any], title: str, content: Any, styles: dict[str, ParagraphStyle], rtl: bool, numbered: bool = False
) -> None:
    if not content:
        return

    if isinstance(content, str):
        content_items = [content]
    elif isinstance(content, list):
        content_items = content
    else:
        content_items = [str(content)]

    story.append(Paragraph(paragraph_text(title, rtl), styles["SectionTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.1, color=ACCENT, spaceBefore=0, spaceAfter=6))

    if numbered:
        render_numbered_list(story, styles["BodyTextSpec"], content_items, rtl)
    else:
        render_list(story, styles["BulletTextSpec"], content_items, rtl)

    story.append(Spacer(1, 5))


def build_story(spec: dict[str, Any], styles: dict[str, ParagraphStyle], rtl: bool) -> list[Any]:
    meta = spec.get("meta", {})
    overview = spec.get("overview", {})
    sections = spec.get("sections", {})

    story: list[Any] = []
    title = meta.get("title") or meta.get("project_name") or "Technical / Product Spec"

    story.append(Paragraph(paragraph_text(title, rtl), styles["SpecTitle"]))
    story.append(Spacer(1, 10))
    render_overview(story, overview, styles, rtl)

    for section_title, section_key in SECTION_ORDER:
        render_section(
            story,
            section_title,
            sections.get(section_key, []),
            styles,
            rtl,
            numbered=section_key in NUMBERED_SECTIONS,
        )

    return story


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a technical/product spec JSON file into a PDF.")
    parser.add_argument("spec", type=Path, help="Path to the spec JSON file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output PDF path. Defaults to the input file name with a .pdf extension.",
    )
    args = parser.parse_args()

    spec_path = args.spec.expanduser().resolve()
    if not spec_path.exists():
        raise SystemExit(f"Spec file not found: {spec_path}")

    spec = load_spec(spec_path)
    rtl = is_rtl(spec)
    body_font, bold_font = register_body_font(rtl)
    tagline_font = register_brand_font()
    styles = build_styles(body_font, bold_font, rtl)

    output_path = args.output.expanduser().resolve() if args.output else spec_path.with_suffix(".pdf")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=35 * mm,
        bottomMargin=20 * mm,
        title=str(spec.get("meta", {}).get("title", "Technical / Product Spec")),
        author=str(spec.get("meta", {}).get("prepared_by", "Codex")),
        subject=str(spec.get("meta", {}).get("project_name", "Technical/product spec")),
    )

    story = build_story(spec, styles, rtl)

    def draw_page(canvas: Any, document: SimpleDocTemplate) -> None:
        draw_header(canvas, document, rtl, Path(__file__).resolve().parents[1] / "assets" / "AssistycaLogoTitle.png", tagline_font)
        draw_footer(canvas, document, body_font)

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
