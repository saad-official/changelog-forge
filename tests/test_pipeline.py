import itertools

import pytest
from llm_kit import Ledger, LLMBudgetError, LLMOutputError

from changelog_forge.chunk import ApproxCounter
from changelog_forge.models import Change, GroupAnalysis
from changelog_forge.pipeline import DictCheckpoints, Pipeline, PipelineSuspended
from changelog_forge.pipeline.run import ledger_from_json, ledger_to_json

from .conftest import FakeLLM


def make_pipeline(ledger=None, map_script=None, reduce_script=None, **kwargs):
    ledger = ledger or Ledger(max_usd=0.05)
    map_llm = FakeLLM(ledger, "openai/gpt-oss-20b", map_script)
    reduce_llm = FakeLLM(ledger, "openai/gpt-oss-120b", reduce_script)
    pipeline = Pipeline(
        map_llm=map_llm,
        reduce_llm=reduce_llm,
        ledger=ledger,
        counter=ApproxCounter(),
        budget_usd=0.05,
        **kwargs,
    )
    return pipeline, map_llm, reduce_llm


def test_end_to_end_produces_two_consistent_documents(sample_range):
    events = []
    statuses = []
    pipeline, map_llm, reduce_llm = make_pipeline(
        emit=lambda kind, message, data: events.append((kind, data)),
        on_status=statuses.append,
    )
    result = pipeline.run(sample_range, ["user", "dev"])

    assert map_llm.calls == [("map:1", "GroupAnalysis")]
    assert reduce_llm.calls == [("reduce:dev", "DevDraft"), ("reduce:user", "UserDraft")]
    assert statuses == ["mapping", "reducing", "verifying"]
    dev, user = result.outputs["dev"], result.outputs["user"]
    assert dev.intro == "Developer intro." and user.intro == "User intro."
    assert [s.category for s in dev.sections] == ["breaking", "feature", "fix", "docs", "internal"]
    assert [s.category for s in user.sections] == ["breaking", "feature", "fix"]
    # same facts in both documents: every user item exists in the dev document
    dev_ids = {i.id for i in dev.all_items()}
    assert {i.id for i in user.all_items()} <= dev_ids
    assert dev.sections[0].items[0].migration_note == "Upgrade to Node 20."
    assert result.prompt_versions["map"].startswith("map.v1@")
    assert result.models == {"map": "openai/gpt-oss-20b", "reduce": "openai/gpt-oss-120b"}
    assert result.usage.calls == 3 and result.usage.usd > 0
    assert {(m.model, m.stage) for m in result.usage.by_model} == {
        ("openai/gpt-oss-20b", "map"),
        ("openai/gpt-oss-120b", "reduce"),
    }
    assert result.verification.dropped_refs == [] and result.verification.degraded == []
    group_event = next(data for kind, data in events if data.get("stage") == "mapping")
    assert (group_event["group"], group_event["groups"]) == (1, 1)
    assert "[#10](https://github.com/acme/widgets/pull/10)" in result.markdown["dev"]


def test_hallucinated_refs_never_reach_the_documents(sample_range):
    def liar(message, schema, label):
        return GroupAnalysis(
            changes=[
                Change(
                    category="feature",
                    user_summary="Invented",
                    dev_summary="Invented",
                    breaking=False,
                    breaking_confidence=0,
                    migration_note=None,
                    refs=["#31337", "cafebabe"],
                )
            ]
        )

    pipeline, _, _ = make_pipeline(map_script={"map": liar})
    result = pipeline.run(sample_range, ["dev"])
    assert {d.ref for d in result.verification.dropped_refs} == {"#31337", "cafebabe"}
    md = result.markdown["dev"]
    assert "31337" not in md and "Invented" not in md
    # every input still appears, as a fallback item
    assert len(result.verification.uncovered_inputs) == 5
    assert all(i.source == "fallback" for i in result.outputs["dev"].all_items())


def test_a_failing_map_group_degrades_to_fallback_items(sample_range):
    pipeline, _, _ = make_pipeline(map_script={"map": LLMOutputError("bad json")}, target_tokens=60)
    result = pipeline.run(sample_range, ["user", "dev"])
    assert result.group_count > 1
    assert len(result.verification.degraded) == result.group_count
    assert all("LLMOutputError" in d for d in result.verification.degraded)
    assert len(result.outputs["dev"].all_items()) == 5


def test_budget_exhaustion_stops_calling_the_model(sample_range):
    pipeline, map_llm, _ = make_pipeline(
        map_script={"map:1": LLMBudgetError("cost budget exhausted")}, target_tokens=60
    )
    result = pipeline.run(sample_range, ["dev"])
    assert [label for label, _ in map_llm.calls] == ["map:1"]  # later groups never called
    assert "budget exhausted" in result.verification.degraded[0]
    assert any("skipped" in d for d in result.verification.degraded[1:])


def test_a_failing_reducer_falls_back_to_a_template(sample_range):
    pipeline, _, _ = make_pipeline(reduce_script={"reduce": LLMOutputError("nope")})
    result = pipeline.run(sample_range, ["user", "dev"])
    assert result.outputs["user"].intro.startswith("This release of acme/widgets brings")
    assert result.outputs["dev"].intro.startswith("5 changes in acme/widgets")
    assert len([d for d in result.verification.degraded if d.startswith("reduce")]) == 2


def test_a_suspended_run_resumes_from_checkpoints_without_repeating_work(sample_range):
    checkpoints = DictCheckpoints()
    ticks = itertools.count()
    ledger = Ledger(max_usd=0.05)
    first, map_llm, _ = make_pipeline(
        ledger=ledger,
        checkpoints=checkpoints,
        target_tokens=60,
        deadline=2,
        clock=lambda: next(ticks),  # the deadline passes after the second map group
    )
    with pytest.raises(PipelineSuspended):
        first.run(sample_range, ["user", "dev"])
    done_groups = [label for label, _ in map_llm.calls]
    assert done_groups == ["map:1", "map:2"]
    assert len(checkpoints.get("ledger")) == 2

    resumed_ledger = ledger_from_json(checkpoints.get("ledger"), 0.05)
    second, map_llm2, _ = make_pipeline(
        ledger=resumed_ledger, checkpoints=checkpoints, target_tokens=60
    )
    result = second.run(sample_range, ["user", "dev"])
    assert "map:1" not in [label for label, _ in map_llm2.calls]
    assert result.usage.calls == len(checkpoints.get("ledger"))
    assert result.usage.calls == result.group_count + 2  # every call counted exactly once


def test_ledger_round_trips_through_json():
    ledger = Ledger()
    FakeLLM(ledger).complete_structured("x", GroupAnalysis, label="map:1")
    rebuilt = ledger_from_json(ledger_to_json(ledger), 0.01)
    assert rebuilt.total_usd == pytest.approx(ledger.total_usd)
    assert rebuilt.max_usd == 0.01
