"""Tags on a filed receipt, and the folder file that keeps them.

A PDF in a folder is findable only by its name, and the name is whatever the
vendor called it. The tags are the handle: who it is from, when it is from,
and whether it calls itself an invoice or a receipt.
"""

from __future__ import annotations

import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.infrastructure.file_tags import FILE_TAGS_FILENAME
from packages.infrastructure.file_tags import build_receipt_file_tags
from packages.infrastructure.file_tags import collect_folder_tags
from packages.infrastructure.file_tags import describe_document_kind
from packages.infrastructure.file_tags import read_file_tags
from packages.infrastructure.file_tags import write_file_tags


class ReceiptTagTests(unittest.TestCase):
    def test_a_receipt_is_tagged_with_who_when_and_what(self) -> None:
        tags = build_receipt_file_tags(
            vendor="Render",
            subject="Your receipt from Render",
            filename="receipt-8891.pdf",
            date_text="Fri, 1 Aug 2026 09:00:00 +0000",
        )

        self.assertEqual(tags, ["Render", "Aug", "2026", "Receipt"])

    def test_an_invoice_is_not_tagged_as_a_receipt(self) -> None:
        # A vendor sends both for one charge, and the difference is the thing
        # a bookkeeper sorts on.
        tags = build_receipt_file_tags(
            vendor="Render",
            subject="Your receipt from Render",
            filename="Invoice-8891.pdf",
            date_text="Fri, 1 Aug 2026 09:00:00 +0000",
        )

        self.assertIn("Invoice", tags)
        self.assertNotIn("Receipt", tags)

    def test_a_file_that_says_neither_is_not_labelled_either(self) -> None:
        # A wrong tag is worse than a missing one, so nothing is guessed.
        self.assertEqual(describe_document_kind("statement-8891.pdf", "August summary"), "")

    def test_a_date_written_the_other_way_still_gives_a_month(self) -> None:
        tags = build_receipt_file_tags(vendor="Render", date_text="2026-08-01T09:00:00Z")

        self.assertEqual(tags, ["Render", "Aug", "2026"])

    def test_an_email_with_no_date_is_tagged_with_what_is_known(self) -> None:
        self.assertEqual(build_receipt_file_tags(vendor="Render", filename="receipt.pdf"), ["Render", "Receipt"])

    def test_a_receipt_that_names_nothing_gets_no_tags(self) -> None:
        self.assertEqual(build_receipt_file_tags(), [])


class FolderTagFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.folder = Path(self.temp_dir.name) / "Render"

    def test_tags_survive_a_round_trip(self) -> None:
        write_file_tags(self.folder, {"Render - receipt.pdf": ["Render", "Aug", "2026", "Receipt"]})

        self.assertEqual(
            read_file_tags(self.folder),
            {"Render - receipt.pdf": ["Render", "Aug", "2026", "Receipt"]},
        )

    def test_filing_a_second_receipt_keeps_the_first_one_tagged(self) -> None:
        write_file_tags(self.folder, {"one.pdf": ["Render", "Jul"]})
        write_file_tags(self.folder, {"two.pdf": ["Render", "Aug"]})

        self.assertEqual(sorted(read_file_tags(self.folder)), ["one.pdf", "two.pdf"])

    def test_a_folder_with_no_tag_file_reads_as_untagged(self) -> None:
        self.assertEqual(read_file_tags(self.folder), {})

    def test_a_tag_file_someone_broke_does_not_break_the_listing(self) -> None:
        # Losing the tags is a worse outcome than a listing showing none.
        self.folder.mkdir(parents=True)
        (self.folder / FILE_TAGS_FILENAME).write_text("{not json", encoding="utf-8")

        self.assertEqual(read_file_tags(self.folder), {})

    def test_the_folder_lists_every_tag_in_it_once(self) -> None:
        tags = collect_folder_tags({
            "one.pdf": ["Render", "Aug", "2026", "Receipt"],
            "two.pdf": ["Render", "Aug", "2026", "Invoice"],
        })

        self.assertEqual(tags, ["2026", "Aug", "Invoice", "Receipt", "Render"])

    def test_nonsense_in_place_of_tags_is_dropped(self) -> None:
        write_file_tags(self.folder, {"one.pdf": ["Render", "", None, "render"]})

        self.assertEqual(read_file_tags(self.folder), {"one.pdf": ["Render"]})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the portal script")
class FolderPanelTagTests(unittest.TestCase):
    """The panel side: filtering by a tag, and completing one."""

    def setUp(self) -> None:
        self.script = (Path(__file__).resolve().parents[1] / "portal" / "app.js").read_text(encoding="utf-8")

    def _run(self, setup: str, expression: str) -> object:
        helpers = self.script[
            self.script.index("function getAgentFolderSearchText"):
            self.script.index("function getFilteredAgentFolders")
        ]
        completed = subprocess.run(
            ["node", "-e", f"{setup}\n{helpers}\nconsole.log(JSON.stringify({expression}));"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    # The helpers reach for the workspace and the loaded-folder cache, so the
    # test stands both up rather than reaching into the browser.
    SETUP = """
const folders = [{ name: "Render", type: "receipts", itemCount: 2, tags: ["Render", "Aug", "2026", "Receipt"] }];
const agentFolderContents = new Map([["Render", { status: "ready", items: [
  { name: "Render - receipt.pdf", tags: ["Render", "Aug", "2026", "Receipt"] },
  { name: "Render - invoice.pdf", tags: ["Render", "Aug", "2026", "Invoice"] },
] }]]);
function getAgentWorkspace() { return { folders }; }
function normalizeAgentTextItem(value, fallback = "") { return String(value ?? "").trim() || fallback; }
function getAgentFolderTypeOption() { return { value: "receipts", label: "Receipts" }; }
function formatAgentFolderItemCount(count) { return `${count} items`; }
const AGENT_MAX_FOLDER_TAGS = 40;
function mergeAgentFolderTags(...lists) {
  const tags = [];
  const seen = new Set();
  lists.forEach((list) => {
    (Array.isArray(list) ? list : []).forEach((value) => {
      const tag = String(value || "").trim().slice(0, 40);
      if (!tag || seen.has(tag.toLowerCase())) { return; }
      seen.add(tag.toLowerCase());
      tags.push(tag);
    });
  });
  return tags.slice(0, AGENT_MAX_FOLDER_TAGS);
}
"""

    def test_a_folder_is_found_by_a_tag_on_the_files_inside_it(self) -> None:
        text = self._run(self.SETUP, "getAgentFolderSearchText(folders[0])")

        self.assertIn("aug", str(text))
        self.assertIn("invoice", str(text))

    def test_the_filter_box_knows_the_tags_already_in_use(self) -> None:
        tags = self._run(self.SETUP, "getKnownAgentFolderTags()")

        self.assertEqual(tags, ["2026", "Aug", "Invoice", "Receipt", "Render"])

    def test_a_file_is_matched_by_its_tag_as_well_as_its_name(self) -> None:
        matched = self._run(
            self.SETUP,
            'agentFolderFileMatchesSearch({ name: "Render - invoice.pdf", tags: ["Aug"] }, "aug")',
        )

        self.assertTrue(matched)

    def test_a_file_the_query_says_nothing_about_does_not_match(self) -> None:
        matched = self._run(
            self.SETUP,
            'agentFolderFileMatchesSearch({ name: "Render - invoice.pdf", tags: ["Aug"] }, "jul")',
        )

        self.assertFalse(matched)


if __name__ == "__main__":
    unittest.main()
