import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from helpers import FilesystemTestCase

from iledger.hashing import fingerprint, is_link_or_reparse, scan_directory, sha256_file


class HashingTests(FilesystemTestCase):
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

    def test_links_are_errors(self):
        self.symlink(self.root / "link", "absent")
        (self.root / "dir").mkdir()
        self.symlink(self.root / "dir-link", self.root / "dir", directory=True)
        files, errors = scan_directory(self.root)
        self.assertFalse(files)
        self.assertEqual(set(errors), {"link", "dir-link"})

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX named pipes are not available on Windows")
    def test_named_pipe_is_an_error(self):
        os.mkfifo(self.root / "pipe")
        files, errors = scan_directory(self.root)
        self.assertFalse(files)
        self.assertEqual(set(errors), {"pipe"})

    def test_binary_control_bytes_are_preserved(self):
        data = b"line one\r\nline two\x1aafter control-z\x00\xff"
        file = self.root / "raw bytes.bin"
        file.write_bytes(data)
        record = fingerprint(file)
        self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(record["size"], len(data))

    def test_reparse_attribute_is_recognized(self):
        info = SimpleNamespace(
            st_mode=stat.S_IFREG, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        self.assertTrue(is_link_or_reparse(info))

    def test_path_and_descriptor_ctime_can_have_different_meanings(self):
        file = self.root / "ctime.txt"
        file.write_bytes(b"stable")
        info = file.lstat()
        descriptor_info = SimpleNamespace(
            **{
                name: getattr(info, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            },
            st_ctime_ns=info.st_ctime_ns + 1000,
        )
        with patch("iledger.hashing.os.fstat", return_value=descriptor_info):
            self.assertEqual(sha256_file(file), hashlib.sha256(b"stable").hexdigest())

    def test_descriptor_ctime_change_still_rejects_the_read(self):
        file = self.root / "ctime.txt"
        file.write_bytes(b"stable")
        info = file.lstat()
        changed_info = SimpleNamespace(
            **{
                name: getattr(info, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            },
            st_ctime_ns=info.st_ctime_ns + 1000,
        )
        with patch("iledger.hashing.os.fstat", side_effect=[info, changed_info]):
            with self.assertRaisesRegex(OSError, "changed during hashing"):
                fingerprint(file)

    def test_path_ctime_change_still_rejects_the_read(self):
        file = self.root / "ctime.txt"
        file.write_bytes(b"stable")
        info = file.lstat()
        changed_info = SimpleNamespace(
            **{
                name: getattr(info, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            },
            st_ctime_ns=info.st_ctime_ns + 1000,
        )
        with patch.object(Path, "lstat", side_effect=[info, changed_info]):
            with self.assertRaisesRegex(OSError, "changed during hashing"):
                fingerprint(file)

    @unittest.skipUnless(os.name == "nt", "Windows junction integration test")
    def test_junction_is_rejected_without_traversing_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside scan scope")
        evidence = self.root / "evidence"
        evidence.mkdir()
        junction = evidence / "junction"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            check=True,
            capture_output=True,
        )
        # Remove only the junction, never the target directory.
        self.addCleanup(os.rmdir, junction)
        files, errors = scan_directory(evidence)
        self.assertFalse(files)
        self.assertEqual(set(errors), {"junction"})
        self.assertEqual(scan_directory(evidence, ["junction"]), ({}, {}))

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
