"""Parsing what a user types into a repository and a range.

Accepted forms (CLI, API and the web form all go through `resolve_target`):

    owner/name + "v1.2.0..v1.3.0"            two-dot range
    owner/name + "v1.2.0...v1.3.0"           three-dot range (GitHub's compare syntax)
    owner/name + base="v1.2.0", head="v1.3.0"
    https://github.com/owner/name/compare/v1.2.0...v1.3.0   a compare URL

`git log a..b` and GitHub's `compare/a...b` mean the same thing for release notes: the
commits reachable from `b` and not from `a`. Both spellings are accepted because people
paste both.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from pydantic import BaseModel

# GitHub's own rules: owner up to 39 chars of [A-Za-z0-9-]; repo names allow . _ - too.
_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_NAME = r"[A-Za-z0-9._-]{1,100}"
REPO_RE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<name>{_NAME})$")
# Git ref names: conservative allow-list (no spaces, no "..", no control chars).
REF_RE = re.compile(r"^[A-Za-z0-9._/@^~+-]{1,200}$")


class TargetError(ValueError):
    """The repository or range could not be parsed. The message is user-facing."""


class RangeSpec(BaseModel):
    owner: str
    name: str
    base: str
    head: str

    @property
    def repo(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def compare_url(self) -> str:
        return f"https://github.com/{self.repo}/compare/{self.base}...{self.head}"


def parse_repo(value: str) -> tuple[str, str]:
    cleaned = value.strip().removesuffix(".git").strip("/")
    if cleaned.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise TargetError(f"only github.com repositories are supported, got {parsed.netloc}")
        cleaned = "/".join(parsed.path.strip("/").split("/")[:2])
    match = REPO_RE.match(cleaned)
    if not match or match.group("name") in {".", ".."}:
        raise TargetError(f"expected a repository like 'owner/name', got {value!r}")
    return match.group("owner"), match.group("name")


def _check_ref(ref: str, which: str) -> str:
    ref = ref.strip()
    if not ref or not REF_RE.match(ref) or ".." in ref:
        raise TargetError(f"invalid {which} ref {ref!r}")
    return ref


def parse_range(value: str) -> tuple[str, str]:
    """`base..head` or `base...head` -> (base, head)."""
    value = value.strip()
    separator = "..." if "..." in value else ".."
    if separator not in value:
        raise TargetError(f"expected a range like 'v1.2.0..v1.3.0', got {value!r}")
    base, head = value.split(separator, 1)
    return _check_ref(base, "base"), _check_ref(head, "head")


def parse_compare_url(url: str) -> RangeSpec:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        raise TargetError("expected a https://github.com/<owner>/<repo>/compare/<a>...<b> URL")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 4 or parts[2] != "compare":
        raise TargetError("expected a https://github.com/<owner>/<repo>/compare/<a>...<b> URL")
    owner, name = parse_repo(f"{parts[0]}/{parts[1]}")
    range_text = unquote("/".join(parts[3:]))
    for suffix in (".diff", ".patch"):
        range_text = range_text.removesuffix(suffix)
    base, head = parse_range(range_text)
    return RangeSpec(owner=owner, name=name, base=base, head=head)


def resolve_target(repo_or_url: str, base: str | None = None, head: str | None = None) -> RangeSpec:
    """One entry point for every interface. Explicit base/head win over a URL's range."""
    text = repo_or_url.strip()
    if "/compare/" in text:
        spec = parse_compare_url(text)
        if base or head:
            spec = spec.model_copy(
                update={
                    "base": _check_ref(base, "base") if base else spec.base,
                    "head": _check_ref(head, "head") if head else spec.head,
                }
            )
        return spec
    owner, name = parse_repo(text)
    if base and head:
        return RangeSpec(
            owner=owner, name=name, base=_check_ref(base, "base"), head=_check_ref(head, "head")
        )
    if base and (".." in base):
        parsed_base, parsed_head = parse_range(base)
        return RangeSpec(owner=owner, name=name, base=parsed_base, head=parsed_head)
    raise TargetError("a range is required: pass base and head, 'base..head', or a compare URL")
