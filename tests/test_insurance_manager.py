"""Versioned insurance storage and conservative receipt screening."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from packages.infrastructure.agent_loop import LoopContext
from packages.infrastructure.agent_loop import TOOLS_BY_NAME
from packages.infrastructure.agent_loop import _tool_search_receipts
from packages.infrastructure.portal_db import PortalDatabase
from packages.infrastructure.receipt_collector import create_receipt_bundle


def coverage(
    *,
    category: str = "veterinary",
    deductible: str = "100",
    evidence: bool = True,
    conditions: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> dict:
    return {
        "category": category,
        "summary": "Eligible veterinary treatment after the deductible.",
        "coveredSubjects": ["Milo"],
        "conditions": conditions or [],
        "exclusions": exclusions or [],
        "limitAmount": "5000",
        "deductibleAmount": deductible,
        "currency": "USD",
        "claimDeadlineDays": 30,
        "evidence": ({"section": "Veterinary expenses", "pages": "12-13"} if evidence else {}),
    }


def version(
    *,
    start: str = "2026-01-01",
    end: str = "2026-12-31",
    deductible: str = "100",
    source_text: str = "Section 4: eligible veterinary treatment after the deductible.",
    evidence: bool = True,
) -> dict:
    return {
        "effectiveFrom": start,
        "effectiveTo": end,
        "summary": "Pet cover for Milo.",
        "coverages": [coverage(deductible=deductible, evidence=evidence)],
        "reviewStatus": "reviewed",
        "sourceName": "milo-policy.txt",
        "sourceMimeType": "text/plain",
        "sourceReference": "Section 4",
        "sourceText": source_text,
    }


class InsuranceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = PortalDatabase(Path(self.temp_dir.name) / "portal.db")
        self.database.register_user("owner@example.com")
        self.user_id = int((self.database.get_user("owner@example.com") or {})["id"])

    def save(self, *, policy_id: int | None = None, version_data: dict | None = None) -> dict:
        return self.database.save_insurance_policy_version(
            user_id=self.user_id,
            policy={
                "id": policy_id,
                "name": "Milo pet insurance",
                "insurer": "Good Cover",
                "policyNumber": "PET-12345678",
                "policyType": "pet",
                "coveredSubject": "Milo",
                "status": "active",
            },
            version=version_data or version(),
        )

    def test_keeps_original_and_structured_summary_separately(self) -> None:
        record = self.save()

        self.assertEqual(record["policyNumberHint"], "••••5678")
        self.assertEqual(record["currentVersion"]["summary"], "Pet cover for Milo.")
        self.assertTrue(record["currentVersion"]["sourceStored"])
        self.assertNotIn("sourceText", record["currentVersion"])

        source = self.database.get_insurance_policy_source(
            user_id=self.user_id,
            version_id=record["currentVersion"]["id"],
        )
        self.assertIn("Section 4", source["sourceText"])
        self.assertEqual(source["sourceDocument"], b"")

    def test_an_identical_save_does_not_make_a_second_version(self) -> None:
        first = self.save()
        repeated = self.save(policy_id=first["id"])

        self.assertTrue(first["versionCreated"])
        self.assertFalse(repeated["versionCreated"])
        self.assertEqual(len(repeated["versions"]), 1)

    def test_renewal_is_a_new_version_and_receipt_date_selects_old_wording(self) -> None:
        original = self.save()
        renewed = self.save(
            policy_id=original["id"],
            version_data=version(start="2027-01-01", end="2027-12-31", deductible="250", source_text="2027 wording"),
        )

        self.assertEqual(len(renewed["versions"]), 2)
        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={
                "date": "2026-06-10",
                "amount": "150",
                "currency": "USD",
                "category": "vet",
                "description": "Treatment for Milo",
            },
        )

        self.assertEqual(result["matchCount"], 1)
        self.assertEqual(result["matches"][0]["versionNumber"], 1)
        self.assertEqual(result["matches"][0]["status"], "likely_worth_claiming")
        self.assertEqual(result["matches"][0]["claimDeadlineEstimate"], "2026-07-10")
        self.assertEqual(result["matches"][0]["claimDeadlineBasis"], "receipt_date_assumed_event_date")
        self.assertTrue(any("receipt date" in note for note in result["matches"][0]["notes"]))

    def test_receipt_below_deductible_is_not_presented_as_a_good_claim(self) -> None:
        self.save()
        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={"date": "2026-05-01", "amount": "80", "currency": "USD", "category": "pet"},
        )

        self.assertEqual(result["matches"][0]["status"], "deductible_may_exceed_expense")
        self.assertIn("does not exceed", result["matches"][0]["notes"][0])

    def test_an_expired_policy_still_matches_a_receipt_from_when_it_was_in_force(self) -> None:
        record = self.save()
        self.database.save_insurance_policy_version(
            user_id=self.user_id,
            policy={
                "id": record["id"],
                "name": "Milo pet insurance",
                "insurer": "Good Cover",
                "policyType": "pet",
                "coveredSubject": "Milo",
                "status": "expired",
            },
            version=version(),
        )

        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={
                "date": "Thu, 02 Jul 2026 10:00:00 +0300",
                "amount": "250 USD",
                "category": "vet",
            },
        )

        self.assertEqual(result["matchCount"], 1)
        self.assertEqual(result["expense"]["date"], "2026-07-02")
        self.assertEqual(result["expense"]["amount"], "250.00")

    def test_summary_only_match_stays_provisional_even_with_an_evidence_label(self) -> None:
        data = version(source_text="")
        self.save(version_data=data)

        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={"date": "2026-05-01", "amount": "800", "currency": "USD", "category": "veterinary"},
        )

        match = result["matches"][0]
        self.assertEqual(match["status"], "possible_more_information_needed")
        self.assertEqual(match["evidenceStatus"], "summary_only")

    def test_unreviewed_source_backed_match_stays_provisional(self) -> None:
        data = version()
        data["reviewStatus"] = "unreviewed"
        self.save(version_data=data)

        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={"date": "2026-05-01", "amount": "800", "currency": "USD", "category": "veterinary"},
        )

        match = result["matches"][0]
        self.assertEqual(match["status"], "possible_more_information_needed")
        self.assertTrue(any("human-reviewed" in note for note in match["notes"]))

    def test_policy_source_and_matches_are_account_scoped(self) -> None:
        record = self.save()
        self.database.register_user("other@example.com")
        other_id = int((self.database.get_user("other@example.com") or {})["id"])

        self.assertEqual(self.database.list_insurance_policies(user_id=other_id), [])
        self.assertIsNone(self.database.get_insurance_policy_source(
            user_id=other_id,
            version_id=record["currentVersion"]["id"],
        ))

    def test_archived_policy_is_not_used_for_future_screening(self) -> None:
        record = self.save()
        self.assertTrue(self.database.archive_insurance_policy(user_id=self.user_id, policy_id=record["id"]))

        result = self.database.check_insurance_expense(
            user_id=self.user_id,
            expense={"date": "2026-05-01", "amount": "800", "currency": "USD", "category": "pet"},
        )

        self.assertEqual(result["status"], "no_relevant_policy")

    def test_deleting_account_deletes_policy_sources(self) -> None:
        record = self.save()
        version_id = record["currentVersion"]["id"]

        self.database.delete_user("owner@example.com")

        self.assertIsNone(self.database.get_insurance_policy_source(user_id=self.user_id, version_id=version_id))

    def test_receipt_search_automatically_surfaces_a_potential_claim(self) -> None:
        self.save()

        def api(method: str, path: str, payload: dict) -> tuple[dict, int]:
            self.assertEqual(path, "/api/agent/proposals/run")
            return ({
                "answer": "One receipt found.",
                "answerRecords": [{
                    "sourceRef": "mail-1",
                    "date": "2026-04-10",
                    "vendor": "City Veterinary Clinic",
                    "subject": "Veterinary receipt for Milo",
                    "amount": "240",
                    "currency": "USD",
                    "status": "Ready",
                }],
            }, 200)

        context = LoopContext(api=api, database=self.database, email="owner@example.com", user_id=self.user_id)
        outcome = _tool_search_receipts(context, {"what": "Find April vet receipts", "vendor": None, "months": "2026-04"})

        checks = outcome["insuranceChecks"]
        self.assertEqual(checks["checkedReceiptCount"], 1)
        self.assertEqual(checks["potentialClaimCount"], 1)
        self.assertEqual(checks["receipts"][0]["matches"][0]["policyName"], "Milo pet insurance")

    def test_documented_receipt_keeps_its_policy_screen_in_the_manifest(self) -> None:
        self.save()
        bundle = create_receipt_bundle(
            [{
                "id": "mail-1",
                "date": "Thu, 02 Jul 2026 10:00:00 +0300",
                "from": "City Veterinary Clinic <billing@vet.example>",
                "subject": "Veterinary receipt for Milo",
                "snippet": "Payment received. Total USD 240.00",
                "receiptVerdict": {"isReceipt": True, "paidTo": "City Veterinary Clinic"},
            }],
            output_root=Path(self.temp_dir.name) / "receipts",
            owner_key="owner",
            output_folder="Receipts/Jul2026",
            insurance_check=lambda expense: self.database.check_insurance_expense(
                user_id=self.user_id,
                expense=expense,
            ),
        )

        self.assertEqual(bundle["insuranceScreenedCount"], 1)
        self.assertEqual(bundle["insurancePotentialClaimCount"], 1)
        manifest = json.loads(Path(bundle["artifacts"]["manifest"]["path"]).read_text(encoding="utf-8"))
        check = manifest["receipts"][0]["insuranceCheck"]
        self.assertEqual(check["status"], "potential_claims_found")
        self.assertEqual(check["matches"][0]["policyName"], "Milo pet insurance")
        self.assertEqual(manifest["metadata"]["insuranceScreenedCount"], 1)

    def test_agent_exposes_policy_management_and_screening_tools(self) -> None:
        self.assertIn("save_insurance_policy", TOOLS_BY_NAME)
        self.assertIn("show_insurance_policies", TOOLS_BY_NAME)
        self.assertIn("check_insurance_expense", TOOLS_BY_NAME)
        self.assertIn("archive_insurance_policy", TOOLS_BY_NAME)

    def test_policy_photo_is_preserved_when_saved_from_the_chat(self) -> None:
        photo_bytes = b"not-a-real-image-but-normalized-before-this-boundary"
        context = LoopContext(
            api=lambda *_args, **_kwargs: ({}, 500),
            database=self.database,
            email="owner@example.com",
            user_id=self.user_id,
            attached_photo={
                "fileName": "policy.png",
                "mimeType": "image/png",
                "dataUrl": "data:image/png;base64," + base64.b64encode(photo_bytes).decode("ascii"),
            },
        )
        outcome = TOOLS_BY_NAME["save_insurance_policy"].run(context, {
            "policy_id": None,
            "name": "Milo photo policy",
            "insurer": "Good Cover",
            "policy_number": "12345678",
            "policy_type": "pet",
            "covered_subject": "Milo",
            "status": "active",
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "summary": "Pet cover.",
            "coverages": [{
                "category": "pet",
                "summary": "Veterinary treatment.",
                "covered_subjects": ["Milo"],
                "conditions": [],
                "exclusions": [],
                "limit_amount": "5000",
                "deductible_amount": "100",
                "currency": "USD",
                "claim_deadline_days": 30,
                "evidence_section": "Section 4",
                "evidence_pages": "12",
                "evidence_quote": None,
            }],
            "source_name": None,
            "source_mime_type": None,
            "source_reference": "attached photo",
            "source_text": None,
            "human_reviewed": False,
        })

        self.assertTrue(outcome["ok"])
        policy = self.database.list_insurance_policies(user_id=self.user_id)[0]
        source = self.database.get_insurance_policy_source(
            user_id=self.user_id,
            version_id=policy["latestVersion"]["id"],
        )
        self.assertEqual(source["sourceDocument"], photo_bytes)
        self.assertEqual(source["sourceName"], "policy.png")


if __name__ == "__main__":
    unittest.main()
