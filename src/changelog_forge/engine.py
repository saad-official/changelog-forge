"""Wiring: settings + routing -> the objects a run needs. Shared by the API, CLI and evals.

`Engine` holds the long-lived, swappable collaborators (store, how to build a GitHub
client, how to build the two tiers). Tests construct it with fakes; production uses
`Engine.from_settings`. Nothing in the pipeline imports settings directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_kit import Ledger

from .chunk import TokenCounter
from .collect.github import GitHubClient
from .config import AppSettings
from .db import Store, make_store
from .llm import RoutedLLM, TokenPacer
from .routing import Routing, load_routing

LLMBuilder = Callable[[Ledger], tuple[Any, Any]]
GitHubBuilder = Callable[[str | None], GitHubClient]


@dataclass
class Engine:
    settings: AppSettings
    store: Store
    routing: Routing
    llm_builder: LLMBuilder
    github_builder: GitHubBuilder
    counter: TokenCounter | None = None
    pacer: TokenPacer = field(default_factory=TokenPacer)

    @property
    def budget_usd(self) -> float:
        return self.settings.max_usd_per_run or self.routing.budget.max_usd_per_run

    @classmethod
    def from_settings(
        cls, settings: AppSettings, store: Store | None = None, routing: Routing | None = None
    ) -> Engine:
        routing = routing or load_routing()
        store = store if store is not None else make_store(settings)
        # One pacer per process: Groq's tokens-per-minute limit is per account and model,
        # so concurrent runs in one process must share the window.
        pacer = TokenPacer()
        llm_settings = settings.llm_settings()
        retry = routing.retry.policy()

        def build_llms(ledger: Ledger) -> tuple[RoutedLLM, RoutedLLM]:
            common = {"ledger": ledger, "retry": retry, "settings": llm_settings, "pacer": pacer}
            return (
                RoutedLLM("map", routing.tier("map"), **common),
                RoutedLLM("reduce", routing.tier("reduce"), **common),
            )

        def build_github(token: str | None) -> GitHubClient:
            server = settings.github_token.get_secret_value() if settings.github_token else None
            return GitHubClient(store, token or server, max_commits=settings.max_commits)

        return cls(
            settings=settings,
            store=store,
            routing=routing,
            llm_builder=build_llms,
            github_builder=build_github,
            pacer=pacer,
        )
