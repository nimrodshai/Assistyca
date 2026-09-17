"""What the Israeli public record says about a piece of land.

Someone buying a flat, arguing with a neighbour's extension or wondering why
cranes appeared down the street wants three things: which parcel this is, what
is planned for it, and how to see who owns it. Web search finds some of that
by chance. This module reads the sources directly.

- The parcel (gush and helka, its registered area and whether it is settled)
  comes from the Survey of Israel's open cadastre on open.govmap.gov.il.
- The plans that cover it - approved, deposited for objections, or still being
  checked - come from the Planning Administration's public map service
  (ags.iplan.gov.il), each with its page on mavat.
- An address becomes a point through OpenStreetMap's Nominatim, because the
  GovMap search refuses calls from outside its own site.

Who owns the parcel, its mortgages and liens are only in a Tabu extract, which
the Land Registry sells per parcel behind its own payment page. Nothing here
fetches or pays for one: the result says how to order it and hands over the
gush and helka the order form asks for.

All three services are public and need no key. None of them is ours, so any
of them failing becomes a plain error the assistant can say, never a guess.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
CADASTRE_WFS_URL = "https://open.govmap.gov.il/geoserver/opendata/wfs"
PLANS_QUERY_URL = "https://ags.iplan.gov.il/arcgisiplan/rest/services/PlanningPublic/Xplan/MapServer/1/query"
TABU_EXTRACT_URL = "https://www.gov.il/he/service/land_registration_extract"
PUBLIC_RECORDS_TIMEOUT_SECONDS = 20.0
# Nominatim's usage policy asks for a User-Agent that names the application.
PUBLIC_RECORDS_USER_AGENT = "Assistyca/1.0 PublicRecords (+https://assistyca.com)"
PUBLIC_RECORDS_MAX_PLANS = 12

_PLAN_FIELDS = (
    "pl_number",
    "pl_name",
    "entity_subtype_desc",
    "internet_short_status",
    "station_desc",
    "pl_objectives",
    "depositing_date",
    "pl_rejection_date",
    "pl_date_8",
    "last_update_date",
    "quantity_delta_120",
    "plan_county_name",
    "pl_url",
)


class PublicRecordsError(RuntimeError):
    """A public service could not be read. code says which kind of failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _base_url(env_name: str, default: str) -> str:
    return str(os.environ.get(env_name) or default).strip()


def _get_json(url: str, params: dict[str, Any], *, source: str) -> Any:
    query = urllib_parse.urlencode({key: value for key, value in params.items() if value is not None})
    request = urllib_request.Request(
        f"{url}?{query}",
        headers={"User-Agent": PUBLIC_RECORDS_USER_AGENT, "Accept": "application/json", "Accept-Language": "he,en"},
    )
    try:
        with urllib_request.urlopen(request, timeout=PUBLIC_RECORDS_TIMEOUT_SECONDS) as response:
            body = response.read()
    except TimeoutError as exc:
        raise PublicRecordsError("timed_out", f"{source} took too long to answer.") from exc
    except (urllib_error.URLError, OSError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise PublicRecordsError("timed_out", f"{source} took too long to answer.") from exc
        raise PublicRecordsError("provider_unavailable", f"{source} could not be reached: {exc}") from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicRecordsError("provider_unavailable", f"{source} did not answer with data.") from exc


def _one_line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _day(epoch_ms: Any) -> str:
    """ArcGIS dates are epoch milliseconds at midnight UTC of an Israeli day."""

    if not isinstance(epoch_ms, (int, float)) or epoch_ms <= 0:
        return ""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).date().isoformat()


def geocode_address(address: str) -> dict[str, Any] | None:
    """The point for an Israeli address, and whether the house number was found."""

    rows = _get_json(
        _base_url("PUBLIC_RECORDS_GEOCODER_URL", GEOCODER_URL),
        {
            "q": address,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "il",
            "accept-language": "he",
        },
        source="The address lookup",
    )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    try:
        lat, lon = float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    details = row.get("address") if isinstance(row.get("address"), dict) else {}
    return {
        "lat": lat,
        "lon": lon,
        "matchedAddress": _one_line(row.get("display_name"), 300),
        # Without a house number the point is somewhere on the street, and the
        # parcel under it may be a neighbour's.
        "exactBuilding": bool(details.get("house_number")),
    }


