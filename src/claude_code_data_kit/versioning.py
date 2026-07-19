from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Optional, Tuple
from .records import VersionBoundary
_VERSION_RE = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

@dataclass(frozen=True, order=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = _VERSION_RE.match(value.strip())
        if not match:
            raise ValueError(f"unsupported semantic version: {value!r}")
        return cls(*(int(group) for group in match.groups()))

def maybe_parse(value: Optional[str]) -> Optional[SemVer]:
    if not value:
        return None
    try:
        return SemVer.parse(value)
    except ValueError:
        return None

def version_allows(version: Optional[str], boundary: VersionBoundary) -> bool:
    parsed = maybe_parse(version)
    if parsed is None:
        return False
    if boundary.min_inclusive and parsed < SemVer.parse(boundary.min_inclusive):
        return False
    if boundary.max_exclusive and parsed >= SemVer.parse(boundary.max_exclusive):
        return False
    return True

def version_key(value: Optional[str]) -> Tuple[int, int, int]:
    parsed = maybe_parse(value)
    return (-1, -1, -1) if parsed is None else (parsed.major, parsed.minor, parsed.patch)

__all__ = ["SemVer", "maybe_parse", "version_allows", "version_key"]
