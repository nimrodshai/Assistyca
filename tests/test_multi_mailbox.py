"""Several mailboxes on one account, and what an action does with them.

Connecting a second mailbox used to overwrite the first, because a connection
was unique per platform. These tests pin the behaviour that replaced it: two
mailboxes coexist, an action reads all of them by default, it can be narrowed
to one, and one broken mailbox does not sink the run.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.gmail_summary import GmailAuthorizationError
from packages.infrastructure.portal_auth.server import GOOGLE_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import MICROSOFT_OAUTH_SECRET_TYPE
from packages.infrastructure.portal_auth.server import MICROSOFT_OUTLOOK_OAUTH_PROVIDER
from packages.infrastructure.portal_auth.server import PortalConfig
from packages.infrastructure.portal_auth.server import create_server
from packages.infrastructure.portal_auth.server import merge_mail_digest_results

SERVER_MODULE = "packages.infrastructure.portal_auth.server"


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _token_endpoint_patch(responder):
    """Patch the providers' token endpoints, leaving the portal's own calls alone."""

    real_urlopen = urllib_request.urlopen
    token_hosts = ("login.microsoftonline.com", "oauth2.googleapis.com")

    def fake_urlopen(request, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        if any(host in url for host in token_hosts):
            return responder(request)
        return real_urlopen(request, timeout=timeout, **kwargs)

    return mock.patch(f"{SERVER_MODULE}.urllib_request.urlopen", side_effect=fake_urlopen)


class MultiMailboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(__file__).resolve().parents[1]
        key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
        self.server = create_server(
            "127.0.0.1",
            0,
            root,
            PortalConfig(
                db_path=Path(self.temp_dir.name) / "portal.db",
                credential_encryption_key=key,
                agent_output_dir=Path(self.temp_dir.name) / "agent_outputs",
                session_secret="test-session-secret-that-is-long-enough-to-sign",
                google_oauth_client_id="google-client-id.apps.googleusercontent.com",
                google_oauth_client_secret="google-client-secret",
                microsoft_oauth_client_id="microsoft-client-id",
                microsoft_oauth_client_secret="microsoft-client-secret",
            ),
        )
        if self.server.credential_vault is None:
            self.server.server_close()
            self.skipTest("cryptography is installed in deployment, not this minimal test environment")
        self.server.database.register_user("owner@example.com")
        code, _ = self.server.store.issue_challenge("owner@example.com")
        ok, _, session = self.server.store.verify_code("owner@example.com", code)
        assert ok and session is not None
        self.session_token = session["token"]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path: str, body: dict[str, object]):  # type: ignore[no-untyped-def]
        return urllib_request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

    def _save_gmail(self, address: str, *, label: str = "") -> None:
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": GOOGLE_OAUTH_SECRET_TYPE,
                "provider": "google",
                "refreshToken": f"refresh-for-{address}",
            })),
            secret_hint="Google OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            account_address=address,
            account_label=label,
            metadata={"provider": "google_gmail", "validationStatus": "verified"},
        )

    def _save_outlook(self, address: str, *, label: str = "") -> None:
        self.server.database.save_platform_connection(
            "owner@example.com",
            platform="email",
            auth_type="oauth",
            secret_ciphertext=self.server.credential_vault.encrypt(json.dumps({  # type: ignore[union-attr]
                "type": MICROSOFT_OAUTH_SECRET_TYPE,
                "provider": "microsoft",
                "refreshToken": f"refresh-for-{address}",
            })),
            secret_hint="Microsoft OAuth",
            key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            connection_status="connected",
            account_address=address,
            account_label=label,
            metadata={"provider": MICROSOFT_OUTLOOK_OAUTH_PROVIDER, "validationStatus": "verified"},
        )

    def _run_receipts(self, fields: dict[str, object]):  # type: ignore[no-untyped-def]
        def responder(request):  # type: ignore[no-untyped-def]
            return _FakeResponse({"access_token": "fresh-access-token"})

        with _token_endpoint_patch(responder):
            with urllib_request.urlopen(
                self._post("/api/agent/proposals/run", {
                    "proposalType": "email-digest",
                    "fields": fields,
                }),
                timeout=5,
            ) as response:
                return json.loads(response.read().decode("utf-8"))

    # --- storage -------------------------------------------------------------

    def test_connecting_outlook_no_longer_replaces_a_connected_gmail(self) -> None:
        # This is the whole point: these used to collide on (user, platform).
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        connections = self.server.database.list_platform_connections("owner@example.com")
        addresses = sorted(item["accountAddress"] for item in connections)

        self.assertEqual(addresses, ["personal@gmail.com", "work@contoso.com"])

    def test_reconnecting_the_same_address_updates_it_in_place(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_gmail("personal@gmail.com")

        self.assertEqual(len(self.server.database.list_platform_connections("owner@example.com")), 1)

    def test_a_single_account_platform_still_holds_one_row(self) -> None:
        # Calendar and Drive save with no address, so they keep colliding by
        # design and a reconnect replaces rather than accumulates.
        for _ in range(2):
            self.server.database.save_platform_connection(
                "owner@example.com",
                platform="calendar",
                auth_type="oauth",
                secret_ciphertext=self.server.credential_vault.encrypt("{}"),  # type: ignore[union-attr]
                secret_hint="Google OAuth",
                key_version=self.server.credential_vault.key_version,  # type: ignore[union-attr]
            )

        calendars = [
            item for item in self.server.database.list_platform_connections("owner@example.com")
            if item["platform"] == "calendar"
        ]
        self.assertEqual(len(calendars), 1)

    # --- running across mailboxes -------------------------------------------

    def test_an_action_reads_every_mailbox_when_it_names_none(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        gmail_result = {"summary": "Gmail digest - 1 message", "messageCount": 1, "items": [{"subject": "A"}]}
        outlook_result = {"summary": "Outlook digest - 2 messages", "messageCount": 2, "items": [{"subject": "B"}, {"subject": "C"}]}

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", return_value=gmail_result):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value=outlook_result):
                payload = self._run_receipts({"deliveryChannel": "portal"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["messageCount"], 3)
        self.assertEqual(len(payload["items"]), 3)
        self.assertEqual(sorted(payload["mailboxes"]), ["personal@gmail.com", "work@contoso.com"])

    def test_every_merged_item_says_which_mailbox_it_came_from(self) -> None:
        # A merged receipt bundle has to be able to attribute each row.
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", return_value={"messageCount": 1, "items": [{"subject": "A"}]}):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value={"messageCount": 1, "items": [{"subject": "B"}]}):
                payload = self._run_receipts({"deliveryChannel": "portal"})

        self.assertEqual(
            sorted(item["mailbox"] for item in payload["items"]),
            ["personal@gmail.com", "work@contoso.com"],
        )

    def test_an_action_can_be_narrowed_to_one_mailbox(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run") as gmail_run:
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value={"messageCount": 1, "items": []}) as outlook_run:
                payload = self._run_receipts({
                    "deliveryChannel": "portal",
                    "mailboxAccount": "work@contoso.com",
                })

        self.assertTrue(payload["ok"])
        outlook_run.assert_called_once()
        gmail_run.assert_not_called()
        self.assertEqual(payload["mailboxes"], ["work@contoso.com"])

    def test_a_narrowed_action_can_name_its_mailbox_by_label(self) -> None:
        # A saved action keeps working after the address is relabelled.
        self._save_gmail("personal@gmail.com", label="Personal")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", return_value={"messageCount": 1, "items": []}) as gmail_run:
            payload = self._run_receipts({"deliveryChannel": "portal", "mailboxAccount": "Personal"})

        self.assertTrue(payload["ok"])
        gmail_run.assert_called_once()

    def test_naming_a_mailbox_that_is_gone_says_so_instead_of_reading_another(self) -> None:
        # Silently falling back to a different mailbox would put someone
        # else's receipts in the bundle.
        self._save_gmail("personal@gmail.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run") as gmail_run:
            with self.assertRaises(urllib_error.HTTPError) as caught:
                self._run_receipts({"deliveryChannel": "portal", "mailboxAccount": "deleted@gmail.com"})

        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(json.loads(caught.exception.read())["error"], "mailbox_not_connected")
        gmail_run.assert_not_called()

    # --- one mailbox failing -------------------------------------------------

    def test_one_broken_mailbox_does_not_sink_the_others(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", side_effect=GmailAuthorizationError("Gmail access needs attention.")):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value={"messageCount": 2, "items": [{"subject": "B"}, {"subject": "C"}]}):
                payload = self._run_receipts({"deliveryChannel": "portal"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["messageCount"], 2)
        self.assertEqual(payload["mailboxes"], ["work@contoso.com"])

    def test_a_partial_run_reports_the_mailbox_it_skipped(self) -> None:
        # Otherwise it silently returns fewer receipts than the user has.
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", side_effect=GmailAuthorizationError("Gmail access needs attention.")):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value={"messageCount": 1, "items": []}):
                payload = self._run_receipts({"deliveryChannel": "portal"})

        skipped = payload["skippedMailboxes"]
        self.assertEqual([entry["mailbox"] for entry in skipped], ["personal@gmail.com"])

    def test_only_the_broken_mailbox_is_flagged_for_attention(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_outlook("work@contoso.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", side_effect=GmailAuthorizationError("Gmail access needs attention.")):
            with mock.patch(f"{SERVER_MODULE}.OutlookDigestRunner.run", return_value={"messageCount": 1, "items": []}):
                self._run_receipts({"deliveryChannel": "portal"})

        statuses = {
            item["accountAddress"]: item["connectionStatus"]
            for item in self.server.database.list_platform_connections("owner@example.com")
        }
        self.assertEqual(statuses["personal@gmail.com"], "needs_attention")
        self.assertEqual(statuses["work@contoso.com"], "connected")

    def test_the_run_fails_only_when_every_mailbox_fails(self) -> None:
        self._save_gmail("personal@gmail.com")
        self._save_gmail("second@gmail.com")

        with mock.patch(f"{SERVER_MODULE}.GmailDigestRunner.run", side_effect=GmailAuthorizationError("Gmail access needs attention.")):
            with self.assertRaises(urllib_error.HTTPError) as caught:
                self._run_receipts({"deliveryChannel": "portal"})

        self.assertEqual(caught.exception.code, 409)


class MergeMailDigestResultTests(unittest.TestCase):
    def test_a_single_mailbox_keeps_the_wording_its_reader_produced(self) -> None:
        # Everyone connected today has one mailbox; their runs must not change.
        merged = merge_mail_digest_results([
            {"mailbox": "personal@gmail.com", "result": {
                "message": "Gmail digest\n\n1 recent message",
                "summary": "Gmail digest - 1 message",
                "messageCount": 1,
                "items": [{"subject": "A"}],
            }},
        ])

        self.assertEqual(merged["summary"], "Gmail digest - 1 message")
        self.assertEqual(merged["messageCount"], 1)

    def test_several_mailboxes_get_a_combined_summary(self) -> None:
        merged = merge_mail_digest_results([
            {"mailbox": "a@example.com", "result": {"summary": "Gmail digest - 1 message", "messageCount": 1, "items": [{"subject": "A"}]}},
            {"mailbox": "b@example.com", "result": {"summary": "Outlook digest - 2 messages", "messageCount": 2, "items": [{"subject": "B"}, {"subject": "C"}]}},
        ])

        self.assertEqual(merged["messageCount"], 3)
        self.assertEqual(merged["summary"], "2 mailboxes - 3 message(s)")

    def test_a_reader_that_already_named_the_mailbox_is_left_alone(self) -> None:
        merged = merge_mail_digest_results([
            {"mailbox": "a@example.com", "result": {"messageCount": 1, "items": [{"subject": "A", "mailbox": "shared@example.com"}]}},
        ])

        self.assertEqual(merged["items"][0]["mailbox"], "shared@example.com")


if __name__ == "__main__":
    unittest.main()
