import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iledger.hashing import fingerprint, scan_directory, sha256_file


class HashingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_known_digest_and_empty_file(self):
        file = self.root / "sample"
        file.write_bytes(b"abc")
        self.assertEqual(
            sha256_file(file), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
        file.write_bytes(b"")
        self.assertEqual(sha256_file(file), hashlib.sha256(b"").hexdigest())

    def test_large_binary_file(self):
        data = bytes(range(256)) * 10000
        file = self.root / "binary"
        file.write_bytes(data)
        self.assertEqual(fingerprint(file)["sha256"], hashlib.sha256(data).hexdigest())

    def test_recursive_hidden_unicode_files_and_exclusions(self):
        (self.root / "nested").mkdir()
        (self.root / "nested/café.txt").write_text("hello")
        (self.root / ".hidden").write_text("included")
        (self.root / ".venv").mkdir()
        (self.root / ".venv/skip").write_text("ignored")
        (self.root / "nested/cache.tmp").write_text("ignored")
        from iledger.hashing import DEFAULT_EXCLUDES

        files, errors = scan_directory(self.root, (*DEFAULT_EXCLUDES, "*.tmp"))
        self.assertEqual(set(files), {"nested/café.txt", ".hidden"})
        self.assertFalse(errors)

    def test_links_and_special_files_are_errors(self):
        (self.root / "link").symlink_to("absent")
        (self.root / "dir").mkdir()
        (self.root / "dir-link").symlink_to(self.root / "dir", target_is_directory=True)
        os.mkfifo(self.root / "pipe")
        files, errors = scan_directory(self.root)
        self.assertFalse(files)
        self.assertEqual(set(errors), {"link", "dir-link", "pipe"})

    def test_file_changed_during_hash_is_rejected(self):
        file = self.root / "changing"
        file.write_bytes(b"before")
        real_sha256 = hashlib.sha256

        def mutate_then_hash():
            file.write_bytes(b"after, changed length")
            return real_sha256()

        with patch("iledger.hashing.hashlib.sha256", side_effect=mutate_then_hash):
            with self.assertRaisesRegex(OSError, "changed during hashing"):
                fingerprint(file)

    def test_unreadable_subtree_is_reported(self):
        def failed_walk(root, **kwargs):
            kwargs["onerror"](PermissionError(13, "denied", str(root / "locked")))
            return iter([])

        with patch("iledger.hashing.os.walk", side_effect=failed_walk):
            _, errors = scan_directory(self.root)
        self.assertIn("locked", errors)
