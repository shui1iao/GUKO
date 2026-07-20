#!/usr/bin/env python3
"""Small release-version helpers used by GUKO's release tooling."""

from __future__ import annotations

import re
import sys

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def normalize_version(value: str) -> str:
    """Carry an overflowing patch/minor component once and reset it to zero."""
    match = VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("version must look like 0.2.0")
    major, minor, patch = (int(part) for part in match.groups())
    if patch >= 10:
        minor += 1
        patch = 0
    if minor >= 10:
        major += 1
        minor = 0
    return f"{major}.{minor}.{patch}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: versioning.py MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2
    try:
        print(normalize_version(args[0]))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
