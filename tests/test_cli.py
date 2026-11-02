import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from iledger.cli import app
from iledger.storage import compare_files, load_manifest


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        self.root.mkdir()
        self.baseline = self.root / ".iledger/baseline.json"
        self.runner = CliRunner()

    def invoke(self, *args):
        return self.runner.invoke(app, [str(arg) for arg in args])

    def create_baseline(self, *args):
        result = self.invoke("baseline", self.root, *args)
        self.assertEqual(result.exit_code, 0, result.output)

    def test_end_to_end_and_json_hash_details(self):
        for name in ("keep", "modify", "remove"):
            (self.root / name).write_text("original")
        self.create_baseline()
        clean = self.invoke("check", self.baseline, "--json")
        self.assertEqual(clean.exit_code, 0, clean.output)
        self.assertEqual(json.loads(clean.output)["unchanged"], 3)
        (self.root / "modify").write_text("modified")
        (self.root / "remove").unlink()
        (self.root / "new").write_text("new")
        changed = self.invoke("check", self.baseline, "--json")
        self.assertEqual(changed.exit_code, 1, changed.output)
        data = json.loads(changed.output)
        self.assertEqual(data["added"], ["new"])
        self.assertEqual(data["modified"], ["modify"])
        self.assertEqual(data["missing"], ["remove"])
        self.assertEqual(data["unchanged"], 1)
        self.assertNotEqual(
            data["changes"]["modify"]["before"]["sha256"],
            data["changes"]["modify"]["after"]["sha256"],
        )
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 1)

    def test_mtime_only_changes_do_not_change_content_result(self):
        path = self.root / "same"
        path.write_text("same bytes")
        self.create_baseline()
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 0)

    def test_requires_force_to_replace_baseline(self):
        self.create_baseline()
        original = self.baseline.read_bytes()
        (self.root / "new").write_text("new")
        self.assertEqual(self.invoke("baseline", self.root).exit_code, 2)
        self.assertEqual(self.baseline.read_bytes(), original)
        self.create_baseline("--force")
        self.assertIn("new", load_manifest(self.baseline)["files"])

    def test_custom_baseline_inside_root_excludes_itself(self):
        self.baseline = self.root / "snapshot[1].json"
        (self.root / "nested").mkdir()
        (self.root / "nested/snapshot[1].json").write_text("evidence with same name")
        self.create_baseline("-o", self.baseline)
        self.assertIn("nested/snapshot[1].json", load_manifest(self.baseline)["files"])
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 0)

    def test_scan_failure_never_writes_baseline(self):
        (self.root / "link").symlink_to("absent")
        self.assertEqual(self.invoke("baseline", self.root).exit_code, 2)
        self.assertFalse(self.baseline.exists())
        self.create_baseline("--exclude", "link")
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 0)

    def test_read_error_is_incomplete_not_missing(self):
        (self.root / "locked").write_text("evidence")
        self.create_baseline()
        with patch("iledger.hashing.fingerprint", side_effect=PermissionError("denied")):
            result = self.invoke("check", self.baseline, "--json")
        self.assertEqual(result.exit_code, 2)
        data = json.loads(result.output)
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["missing"], [])
        self.assertIn("locked", data["errors"])

    def test_directory_errors_do_not_report_children_missing(self):
        diff = compare_files({"locked/file": {}}, {}, {"locked": "denied"})
        self.assertEqual(diff["missing"], [])

    def test_invalid_baselines_return_json_error(self):
        self.baseline.parent.mkdir()
        for invalid in ("{", "[]", '{"schema_version": 99}'):
            self.baseline.write_text(invalid)
            result = self.invoke("check", self.baseline, "--json")
            self.assertEqual(result.exit_code, 2)
            self.assertEqual(json.loads(result.output)["status"], "error")

    def test_missing_root_is_error_not_all_files_missing(self):
        self.create_baseline()
        result = self.invoke("check", self.baseline, "--root", self.root / "absent", "--json")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(json.loads(result.output)["status"], "error")

    def test_copied_folder_can_be_checked(self):
        (self.root / "a").write_text("original")
        self.create_baseline()
        copied = Path(self.temp.name) / "copy"
        copied.mkdir()
        (copied / "a").write_text("original")
        self.assertEqual(self.invoke("check", self.baseline, "--root", copied).exit_code, 0)

    def test_inspect_shows_scope(self):
        self.create_baseline()
        result = self.invoke("inspect", self.baseline)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("sha256", result.output)

    def test_path_traversal_record_is_rejected(self):
        (self.root / "a").write_text("original")
        self.create_baseline()
        data = load_manifest(self.baseline)
        data["files"]["../outside"] = data["files"].pop("a")
        self.baseline.write_text(json.dumps(data))
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 2)

    def test_version_and_help(self):
        from iledger import __version__

        result = self.invoke("--version")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.strip(), f"iledger {__version__}")
        self.assertEqual(self.invoke("--help").exit_code, 0)

    def test_file_as_scan_root_is_rejected(self):
        path = self.root / "file"
        path.write_text("not a directory")
        result = self.invoke("baseline", path)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("directory", result.output)

    def test_symlink_baseline_output_is_not_followed(self):
        target = self.root / "keep"
        target.write_text("do not replace")
        output = self.root / "alias"
        output.symlink_to(target)
        result = self.invoke("baseline", self.root, "-o", output, "--force")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(target.read_text(), "do not replace")

    def test_empty_exclude_pattern_is_rejected(self):
        self.assertEqual(self.invoke("baseline", self.root, "-x", "").exit_code, 2)

    def test_human_readable_scan_error_and_invalid_inspect(self):
        self.create_baseline()
        (self.root / "link").symlink_to("absent")
        result = self.invoke("check", self.baseline)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("incomplete", result.output.lower())
        self.assertEqual(self.invoke("inspect", self.root / "absent").exit_code, 2)

    def test_external_baseline_and_check_does_not_modify_it(self):
        self.baseline = self.root.parent / "outside.json"
        (self.root / "sample").write_text("original")
        self.create_baseline("-o", self.baseline)
        original = self.baseline.read_bytes()
        (self.root / "sample").write_text("changed")
        self.assertEqual(self.invoke("check", self.baseline).exit_code, 1)
        self.assertEqual(self.baseline.read_bytes(), original)
