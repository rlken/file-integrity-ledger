"""Hash regular files without loading their entire contents into memory."""

import fnmatch
import hashlib
import os
import stat
from pathlib import Path

DEFAULT_EXCLUDES = (".git", ".venv", "__pycache__", ".iledger")


def is_link_or_reparse(info) -> bool:
    """Include Windows junctions and other reparse points, not just symlinks."""
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def fingerprint(path: Path) -> dict:
    """Reject links/special files and detect common changes during a read."""
    initial = path.lstat()
    if is_link_or_reparse(initial) or not stat.S_ISREG(initial.st_mode):
        raise OSError(
            "not a regular file (links, reparse points, and special files are not followed)"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        if is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise OSError("file type changed before reading")
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = path.lstat()

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    if not all(identity(info) == identity(initial) for info in (before, after, current)):
        raise OSError("file changed during hashing; retry with a stable copy")
    return {"sha256": digest.hexdigest(), "size": after.st_size, "mtime_ns": after.st_mtime_ns}


def sha256_file(path: Path) -> str:
    return fingerprint(Path(path))["sha256"]


def is_excluded(relative: str, patterns) -> bool:
    # A bare pattern matches any path component; a pattern with / matches
    # the whole root-relative POSIX path. Matching is case-sensitive.
    return any(
        fnmatch.fnmatchcase(relative, pattern.lstrip("/"))
        if "/" in pattern
        else any(fnmatch.fnmatchcase(part, pattern) for part in relative.split("/"))
        for pattern in patterns
    )


def scan_directory(root: Path, excludes=DEFAULT_EXCLUDES):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("scan target must be a directory")
    files, errors = {}, {}

    def walk_error(error):
        try:
            relative = Path(error.filename or root).relative_to(root).as_posix()
        except ValueError:
            relative = "."
        errors[relative] = str(error)

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        for name in sorted(dirs[:]):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if is_excluded(relative, excludes):
                dirs.remove(name)
                continue
            try:
                if is_link_or_reparse(path.lstat()):
                    raise OSError(
                        "link or reparse point directory; exclude it explicitly to skip it"
                    )
            except OSError as error:
                dirs.remove(name)
                errors[relative] = str(error)
        dirs.sort()
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if is_excluded(relative, excludes):
                continue
            try:
                files[relative] = fingerprint(path)
            except OSError as error:
                errors[relative] = str(error)
    return files, errors
