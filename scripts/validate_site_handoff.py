#!/usr/bin/env python3
"""Validate a site handoff spec, its cinema fixtures, and optional scope PDF."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = ("spec.json", "website-build-spec.md", "fixture-data.json")
REQUIRED_FIXTURE_KEYS = (
    "meta",
    "brand",
    "home",
    "experiences",
    "cinemas",
    "movies",
    "seatMaps",
    "screenings",
    "orders",
)


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {path}: {error}")
    if not isinstance(value, dict):
        fail(f"Expected an object in {path}")
    return value


def index_unique(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        value = str(item.get(key, ""))
        if not value:
            fail(f"{label} record is missing {key}")
        if value in result:
            fail(f"Duplicate {label} {key}: {value}")
        result[value] = item
    return result


def valid_seat_ids(seat_map: dict[str, Any]) -> set[str]:
    rows = seat_map.get("rowLabels", [])
    seats_per_row = int(seat_map.get("seatsPerRow", 0))
    return {f"{row}{number}" for row in rows for number in range(1, seats_per_row + 1)}


def validate_fixture(fixture: dict[str, Any]) -> dict[str, int]:
    missing = [key for key in REQUIRED_FIXTURE_KEYS if key not in fixture]
    if missing:
        fail(f"Fixture is missing keys: {', '.join(missing)}")

    movies = index_unique(fixture["movies"], "id", "movie")
    cinemas = index_unique(fixture["cinemas"], "id", "cinema")
    experiences = index_unique(fixture["experiences"], "id", "experience")
    screenings = index_unique(fixture["screenings"], "id", "screening")
    seat_maps = index_unique(fixture["seatMaps"], "id", "seat map")
    orders = index_unique(fixture["orders"], "reference", "order")

    movie_slugs = index_unique(fixture["movies"], "slug", "movie")
    cinema_slugs = index_unique(fixture["cinemas"], "slug", "cinema")
    if len(movie_slugs) != len(movies) or len(cinema_slugs) != len(cinemas):
        fail("Slug count does not match record count")

    for movie_id in fixture["home"].get("nowShowingMovieIds", []):
        if movie_id not in movies:
            fail(f"Home references unknown movie: {movie_id}")
    featured_movie_id = fixture["home"].get("featuredMovieId")
    if featured_movie_id not in movies:
        fail(f"Home references unknown featured movie: {featured_movie_id}")

    for experience in experiences.values():
        for cinema_id in experience.get("cinemaIds", []):
            if cinema_id not in cinemas:
                fail(f"Experience {experience['id']} references unknown cinema: {cinema_id}")

    normalized_seats: dict[str, set[str]] = {}
    occupied_seats: dict[str, set[str]] = {}
    for seat_map_id, seat_map in seat_maps.items():
        valid = valid_seat_ids(seat_map)
        normalized_seats[seat_map_id] = valid
        occupied_seats[seat_map_id] = set(seat_map.get("occupiedSeatIds", []))
        for field in ("premiumSeatIds", "accessibleSeatIds", "companionSeatIds", "occupiedSeatIds"):
            invalid = set(seat_map.get(field, [])) - valid
            if invalid:
                fail(f"Seat map {seat_map_id} has invalid {field}: {sorted(invalid)}")

    for screening in screenings.values():
        if screening.get("movieId") not in movies:
            fail(f"Screening {screening['id']} references unknown movie")
        if screening.get("cinemaId") not in cinemas:
            fail(f"Screening {screening['id']} references unknown cinema")
        if screening.get("seatMapId") not in seat_maps:
            fail(f"Screening {screening['id']} references unknown seat map")
        experience = screening.get("experience")
        cinema_experiences = cinemas[screening["cinemaId"]].get("experiences", [])
        if experience not in cinema_experiences:
            fail(f"Screening {screening['id']} uses {experience} at an unsupported cinema")
        try:
            datetime.fromisoformat(screening["startsAt"])
        except (KeyError, TypeError, ValueError):
            fail(f"Screening {screening['id']} has an invalid startsAt value")
        if not screening.get("ticketTypes"):
            fail(f"Screening {screening['id']} has no ticket types")

    for order in orders.values():
        screening_id = order.get("screeningId")
        if screening_id not in screenings:
            fail(f"Order {order['reference']} references unknown screening")
        seat_map_id = screenings[screening_id]["seatMapId"]
        invalid = set(order.get("seatIds", [])) - normalized_seats[seat_map_id]
        if invalid:
            fail(f"Order {order['reference']} has invalid seats: {sorted(invalid)}")
        unavailable = set(order.get("seatIds", [])) & occupied_seats[seat_map_id]
        if unavailable:
            fail(f"Order {order['reference']} uses occupied fixture seats: {sorted(unavailable)}")

    return {
        "movies": len(movies),
        "cinemas": len(cinemas),
        "experiences": len(experiences),
        "screenings": len(screenings),
        "seat_maps": len(seat_maps),
        "orders": len(orders),
    }


def validate_markdown(path: Path) -> int:
    content = path.read_text(encoding="utf-8")
    required_sections = (
        "## 1. Instructions for the implementation model",
        "## 6. Brand and design system",
        "## 10. Homepage",
        "## 15. Booking flow",
        "## 21. Accessibility",
        "## 30. Testing",
        "## 31. Acceptance checklist",
        "## 32. Build order for a smaller implementation model",
    )
    missing = [section for section in required_sections if section not in content]
    if missing:
        fail(f"Build spec is missing sections: {', '.join(missing)}")
    line_count = len(content.splitlines())
    if line_count < 500:
        fail(f"Build spec is too short for this handoff: {line_count} lines")
    return line_count


def render_pdf(spec_dir: Path) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "generate_spec_pdf.py"),
        str(spec_dir / "spec.json"),
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_dir", type=Path, help="Directory containing the site handoff files")
    parser.add_argument("--render-pdf", action="store_true", help="Render spec.pdf after validation")
    args = parser.parse_args()

    spec_dir = args.spec_dir.expanduser().resolve()
    for filename in REQUIRED_FILES:
        if not (spec_dir / filename).is_file():
            fail(f"Missing required handoff file: {spec_dir / filename}")

    load_json(spec_dir / "spec.json")
    counts = validate_fixture(load_json(spec_dir / "fixture-data.json"))
    lines = validate_markdown(spec_dir / "website-build-spec.md")

    if args.render_pdf:
        render_pdf(spec_dir)

    summary = ", ".join(f"{key}={value}" for key, value in counts.items())
    print(f"Valid site handoff: {spec_dir}")
    print(f"Build spec lines={lines}; {summary}")
    if args.render_pdf:
        print(f"Rendered PDF: {spec_dir / 'spec.pdf'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
