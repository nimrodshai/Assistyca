#!/usr/bin/env python3
"""Download Cinema City fixture images into the local site asset tree."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


RESEARCH_DATE = "2026-08-21"


MOVIE_IMAGE_NAMES = {
    "movie-spider-man-brand-new-day": "spider-man-brand-new-day",
    "movie-spa-weekend": "spa-weekend",
    "movie-mutiny": "mutiny",
    "movie-coyote-vs-acme-he": "coyote-vs-acme-he",
    "movie-insidious-out-of-the-further": "insidious-out-of-the-further",
    "movie-la-la-land-10": "la-la-land-10",
    "movie-pout-pout-fish-he": "pout-pout-fish-he",
    "movie-the-odyssey": "the-odyssey",
}


CINEMA_IMAGE_NAMES = {
    "cinema-glilot": "glilot",
    "cinema-rishon-lezion": "rishon-lezion",
    "cinema-jerusalem": "jerusalem",
    "cinema-kfar-saba": "kfar-saba",
    "cinema-netanya": "netanya",
    "cinema-hadera": "hadera",
    "cinema-beer-sheva": "beer-sheva",
    "cinema-ashdod": "ashdod",
}


def run_curl(url: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-LsS", "-o", str(target), url],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        print(f"download failed: {url}\n{result.stderr}", file=sys.stderr)
        return False
    if target.stat().st_size < 128:
        print(f"download looked empty: {target}", file=sys.stderr)
        return False
    return True


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    fixture_path = repo / "clients" / "CinemaCity" / "spec" / "fixture-data.json"
    asset_root = repo / "clients" / "CinemaCity" / "site" / "public" / "images"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    downloads: list[tuple[str, Path, str]] = []
    downloads.append(
        (
            fixture["brand"]["logoSourceUrl"],
            asset_root / "brand" / "cinema-city-logo.png",
            "brand/cinema-city-logo.png",
        )
    )

    for movie in fixture["movies"]:
        name = MOVIE_IMAGE_NAMES[movie["id"]]
        downloads.append(
            (
                movie["posterSourceUrl"],
                asset_root / "posters" / f"{name}.jpg",
                f"posters/{name}.jpg",
            )
        )
        downloads.append(
            (
                movie["backdropSourceUrl"],
                asset_root / "heroes" / f"{name}.jpg",
                f"heroes/{name}.jpg",
            )
        )

    for cinema in fixture["cinemas"]:
        name = CINEMA_IMAGE_NAMES[cinema["id"]]
        downloads.append(
            (
                cinema["imageSourceUrl"],
                asset_root / "locations" / f"{name}.jpg",
                f"locations/{name}.jpg",
            )
        )

    source_rows = ["# Cinema City Runtime Image Sources", ""]
    failures: list[str] = []
    seen_targets: set[Path] = set()
    for url, target, relative in downloads:
        if target not in seen_targets:
            if not run_curl(url, target):
                failures.append(relative)
            seen_targets.add(target)
        source_rows.append(f"- `{relative}`")
        source_rows.append(f"  - Source: {url}")
        source_rows.append(f"  - Research date: {RESEARCH_DATE}")

    source_rows.extend(
        [
            "- `experiences/vip.jpg`",
            "  - Uses `locations/glilot.jpg` as an auditorium-adjacent local visual fallback.",
            f"  - Research date: {RESEARCH_DATE}",
            "- `experiences/prime.jpg`",
            "  - Uses `locations/netanya.jpg` as a PRIME-capable local visual fallback.",
            f"  - Research date: {RESEARCH_DATE}",
            "- `experiences/onyx.jpg`",
            "  - Uses `locations/glilot.jpg` because ONYX is a Glilot fixture experience.",
            f"  - Research date: {RESEARCH_DATE}",
        ]
    )
    (asset_root / "SOURCES.md").write_text("\n".join(source_rows) + "\n", encoding="utf-8")

    # Experience photos intentionally reuse downloaded location photos so the
    # app never hotlinks page URLs that are not direct image resources.
    copy_pairs = [
        (asset_root / "locations" / "glilot.jpg", asset_root / "experiences" / "vip.jpg"),
        (asset_root / "locations" / "netanya.jpg", asset_root / "experiences" / "prime.jpg"),
        (asset_root / "locations" / "glilot.jpg", asset_root / "experiences" / "onyx.jpg"),
    ]
    for source, target in copy_pairs:
        if source.exists():
            target.write_bytes(source.read_bytes())

    if failures:
        print("Downloaded with fallback-needed files:", ", ".join(failures))
    else:
        print(f"Downloaded {len(seen_targets)} assets into {asset_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
