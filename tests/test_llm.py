import pytest
from llm_kit import (
    CallRecord,
    Ledger,
    LLMBudgetError,
    LLMOutputError,
    LLMPermanentError,
    LLMTransientError,
)
from llm_kit import Usage as LLMUsage

from changelog_forge.chunk import ApproxCounter
from changelog_forge.llm import LLMRouteError, RoutedLLM, TokenPacer
from changelog_forge.models import GroupAnalysis
from changelog_forge.routing import Route, Tier


class ScriptedClient:
    def __init__(self, route, ledger, outcome):
        self.route, self.ledger, self.outcome = route, ledger, outcome
        self.kwargs = []

    def complete_structured(self, messages, schema, **kwargs):
        self.kwargs.append(kwargs)
        self.ledger.add(CallRecord("p", self.route.model, "x", LLMUsage(3000, 1000), 0.1))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


TIER = Tier(
    provider="groq",
    model="openai/gpt-oss-20b",
    reasoning_effort="low",
    tpm_limit=8000,
    fallbacks=[Route(provider="gemini", model="gemini-3.5-flash-lite")],
)


def routed(outcomes: dict[str, object], pacer=None):
    ledger = Ledger()
    clients = {}

    def factory(route, ledger_, retry, settings):
        outcome = outcomes[route.model]
        if isinstance(outcome, ValueError):
            raise outcome
        clients[route.model] = ScriptedClient(route, ledger_, outcome)
        return clients[route.model]

    llm = RoutedLLM(
        "map",
        TIER,
        ledger=ledger,
        factory=factory,
        pacer=pacer or TokenPacer(),
        counter=ApproxCounter(),
    )
    return llm, ledger, clients


OK = GroupAnalysis(changes=[])


def test_primary_route_serves_and_gets_reasoning_effort():
    llm, _, clients = routed({"openai/gpt-oss-20b": OK, "gemini-3.5-flash-lite": OK})
    assert llm.complete_structured("hi", GroupAnalysis, label="map:1") is OK
    assert llm.served_by == ["openai/gpt-oss-20b"]
    assert clients["openai/gpt-oss-20b"].kwargs[0]["reasoning_effort"] == "low"
    assert "gemini-3.5-flash-lite" not in clients  # never constructed


@pytest.mark.parametrize(
    "failure",
    [
        LLMTransientError("429 after retries"),
        LLMPermanentError("404 model not found"),
        LLMOutputError("invalid json twice"),
        ValueError("no API key for provider 'groq'"),
    ],
)
def test_falls_back_to_the_next_route(failure):
    llm, _, clients = routed({"openai/gpt-oss-20b": failure, "gemini-3.5-flash-lite": OK})
    assert llm.complete_structured("hi", GroupAnalysis) is OK
    assert llm.served_by == ["gemini-3.5-flash-lite"]
    assert "reasoning_effort" not in clients["gemini-3.5-flash-lite"].kwargs[0]
    assert len(llm.fallback_reasons) == 1


def test_budget_errors_are_never_fallen_back_from():
    llm, _, clients = routed(
        {"openai/gpt-oss-20b": LLMBudgetError("cost budget exhausted"), "gemini-3.5-flash-lite": OK}
    )
    with pytest.raises(LLMBudgetError):
        llm.complete_structured("hi", GroupAnalysis)
    assert "gemini-3.5-flash-lite" not in clients


def test_all_routes_failing_raises_with_every_reason():
    llm, _, _ = routed(
        {
            "openai/gpt-oss-20b": LLMTransientError("429"),
            "gemini-3.5-flash-lite": ValueError("no API key"),
        }
    )
    with pytest.raises(LLMRouteError) as caught:
        llm.complete_structured("hi", GroupAnalysis)
    assert len(caught.value.reasons) == 2


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_token_pacer_waits_for_the_window_to_have_room():
    clock = FakeClock()
    pacer = TokenPacer(clock=clock, sleep=clock.sleep)
    assert pacer.wait("m", 8000, 5000) == 0
    pacer.record("m", 5000)
    clock.now += 10
    assert pacer.wait("m", 8000, 2000) == 0  # 7,000 fits
    pacer.record("m", 2000)
    clock.now += 5
    waited = pacer.wait("m", 8000, 4000)  # needs the 5,000 from t=1000 to expire
    assert waited == pytest.approx(45)
    assert pacer.wait("other-model", 8000, 7000) == 0  # windows are per model
    assert pacer.wait("m", None, 10**6) == 0  # no limit configured