def _parcel_from_feature(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    suffix = props.get("GUSH_SUFFI")
    return {
        "gush": props.get("GUSH_NUM"),
        "gushSuffix": suffix if suffix else None,
        "helka": props.get("PARCEL"),
        "registeredAreaSqm": props.get("LEGAL_AREA"),
        "registrationStatus": _one_line(props.get("STATUS_TEX"), 60),
        "locality": _one_line(props.get("LOCALITY_N"), 80),
    }


def _outer_ring(feature: dict[str, Any]) -> list[list[float]]:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "MultiPolygon" and coordinates:
        coordinates = coordinates[0]
    ring = coordinates[0] if coordinates else []
    return [[float(x), float(y)] for x, y, *_ in ring]


def _inside(point: tuple[float, float], ring: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _point_inside(ring: list[list[float]]) -> tuple[float, float] | None:
    """A point within the parcel, so plans next door are not counted as its own."""

    if len(ring) < 3:
        return None
    # Measured from the first corner: a parcel is a few metres across at
    # coordinates near 34 and 32, and the products would lose it otherwise.
    ox, oy = ring[0]
    local = [(x - ox, y - oy) for x, y in ring]
    area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(local, local[1:] + local[:1]):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if area:
        centroid = (ox + cx / (3 * area), oy + cy / (3 * area))
        if _inside(centroid, ring):
            return centroid
    # An L-shaped parcel can have its centroid outside it: try the middle of
    # each edge, nudged a little to either side.
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        for fraction in (0.02, -0.02):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            candidate = (mx - (y2 - y1) * fraction, my + (x2 - x1) * fraction)
            if _inside(candidate, ring):
                return candidate
    return None


def _cadastre(cql_filter: str) -> list[dict[str, Any]]:
    payload = _get_json(
        _base_url("PUBLIC_RECORDS_CADASTRE_URL", CADASTRE_WFS_URL),
        {
            "service": "WFS",
            "version": "1.1.0",
            "request": "GetFeature",
            "typeName": "opendata:PARCEL_ALL",
            "maxFeatures": 2,
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "CQL_FILTER": cql_filter,
        },
        source="The Survey of Israel parcel map",
    )
    features = payload.get("features") if isinstance(payload, dict) else None
    return [feature for feature in features or [] if isinstance(feature, dict)]


def parcel_at(lat: float, lon: float) -> dict[str, Any] | None:
    features = _cadastre(f"INTERSECTS(the_geom,SRID=4326;POINT({lon:.7f} {lat:.7f}))")
    return _parcel_from_feature(features[0]) if features else None


def parcel_by_number(gush: int, helka: int) -> tuple[dict[str, Any], tuple[float, float] | None] | None:
    features = _cadastre(f"GUSH_NUM={int(gush)} AND PARCEL={int(helka)}")
    if not features:
        return None
    point = _point_inside(_outer_ring(features[0]))
    return _parcel_from_feature(features[0]), point


def _goal(value: Any) -> str:
    # The service joins the plan's name and its goals with carets.
    parts = [_one_line(part, 600) for part in str(value or "").split("^")]
    parts = [part for part in parts if part]
    return parts[1] if len(parts) > 1 else (parts[0] if parts else "")


def _plan(attributes: dict[str, Any]) -> dict[str, Any]:
    approved_on = _day(attributes.get("pl_date_8"))
    housing = attributes.get("quantity_delta_120")
    url = _one_line(attributes.get("pl_url"), 300)
    return {
        "number": _one_line(attributes.get("pl_number"), 80),
        "name": _one_line(attributes.get("pl_name"), 200),
        "kind": _one_line(attributes.get("entity_subtype_desc"), 60),
        "stage": _one_line(attributes.get("internet_short_status") or attributes.get("station_desc"), 80),
        "approved": bool(approved_on),
        "goal": _goal(attributes.get("pl_objectives")),
        "depositedOn": _day(attributes.get("depositing_date")),
        "objectionsUntil": _day(attributes.get("pl_rejection_date")),
        "approvedOn": approved_on,
        "lastUpdated": _day(attributes.get("last_update_date")),
        "housingUnitsChange": int(housing) if isinstance(housing, (int, float)) and housing else 0,
        "url": url if url.startswith("https://") else "",
    }


def plans_at(lat: float, lon: float, *, limit: int = PUBLIC_RECORDS_MAX_PLANS) -> tuple[list[dict[str, Any]], int]:
    """The plans whose blue line covers the point: open ones first, then the newest approved."""

    payload = _get_json(
        _base_url("PUBLIC_RECORDS_PLANS_URL", PLANS_QUERY_URL),
        {
            "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": ",".join(_PLAN_FIELDS),
            "returnGeometry": "false",
            "f": "json",
        },
        source="The Planning Administration map",
    )
    if not isinstance(payload, dict) or "error" in payload or not isinstance(payload.get("features"), list):
        raise PublicRecordsError("provider_unavailable", "The Planning Administration map did not answer with plans.")
    plans = [
        _plan(feature["attributes"])
        for feature in payload["features"]
        if isinstance(feature, dict) and isinstance(feature.get("attributes"), dict)
    ]
    plans = [plan for plan in plans if plan["number"] or plan["name"]]
    open_plans = sorted(
        (plan for plan in plans if not plan["approved"]),
        key=lambda plan: plan["depositedOn"] or plan["lastUpdated"],
        reverse=True,
    )
    approved = sorted((plan for plan in plans if plan["approved"]), key=lambda plan: plan["approvedOn"], reverse=True)
    ordered = open_plans + approved
    return ordered[:limit], len(ordered)


def _positive_int(value: Any) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,7})\s*", str(value if value is not None else ""))
    number = int(match.group(1)) if match else 0
    return number or None


