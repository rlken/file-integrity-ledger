import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iledger.hashing import fingerprint
from iledger.storage import load_manifest, make_manifest, save_manifest, validate_manifest


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        sample = self.root / "sample.txt"
        sample.write_bytes(b"sample")
        self.record = fingerprint(sample)
        self.manifest = make_manifest(self.root, {"sample.txt": self.record}, [])
        self.destination = self.root / "records/baseline.json"

    def test_round_trip_preserves_all_records(self):
        save_manifest(self.destination, self.manifest)
        self.assertEqual(load_manifest(self.destination), self.manifest)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_create_never_clobbers_existing_file(self):
        save_manifest(self.destination, self.manifest)
        original = self.destination.read_bytes()
        changed = copy.deepcopy(self.manifest)
        changed["files"] = {}
        with self.assertRaises(FileExistsError):
            save_manifest(self.destination, changed)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_failed_replace_preserves_existing_baseline_and_cleans_temp_file(self):
        save_manifest(self.destination, self.manifest)
        original = self.destination.read_bytes()
        with patch("iledger.storage.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                save_manifest(self.destination, self.manifest, overwrite=True)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_failed_write_leaves_no_partial_baseline(self):
        with patch("iledger.storage.json.dump", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                save_manifest(self.destination, self.manifest)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_duplicate_keys_are_rejected(self):
        path = self.root / "duplicate.json"
        for content in (
            '{"schema_version": 1, "schema_version": 2}',
            '{"files": {"sample.txt": {}, "sample.txt": {}}}',
        ):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
                    load_manifest(path)

    def test_invalid_manifest_fields_are_rejected(self):
        for key, value in (
            ("schema_version", True),
            ("schema_version", 2),
            ("algorithm", "md5"),
            ("root", "relative"),
            ("root", "/bad\x00path"),
            ("created_at", None),
            ("created_at", "yesterday"),
            ("created_at", "2026-01-01T00:00:00"),
            ("excludes", "*.tmp"),
            ("excludes", [""]),
            ("files", []),
        ):
            with self.subTest(key=key, value=value):
                invalid = copy.deepcopy(self.manifest)
                invalid[key] = value
                with self.assertRaises(ValueError):
                    validate_manifest(invalid)

    def test_invalid_file_records_are_rejected(self):
        for key, value in (
            ("sha256", "bad"),
            ("sha256", 123),
            ("size", -1),
            ("size", True),
            ("mtime_ns", "yesterday"),
        ):
            with self.subTest(key=key, value=value):
                invalid = copy.deepcopy(self.manifest)
                invalid["files"]["sample.txt"][key] = value
                with self.assertRaises(ValueError):
                    validate_manifest(invalid)

    def test_invalid_paths_are_rejected(self):
        for name in ("../outside", "/absolute", "./sample", "a//b", ".", "", "a\x00b", 1):
            with self.subTest(name=name):
                invalid = copy.deepcopy(self.manifest)
                invalid["files"] = {name: self.record}
                with self.assertRaises(ValueError):
                    validate_manifest(invalid)

    def test_file_cannot_also_be_a_directory(self):
        self.manifest["files"]["sample.txt/child"] = self.record
        with self.assertRaisesRegex(ValueError, "conflicting"):
            validate_manifest(self.manifest)

    def test_excluded_records_are_rejected(self):
        self.manifest["excludes"] = ["*.txt"]
        with self.assertRaisesRegex(ValueError, "scan scope"):
            validate_manifest(self.manifest)

    def test_non_utf8_baseline_is_rejected(self):
        path = self.root / "invalid.json"
        path.write_bytes(b"\xff\xfe")
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_json_serialization_escapes_unusual_filenames(self):
        self.manifest["files"] = {"line\nbreak.txt": self.record}
        save_manifest(self.destination, self.manifest)
        self.assertEqual(json.loads(self.destination.read_text()), self.manifest)
