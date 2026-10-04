"""The project's thin adapter over llm-kit: fallback routes and token-per-minute pacing.

llm-kit gives one `LLM` per (provider, model) with retries, a budget check and a ledger.
Two things this project needs are deliberately *not* in llm-kit ("llm-kit knows about
providers, projects know about problems"), so they live here:

  1. Fallback across providers. When Groq is rate-limited past the retry deadline, or a
     model id is withdrawn (a permanent 404), or the output will not validate even after
     the repair attempt, the same call is re-issued on the next route in `routing.toml`.
     A budget error is never a reason to fall back: it is our own ceiling doing its job.
  2. Token-per-minute pacing. llm-kit paces by requests per minute; Groq's free tier also
     caps tokens per minute (8,000), and one 6,000-token map group plus its output nearly
     fills a minute. The pacer keeps a sliding 60-second window of the tokens each model
     actually used (read off the shared Ledger's new records after every call) and sleeps
     before a call that would overflow it. Sleeping 20 s beats being rejected and backing
     off 20 s anyway, and it keeps 429s for the cases we could not predict.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from llm_kit import (
    LLM,
    Ledger,
    LLMBudgetError,
    LLMError,
    LLMOutputError,
    LLMPermanentError,
    LLMTransientError,
    RetryPolicy,
)
from llm_kit import Settings as LLMSettings
from pydantic import BaseModel

from .chunk import TokenCounter, default_counter
from .routing import Route, Tier

TModel = TypeVar("TModel", bound=BaseModel)

EXPECTED_OUTPUT_TOKENS = 1500
WINDOW_S = 60.0


def is_schema_rejection(exc: Exception) -> bool:
    """Groq enforces strict schemas server-side and answers a violating generation with a
    400 ("Generated JSON does not match the expected schema"). llm-kit rightly calls a 400
    permanent - but this one is a sampling failure, not a bad request: the same request
    usually succeeds on a second draw. Measured on the first live smoke run (gpt-oss-20b
    emitted a category outside the enum)."""
    text = str(exc)
    return isinstance(exc, LLMPermanentError) and (
        "does not match the expected schema" in text or "json_validate_failed" in text
    )


_DAILY = re.compile(r"per day \((?:TPD|RPD)\)", re.IGNORECASE)
_TRY_AGAIN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


def daily_quota_reset_s(exc: Exception) -> float | None:
    """Seconds until a *daily* quota resets, if `exc` is a daily-quota 429.

    Groq's free tier also caps tokens per day (200K for gpt-oss-20b). A TPD 429 says "try
    again in 18m11s"; llm-kit treats it like any 429 and retries for its full deadline,
    which can never succeed. Found in the second live eval run of the day. The router
    remembers the reset time and skips the route until then.
    """
    text = str(exc)
    if not isinstance(exc, LLMTransientError) or not _DAILY.search(text):
        return None
    match = _TRY_AGAIN.search(text)
    if not match or not any(match.groups()):
        return 3600.0
    hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


class LLMRouteError(LLMError):
    """Every route for a tier failed. Carries each route's reason, in order."""

    def __init__(self, tier: str, reasons: list[str]):
        super().__init__(f"all routes for tier {tier!r} failed: " + " | ".join(reasons))
        self.reasons = reasons


class StructuredLLM(Protocol):
    """What the pipeline needs from a model. RoutedLLM implements it; tests fake it."""

    def complete_structured(
        self,
        messages: str | list[dict[str, Any]],
        schema: type[TModel],
        *,
        system: str | None = None,
        label: str | None = None,
    ) -> TModel: ...


class TokenPacer:
    """Sliding-window tokens-per-minute guard, one window per model."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._clock = clock
        self._sleep = sleep
        self._windows: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._exhausted: dict[str, float] = {}
        self.slept_s = 0.0

    def _used(self, model: str, now: float) -> int:
        window = self._windows[model]
        while window and now - window[0][0] >= WINDOW_S:
            window.popleft()
        return sum(tokens for _, tokens in window)

    def wait(self, model: str, limit: int | None, estimate: int) -> float:
        """Sleep until `estimate` more tokens fit under `limit`. Returns seconds slept."""
        if not limit:
            return 0.0
        now = self._clock()
        used = self._used(model, now)
        if used + estimate <= limit:
            return 0.0
        # Wait for the oldest entries to age out until the call fits. A single call larger
        # than the limit can only be sent into an empty minute, so it waits for all of them.
        excess = used + estimate - limit
        freed, wait_until = 0, now
        for at, tokens in self._windows[model]:
            freed += tokens
            wait_until = at + WINDOW_S
            if freed >= excess:
                break
        waited = max(0.0, wait_until - now)
        if waited > 0:
            self._sleep(waited)
            self.slept_s += waited
        return waited

    def mark_exhausted(self, model: str, seconds: float) -> None:
        self._exhausted[model] = self._clock() + seconds

    def exhausted_for(self, model: str) -> float:
        """Seconds until `model`'s daily quota resets (0 when usable)."""
        return max(0.0, self._exhausted.get(model, 0.0) - self._clock())

    def record(self, model: str, tokens: int) -> None:
        if tokens > 0:
            self._windows[model].append((self._clock(), tokens))


