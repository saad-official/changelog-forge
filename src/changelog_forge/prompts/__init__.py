"""Versioned prompt files and the loader that records which version a run used.

Prompts are files, not string literals, for the same reason migrations are: a change to
one is a reviewable diff with a version bump, and every run stores the exact version
string it used (`runs.prompt_versions`). When a golden-set score moves, the first question
is "which prompt version produced this?", and the answer has to be in the data.

A version id looks like `map.v1@3f2a9c1b`: the file's declared version plus the first 8 hex
chars of its SHA-256, so an edit that forgot to bump `v1` still shows up as a new id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:8]

    @property
    def id(self) -> str:
        return f"{self.name}.{self.version}@{self.digest}"


@lru_cache
def load_prompt(name: str, version: str = "v1") -> Prompt:
    path = resources.files("changelog_forge.prompts") / f"{name}.{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt {name}.{version}.md not found in changelog_forge/prompts")
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8").strip())


def wrap_untrusted(tag: str, content: str) -> str:
    """Delimit third-party text so the system prompt can refer to it as data."""
    safe = content.replace(f"</{tag}", f"&lt;/{tag}")
    return f"<{tag}>\n{safe}\n</{tag}>"