def test_a_call_bigger_than_the_limit_waits_for_an_empty_window():
    clock = FakeClock()
    pacer = TokenPacer(clock=clock, sleep=clock.sleep)
    pacer.record("m", 1000)
    clock.now += 30
    pacer.record("m", 1000)
    assert pacer.wait("m", 8000, 9000) == pytest.approx(60)


def test_routed_calls_feed_the_pacer_with_ledger_usage():
    clock = FakeClock()
    pacer = TokenPacer(clock=clock, sleep=clock.sleep)
    llm, _, _ = routed({"openai/gpt-oss-20b": OK, "gemini-3.5-flash-lite": OK}, pacer=pacer)
    llm.complete_structured("x" * 4000, GroupAnalysis)  # ~2,500 estimated, 4,000 used
    llm.complete_structured("x" * 4000, GroupAnalysis)
    assert clock.slept == []
    llm.complete_structured("x" * 4000, GroupAnalysis)  # 8,000 used + 2,500 > 8,000
    assert clock.slept and clock.slept[0] == pytest.approx(60)


class FlakyClient(ScriptedClient):
    def __init__(self, route, ledger, outcomes):
        super().__init__(route, ledger, None)
        self.outcomes = list(outcomes)

    def complete_structured(self, messages, schema, **kwargs):
        self.outcome = self.outcomes.pop(0)
        return super().complete_structured(messages, schema, **kwargs)


def test_a_groq_schema_rejection_is_resampled_on_the_same_route_first():
    rejection = LLMPermanentError(
        "400 from provider: Generated JSON does not match the expected schema"
    )
    tier = TIER.model_copy(update={"schema_retries": 1})
    ledger = Ledger()
    clients = {}

    def factory(route, ledger_, retry, settings):
        script = [rejection, OK] if route.model == "openai/gpt-oss-20b" else [OK]
        clients[route.model] = FlakyClient(route, ledger_, script)
        return clients[route.model]

    llm = RoutedLLM("map", tier, ledger=ledger, factory=factory, counter=ApproxCounter())
    assert llm.complete_structured("hi", GroupAnalysis) is OK
    assert llm.served_by == ["openai/gpt-oss-20b"]
    assert "gemini-3.5-flash-lite" not in clients
    assert len(ledger.records) == 2  # both draws are paid for and recorded


def test_other_permanent_errors_are_not_resampled():
    tier = TIER.model_copy(update={"schema_retries": 1})
    clients = {}

    def factory(route, ledger_, retry, settings):
        script = [LLMPermanentError("401 bad key"), OK] if "oss" in route.model else [OK]
        clients[route.model] = FlakyClient(route, ledger_, script)
        return clients[route.model]

    llm = RoutedLLM("map", tier, ledger=Ledger(), factory=factory, counter=ApproxCounter())
    llm.complete_structured("hi", GroupAnalysis)
    assert llm.served_by == ["gemini-3.5-flash-lite"]


def test_a_daily_quota_429_parks_the_route_until_reset():
    from changelog_forge.llm import daily_quota_reset_s

    tpd = LLMTransientError(
        "all 3 attempts failed. Last error: 429 ... on tokens per day (TPD): Limit 200000, "
        "Used 195793, Requested 6734. Please try again in 18m11.664s."
    )
    assert daily_quota_reset_s(tpd) == pytest.approx(18 * 60 + 11.664)
    assert daily_quota_reset_s(LLMTransientError("429 tokens per minute (TPM)")) is None

    clock = FakeClock()
    pacer = TokenPacer(clock=clock, sleep=clock.sleep)
    llm, _, clients = routed({"openai/gpt-oss-20b": tpd, "gemini-3.5-flash-lite": OK}, pacer=pacer)
    llm.complete_structured("a", GroupAnalysis)
    llm.complete_structured("b", GroupAnalysis)
    assert len(clients["openai/gpt-oss-20b"].kwargs) == 1  # second call skipped the route
    assert llm.served_by == ["gemini-3.5-flash-lite", "gemini-3.5-flash-lite"]
    clock.now += 18 * 60 + 12
    assert pacer.exhausted_for("openai/gpt-oss-20b") == 0
