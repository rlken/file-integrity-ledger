"""Versioned, validated JSON manifests and atomic writes."""

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import __version__
from .hashing import is_excluded


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_manifest(root: Path, files: dict, excludes: list) -> dict:
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "algorithm": "sha256",
        "created_at": utc_now(),
        "root": str(root),
        "excludes": excludes,
        "files": files,
    }


def validate_manifest(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("baseline must be a JSON object")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported baseline schema (expected version 1)")
    if data.get("algorithm") != "sha256":
        raise ValueError("baseline must use sha256")
    if (
        not isinstance(data.get("root"), str)
        or "\x00" in data["root"]
        or not (
            PurePosixPath(data["root"]).is_absolute() or PureWindowsPath(data["root"]).is_absolute()
        )
    ):
        raise ValueError("baseline root must be an absolute path")
    if not isinstance(data.get("created_at"), str):
        raise ValueError("baseline timestamp is missing")
    try:
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise ValueError("baseline timestamp must include a timezone") from None
    excludes = data.get("excludes")
    if not isinstance(excludes, list) or not all(isinstance(p, str) and p for p in excludes):
        raise ValueError("baseline exclusions must be nonempty strings")
    if not isinstance(data.get("files"), dict):
        raise ValueError("baseline files must be an object")
    for name, entry in data["files"].items():
        if not isinstance(name, str) or "\x00" in name:
            raise ValueError("baseline contains an invalid relative path")
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or name == "."
        ):
            raise ValueError("baseline contains an invalid relative path")
        if is_excluded(name, excludes):
            raise ValueError("baseline contains a file outside its declared scan scope")
        if any(str(parent) in data["files"] for parent in path.parents if str(parent) != "."):
            raise ValueError("baseline contains conflicting file and directory paths")
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise ValueError("baseline contains an invalid file record")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ValueError("baseline contains an invalid SHA-256 digest")
        if type(entry.get("size")) is not int or entry["size"] < 0:
            raise ValueError("baseline contains an invalid file size")
        if type(entry.get("mtime_ns")) is not int:
            raise ValueError("baseline contains an invalid modification time")
    return data


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("baseline contains duplicate JSON keys")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return validate_manifest(json.load(stream, object_pairs_hook=_unique_keys))


def save_manifest(path: Path, data: dict, overwrite: bool = False):
    validate_manifest(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".iledger-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif sys.platform == "win32":
            # Windows rename fails if the destination exists, including on
            # filesystems without hard links. POSIX rename would overwrite it.
            os.rename(temporary, path)
        else:
            # Atomic create-if-absent: never silently replace an existing baseline.
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compare_files(expected: dict, actual: dict, errors: dict) -> dict:
    old, new = set(expected), set(actual)
    shared = old & new
    modified = sorted(name for name in shared if expected[name]["sha256"] != actual[name]["sha256"])
    return {
        "added": sorted(new - old),
        "modified": modified,
        "missing": sorted(
            name
            for name in old - new
            if not any(
                error == "." or name == error or name.startswith(error + "/") for error in errors
            )
        ),
        "unchanged": len(shared) - len(modified),
    }
