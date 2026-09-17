from __future__ import annotations

import unittest
from unittest import mock

from packages.tools.public_records import lookup
from packages.tools.public_records.lookup import PublicRecordsError
from packages.tools.public_records.lookup import look_up_property


PARCEL = {
    "type": "Feature",
    "geometry": {
        "type": "MultiPolygon",
        "coordinates": [[[[34.7697, 32.0623], [34.7700, 32.0623], [34.7700, 32.0626], [34.7697, 32.0626], [34.7697, 32.0623]]]],
    },
    "properties": {"GUSH_NUM": 7422, "GUSH_SUFFI": 0, "PARCEL": 71, "LEGAL_AREA": 546, "STATUS_TEX": "מוסדר", "LOCALITY_N": "תל אביב -יפו"},
}


def _plan(number: str, *, approved_ms: int | None = None, deposited_ms: int | None = None, objections_ms: int | None = None) -> dict:
    return {"attributes": {
        "pl_number": number,
        "pl_name": f"plan {number}",
        "entity_subtype_desc": "תכנית מפורטת",
        "internet_short_status": "פרסום אישור" if approved_ms else "רישום התנגדויות",
        "pl_objectives": f"plan {number} ^ build more homes ^",
        "depositing_date": deposited_ms,
        "pl_rejection_date": objections_ms,
        "pl_date_8": approved_ms,
        "last_update_date": None,
        "quantity_delta_120": 24.0,
        "pl_url": f"https://mavat.iplan.gov.il/SV4/1/{number}/310",
    }}


class _Services:
    def __init__(self, *, geocoded: list | None = None, parcels: list | None = None, plans: list | None = None) -> None:
        self.geocoded = geocoded if geocoded is not None else [
            {"lat": "32.0625", "lon": "34.7699", "display_name": "10, הרצל, תל אביב", "address": {"house_number": "10"}},
        ]
        self.parcels = parcels if parcels is not None else [PARCEL]
        self.plans = plans if plans is not None else []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params: dict, *, source: str):
        self.calls.append((url, params))
        if url == lookup.GEOCODER_URL:
            return self.geocoded
        if url == lookup.CADASTRE_WFS_URL:
            return {"type": "FeatureCollection", "features": self.parcels}
        return {"features": self.plans}


class PublicRecordsTests(unittest.TestCase):
    def test_an_address_becomes_its_parcel_and_plans_with_open_ones_first(self) -> None:
        services = _Services(plans=[
            _plan("old", approved_ms=1468800000000),
            _plan("open", deposited_ms=1740355200000, objections_ms=1788739200000),
            _plan("new", approved_ms=1747785600000),
        ])
        with mock.patch.object(lookup, "_get_json", services):
            result = look_up_property(address="הרצל 10 תל אביב")

        self.assertTrue(result["found"])
        self.assertEqual(result["parcel"]["gush"], 7422)
        self.assertEqual(result["parcel"]["helka"], 71)
        self.assertIsNone(result["parcel"]["gushSuffix"])
        self.assertTrue(result["location"]["exactBuilding"])
        self.assertEqual([plan["number"] for plan in result["plans"]], ["open", "new", "old"])
        self.assertEqual(result["plans"][0]["objectionsUntil"], "2026-09-07")
        self.assertEqual(result["plans"][0]["goal"], "build more homes")
        self.assertEqual(result["plans"][1]["approvedOn"], "2025-05-21")
        self.assertEqual(result["plans"][1]["housingUnitsChange"], 24)
        self.assertEqual(result["tabuExtract"]["url"], lookup.TABU_EXTRACT_URL)
        cql = services.calls[1][1]["CQL_FILTER"]
        self.assertIn("POINT(34.7699000 32.0625000)", cql)

    def test_an_address_without_a_house_number_is_not_called_exact(self) -> None:
        services = _Services(geocoded=[{"lat": "32.06", "lon": "34.77", "display_name": "הרצל", "address": {"road": "הרצל"}}])
        with mock.patch.object(lookup, "_get_json", services):
            result = look_up_property(address="הרצל תל אביב")

        self.assertFalse(result["location"]["exactBuilding"])

    def test_a_gush_and_helka_are_looked_up_and_plans_read_inside_the_parcel(self) -> None:
        services = _Services()
        with mock.patch.object(lookup, "_get_json", services):
            result = look_up_property(gush="7422", helka=71)

        self.assertEqual(services.calls[0][1]["CQL_FILTER"], "GUSH_NUM=7422 AND PARCEL=71")
        self.assertEqual(result["location"], {"from": "gush and helka"})
        geometry = services.calls[1][1]["geometry"]
        self.assertIn('"x": 34.76985', geometry)

    def test_a_place_that_is_not_on_the_map_is_not_found(self) -> None:
        with mock.patch.object(lookup, "_get_json", _Services(geocoded=[])):
            self.assertFalse(look_up_property(address="nowhere")["found"])
        with mock.patch.object(lookup, "_get_json", _Services(parcels=[])):
            self.assertFalse(look_up_property(gush=1, helka=1)["found"])
        self.assertFalse(look_up_property()["found"])

    def test_a_planning_service_error_is_raised_not_read_as_no_plans(self) -> None:
        services = _Services()
        services.plans = None

        def failing(url: str, params: dict, *, source: str):
            if url == lookup.PLANS_QUERY_URL:
                return {"error": {"code": 500}}
            return services(url, params, source=source)

        with mock.patch.object(lookup, "_get_json", failing):
            with self.assertRaises(PublicRecordsError):
                look_up_property(address="הרצל 10 תל אביב")

    def test_an_l_shaped_parcel_gets_a_point_inside_it(self) -> None:
        ring = [[0, 0], [10, 0], [10, 1], [1, 1], [1, 10], [0, 10], [0, 0]]
        point = lookup._point_inside(ring)

        self.assertIsNotNone(point)
        self.assertTrue(lookup._inside(point, ring))


if __name__ == "__main__":
    unittest.main()
