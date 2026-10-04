"""The golden set on disk: recorded inputs, hand-written expectations, recorded model output.

    evals/golden/manifest.json               version + the list of cases
    evals/golden/<slug>/input.json           CollectedRange, collected once from GitHub
    evals/golden/<slug>/expected.json        Expected, written by a human reading input.json
    evals/golden/<slug>/cassette.json        model responses from the last `--live --record`

Inputs are snapshots so evals are deterministic and free of GitHub rate limits; the
cassette makes the *model* side deterministic too, so CI can run every scorer with no
network and no keys. The live suite (`uv run evals --live`) is how prompt or model changes
get measured; re-record the cassette when you accept the new numbers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from ..models import CollectedRange


class Expected(BaseModel):
    """What a correct set of notes must (and must not) contain. Refs are "#123" or SHAs."""

    repo: str
    base: str
    head: str
    must_mention: list[str] = Field(default_factory=list)
    must_flag_breaking: list[str] = Field(default_factory=list)
    # Changes a reasonable reviewer might call breaking either way: flagging them is not a
    # false positive, missing them is not a miss.
    may_flag_breaking: list[str] = Field(default_factory=list)
    # Regexes (case-insensitive) that must not match either document.
    forbidden_claims: list[str] = Field(default_factory=list)
    # Expected category per ref, from labels / conventional types / reading the PR.
    categories: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class Case(BaseModel):
    slug: str
    repo: str
    base: str
    head: str
    status: str = "recorded"  # or "todo" when the input could not be collected
    todo: str = ""


class Manifest(BaseModel):
    version: str
    cases: list[Case]


def golden_dir() -> Path:
    override = os.environ.get("GOLDEN_DIR")
    if override:
        return Path(override)
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        candidate = folder / "evals" / "golden"
        if candidate.is_dir():
            return candidate
    # Installed package next to a checkout (Docker copies evals/ to /app/evals).
    return Path(__file__).resolve().parents[3] / "evals" / "golden"


def load_manifest(root: Path | None = None) -> Manifest:
    root = root or golden_dir()
    return Manifest.model_validate_json((root / "manifest.json").read_text(encoding="utf-8"))


def slug_for(repo: str) -> str:
    return repo.replace("/", "__")


def load_input(slug: str, root: Path | None = None) -> CollectedRange:
    path = (root or golden_dir()) / slug / "input.json"
    return CollectedRange.model_validate_json(path.read_text(encoding="utf-8"))


def load_expected(slug: str, root: Path | None = None) -> Expected:
    path = (root or golden_dir()) / slug / "expected.json"
    return Expected.model_validate_json(path.read_text(encoding="utf-8"))


def cassette_path(slug: str, root: Path | None = None) -> Path:
    return (root or golden_dir()) / slug / "cassette.json"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
