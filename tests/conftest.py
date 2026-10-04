"""Shared fixtures: commit builders, a fake model, an in-memory engine.

No test touches the network: GitHub is mocked with respx, models with FakeLLM, Postgres
with MemoryStore, tiktoken with ApproxCounter.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

import pytest
from llm_kit import CallRecord, Ledger, LLMOutputError
from llm_kit import Usage as LLMUsage
from pydantic import BaseModel

from changelog_forge.chunk import ApproxCounter
from changelog_forge.config import AppSettings
from changelog_forge.db import MemoryStore
from changelog_forge.engine import Engine
from changelog_forge.llm import TokenPacer
from changelog_forge.models import (
    Change,
    CollectedRange,
    CommitRecord,
    DevDraft,
    GroupAnalysis,
    SectionDraft,
    UserDraft,
)
from changelog_forge.routing import load_routing

REPO = "acme/widgets"


def sha(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()


def commit(
    seed: str,
    message: str,
    *,
    pr: int | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    labels: list[str] | None = None,
    parents: int = 1,
    files: list[str] | None = None,
) -> CommitRecord:
    full = sha(seed)
    return CommitRecord(
        sha=full,
        message=message,
        author="dev",
        parents=parents,
        html_url=f"https://github.com/{REPO}/commit/{full}",
        pr_number=pr,
        pr_title=pr_title,
        pr_body=pr_body,
        pr_url=f"https://github.com/{REPO}/pull/{pr}" if pr else None,
        labels=labels or [],
        files=files,
    )


def collected(commits: list[CommitRecord], base: str = "v1.0.0", head: str = "v1.1.0"):
    return CollectedRange(
        repo=REPO,
        base=base,
        head=head,
        compare_url=f"https://github.com/{REPO}/compare/{base}...{head}",
        total_commits=len(commits),
        commits=commits,
    )


@pytest.fixture
def sample_range() -> CollectedRange:
    """Five changes: a feature PR (2 commits), a breaking PR, a fix, a docs commit, a chore."""
    return collected(
        [
            commit(
                "a1",
                "Add export button",
                pr=10,
                pr_title="feat: add CSV export",
                pr_body="Adds an export button.",
                labels=["enhancement"],
            ),
            commit(
                "a2",
                "Polish export",
                pr=10,
                pr_title="feat: add CSV export",
                labels=["enhancement"],
            ),
            commit(
                "b1",
                "feat!: drop Node 18 (#11)",
                pr=11,
                pr_title="feat!: drop Node 18",
                pr_body="BREAKING CHANGE: Node 20 is now required.",
            ),
            commit(
                "c1",
                "fix: crash on empty file (#12)",
                pr=12,
                pr_title="fix: crash on empty file",
                labels=["bug"],
            ),
            commit("d1", "docs: fix typo in README"),
            commit("e1", "chore(deps): bump lodash"),
        ]
    )


ITEM_RE = re.compile(r'<item id="(?P<id>[^"]+)" refs="(?P<refs>[^"]*)">\ntitle: (?P<title>[^\n]*)')


def echo_map(message: str) -> GroupAnalysis:
    """A plausible map model: one change per item, citing the item's first ref."""
    changes = []
    for match in ITEM_RE.finditer(message):
        title = match.group("title")
        breaking = "!" in title.split(":")[0] if ":" in title else False
        category = "feature" if title.startswith("feat") else "fix"
        if title.startswith("docs"):
            category = "docs"
        if title.startswith("chore"):
            category = "internal"
        changes.append(
            Change(
                category=category,
                user_summary=f"User: {title}",
                dev_summary=f"Dev: {title}",
                breaking=breaking,
                breaking_confidence=0.95 if breaking else 0.0,
                migration_note="Upgrade to Node 20." if breaking else None,
                refs=[match.group("refs").split(", ")[0]],
            )
        )
    return GroupAnalysis(changes=changes)


ID_RE = re.compile(r'"id": ?"(i\d+)"')


def echo_reduce(message: str, schema: type[BaseModel]) -> BaseModel:
    ids = ID_RE.findall(message)
    sections = [SectionDraft(section="feature", prose="New things.", item_ids=list(reversed(ids)))]
    if schema is DevDraft:
        return DevDraft(intro="Developer intro.", sections=sections, duplicates=[])
    return UserDraft(intro="User intro.", sections=sections)


Handler = Callable[[str, type[BaseModel], str], Any]


class FakeLLM:
    """Implements StructuredLLM. Each call is recorded in the shared Ledger like a real one.

    `script` maps a label prefix ("map", "map:2", "reduce:dev") to a response, an exception
    to raise, or a callable(message, schema, label).
    """

    def __init__(
        self,
        ledger: Ledger,
        model: str = "openai/gpt-oss-20b",
        script: dict[str, Any] | None = None,
    ):
        self.ledger = ledger
        self.model = model
        self.script = script or {}
        self.calls: list[tuple[str, str]] = []
        self.served_by: list[str] = []

    def _lookup(self, label: str) -> Any:
        if label in self.script:
            return self.script[label]
        prefix = label.split(":")[0]
        return self.script.get(prefix)

    def complete_structured(self, messages, schema, *, system=None, label=None):
        label = label or ""
        self.calls.append((label, schema.__name__))
        self.ledger.add(
            CallRecord(
                provider="groq",
                model=self.model,
                label=label,
                usage=LLMUsage(1000, 200, 50),
                latency_s=0.1,
                finish_reason="stop",
            )
        )
        action = self._lookup(label)
        if isinstance(action, Exception):
            raise action
        if callable(action) and not isinstance(action, BaseModel):
            return action(messages, schema, label)
        if action is not None:
            return action
        self.served_by.append(self.model)
        if schema is GroupAnalysis:
            return echo_map(messages)
        if schema in (DevDraft, UserDraft):
            return echo_reduce(messages, schema)
        raise LLMOutputError(f"FakeLLM has no response for {schema.__name__}")


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings(
        _env_file=None,
        database_url=None,
        github_token=None,
        groq_api_key="test-groq",
        gemini_api_key=None,
        cron_secret="cron-test",
        web_origin="http://localhost:3000",
    )


def make_engine(
    settings: AppSettings,
    store: MemoryStore | None = None,
    *,
    map_script: dict[str, Any] | None = None,
    reduce_script: dict[str, Any] | None = None,
    collected_range: CollectedRange | None = None,
    github_error: Exception | None = None,
) -> Engine:
    store = store or MemoryStore()

    def build_llms(ledger: Ledger):
        return (
            FakeLLM(ledger, "openai/gpt-oss-20b", map_script),
            FakeLLM(ledger, "openai/gpt-oss-120b", reduce_script),
        )

    class FakeGitHub:
        def __init__(self, token):
            self.token = token

        def collect(self, spec, on_progress=None):
            if github_error is not None:
                raise github_error
            if on_progress:
                on_progress("collecting", 1, 1)
            data = collected_range or collected([commit("x1", "fix: thing (#1)", pr=1)])
            return data.model_copy(update={"repo": spec.repo, "base": spec.base, "head": spec.head})

        def close(self):
            pass

    return Engine(
        settings=settings,
        store=store,
        routing=load_routing(),
        llm_builder=build_llms,
        github_builder=FakeGitHub,
        counter=ApproxCounter(),
        pacer=TokenPacer(),
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