def look_up_property(*, address: str = "", gush: Any = None, helka: Any = None) -> dict[str, Any]:
    """The parcel, its plans and how to order its Tabu extract, from an address or a gush and helka.

    Returns {"found": False, "reason": ...} when the place cannot be placed on
    the map; raises PublicRecordsError when a service cannot be read.
    """

    address = _one_line(address, 300)
    gush_number, helka_number = _positive_int(gush), _positive_int(helka)
    location: dict[str, Any] = {}
    point: tuple[float, float] | None = None
    parcel: dict[str, Any] | None = None

    if gush_number and helka_number:
        found = parcel_by_number(gush_number, helka_number)
        if not found:
            return {"found": False, "reason": f"No parcel {helka_number} in gush {gush_number} is on the Survey of Israel map."}
        parcel, point = found
        location = {"from": "gush and helka"}
    elif address:
        place = geocode_address(address)
        if not place:
            return {"found": False, "reason": "The address could not be placed on the map."}
        point = (place["lon"], place["lat"])
        location = {
            "from": "address",
            "matchedAddress": place["matchedAddress"],
            "exactBuilding": place["exactBuilding"],
        }
        parcel = parcel_at(place["lat"], place["lon"])
    else:
        return {"found": False, "reason": "An address, or a gush and helka, is needed."}

    plans: list[dict[str, Any]] = []
    plan_count = 0
    if point:
        plans, plan_count = plans_at(point[1], point[0])

    return {
        "found": True,
        "location": location,
        "parcel": parcel,
        "plans": plans,
        "planCount": plan_count,
        "sources": {
            "parcel": "Survey of Israel open cadastre",
            "plans": "Israel Planning Administration (iplan / mavat)",
        },
        "tabuExtract": {
            "url": TABU_EXTRACT_URL,
            "whatItHas": "the registered owners, mortgages, liens, warnings and restrictions",
            "howToOrder": (
                "Ordered and paid for online from the Land Registry with the gush and helka; a flat in a shared "
                "building also needs its sub-parcel (tat-helka), which is not always the flat number. It arrives "
                "by email within minutes."
            ),
        },
    }


__all__ = [
    "PUBLIC_RECORDS_MAX_PLANS",
    "PublicRecordsError",
    "TABU_EXTRACT_URL",
    "geocode_address",
    "look_up_property",
    "parcel_at",
    "parcel_by_number",
    "plans_at",
]
