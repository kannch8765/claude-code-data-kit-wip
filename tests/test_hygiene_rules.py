from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Iterable


@dataclass(frozen=True)
class HygieneViolation:
    rule: str
    excerpt: str


# These are deliberately fictional public sentinels. Real account/repository
# denylists belong only in private release tooling.
FICTIONAL_SENTINELS = (
    "fictional-" "private-owner",
    "fictional-" "private-repository",
    "fictional-" "internal-project",
)

_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    + "@"
    + r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    + r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    + r"\.[A-Za-z]{2,63}"
)
_PRIVATE_KEY = re.compile(
    "-" * 5 + r"BEGIN [A-Z0-9 ]+ PRIVATE KEY" + "-" * 5
)
_TOKEN_PREFIX = re.compile(
    r"(?i)(?:sk|ghp|github_pat|glpat|xox[baprs]|ya29)[_-][A-Za-z0-9_-]{16,}"
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|oauth[_-]?token|access[_-]?token|authorization|password)"
    r"\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{20,}"
)
_UNIX_PERSONAL_PATH = re.compile(
    r"(?<![A-Za-z0-9])"
    + "/"
    + r"(?:home|Users|root|mnt|opt|var)/(?!synthetic(?:/|\b))[A-Za-z0-9._-]+(?:/[^\s\"']*)?"
)
_WINDOWS_PERSONAL_PATH = re.compile(
    r"(?i)[A-Z]:\\(?:Users|Documents and Settings)\\[A-Za-z0-9._-]+"
)
_HOSTED_REPOSITORY_URL = re.compile(
    r"(?i)https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org)/"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
)

_GENERIC_RULES = (
    ("email-address", _EMAIL),
    ("private-key", _PRIVATE_KEY),
    ("token-prefix", _TOKEN_PREFIX),
    ("credential-assignment", _CREDENTIAL_ASSIGNMENT),
    ("unix-personal-absolute-path", _UNIX_PERSONAL_PATH),
    ("windows-personal-absolute-path", _WINDOWS_PERSONAL_PATH),
    ("hosted-repository-url", _HOSTED_REPOSITORY_URL),
)

_TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_TEXT_BASENAMES = {
    ".gitignore",
    "METADATA",
    "PKG-INFO",
    "RECORD",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
}


def is_public_text_path(path: str) -> bool:
    normalized = PurePosixPath(path)
    return normalized.suffix.lower() in _TEXT_SUFFIXES or normalized.name in _TEXT_BASENAMES


def find_violations(text: str) -> tuple[HygieneViolation, ...]:
    violations: list[HygieneViolation] = []
    lowered = text.lower()
    for sentinel in FICTIONAL_SENTINELS:
        if sentinel.lower() in lowered:
            violations.append(HygieneViolation("fictional-public-sentinel", sentinel))
    for name, pattern in _GENERIC_RULES:
        match = pattern.search(text)
        if match:
            violations.append(HygieneViolation(name, match.group(0)[:120]))
    return tuple(violations)


def scan_named_texts(items: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    findings: list[str] = []
    for name, text in items:
        for violation in find_violations(text):
            findings.append(f"{name}: {violation.rule}: {violation.excerpt}")
    return tuple(findings)