LLMFactory = Callable[[Route, Ledger, RetryPolicy, LLMSettings | None], Any]


def default_factory(
    route: Route, ledger: Ledger, retry: RetryPolicy, settings: LLMSettings | None
) -> LLM:
    llm = LLM(
        provider=route.provider,
        model=route.model,
        settings=settings,
        ledger=ledger,
        retry_policy=retry,
        temperature=route.temperature,
        max_tokens=route.max_tokens,
        label=route.model,
    )
    # llm-kit builds `OpenAI(...)` with the SDK's default `max_retries=2`, so every 429 was
    # retried by the SDK *inside* each llm-kit attempt: two retry layers, the inner one
    # invisible to the ledger and to llm-kit's deadline (found in the first live eval: a
    # single "attempt" outlived the 45 s retry deadline). One layer, the one we can see.
    llm.client = llm.client.with_options(max_retries=0)
    return llm


class RoutedLLM:
    """A tier from routing.toml: the primary route, then each fallback, sharing one Ledger."""

    def __init__(
        self,
        name: str,
        tier: Tier,
        *,
        ledger: Ledger,
        retry: RetryPolicy | None = None,
        settings: LLMSettings | None = None,
        factory: LLMFactory = default_factory,
        pacer: TokenPacer | None = None,
        counter: TokenCounter | None = None,
    ):
        self.name = name
        self.tier = tier
        self.ledger = ledger
        self.retry = retry or RetryPolicy()
        self.settings = settings
        self.factory = factory
        self.pacer = pacer or TokenPacer()
        self.counter = counter
        self._clients: dict[str, Any] = {}
        self.served_by: list[str] = []
        self.fallback_reasons: list[str] = []

    def _client(self, route: Route) -> Any:
        if route.key not in self._clients:
            # Raises ValueError when the provider's key is missing: that route is simply
            # unavailable here, which is a reason to try the next one.
            self._clients[route.key] = self.factory(route, self.ledger, self.retry, self.settings)
        return self._clients[route.key]

    def _estimate(self, messages: Any, system: str | None) -> int:
        counter = self.counter or default_counter()
        text = (system or "") + (messages if isinstance(messages, str) else str(messages))
        return counter.count(text) + EXPECTED_OUTPUT_TOKENS

    def complete_structured(
        self,
        messages: str | list[dict[str, Any]],
        schema: type[TModel],
        *,
        system: str | None = None,
        label: str | None = None,
    ) -> TModel:
        reasons: list[str] = []
        estimate: int | None = None
        for route in self.tier.routes:
            try:
                client = self._client(route)
            except ValueError as exc:
                reasons.append(f"{route.key}: unavailable ({exc})")
                continue
            exhausted = self.pacer.exhausted_for(route.model)
            if exhausted:
                reasons.append(f"{route.key}: daily quota exhausted for {exhausted:.0f}s more")
                continue
            overrides: dict[str, Any] = {}
            if route.reasoning_effort:
                overrides["reasoning_effort"] = route.reasoning_effort
            for attempt in range(1 + route.schema_retries):
                if route.tpm_limit:
                    estimate = estimate or self._estimate(messages, system)
                    self.pacer.wait(route.model, route.tpm_limit, estimate)
                before = len(self.ledger.records)
                try:
                    result = client.complete_structured(
                        messages, schema, system=system, label=label or self.name, **overrides
                    )
                except LLMBudgetError:
                    raise
                except (LLMTransientError, LLMPermanentError, LLMOutputError) as exc:
                    reasons.append(f"{route.key}: {type(exc).__name__}: {str(exc)[:300]}")
                    reset = daily_quota_reset_s(exc)
                    if reset is not None:
                        self.pacer.mark_exhausted(route.model, reset)
                    if is_schema_rejection(exc) and attempt < route.schema_retries:
                        continue  # resample on the same, cheaper route first
                    break
                finally:
                    used = sum(r.usage.total_tokens for r in self.ledger.records[before:])
                    self.pacer.record(route.model, used)
                self.served_by.append(route.model)
                if reasons:
                    self.fallback_reasons.extend(reasons)
                return result
        self.fallback_reasons.extend(reasons)
        raise LLMRouteError(self.name, reasons)
