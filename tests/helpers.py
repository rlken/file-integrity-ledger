import os
import unittest


class FilesystemTestCase(unittest.TestCase):
    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            if os.name == "nt" and error.winerror == 1314:
                self.skipTest("Creating symlinks requires Windows Developer Mode or elevation")
            raise
