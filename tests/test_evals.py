import json

import pytest
from llm_kit import Ledger

from changelog_forge.chunk import ApproxCounter
from changelog_forge.evals import runner
from changelog_forge.evals.cassette import CassetteMiss, RecordingLLM, ReplayLLM
from changelog_forge.evals.golden import Expected
from changelog_forge.evals.scorers import score_case
from changelog_forge.models import GroupAnalysis, Ref
from changelog_forge.pipeline import Pipeline

from .conftest import FakeLLM, echo_map, make_engine, sha


def run(sample_range, **scripts):
    ledger = Ledger()
    pipeline = Pipeline(
        map_llm=FakeLLM(ledger, script=scripts.get("map")),
        reduce_llm=FakeLLM(ledger, "openai/gpt-oss-120b", scripts.get("reduce")),
        ledger=ledger,
        counter=ApproxCounter(),
    )
    return pipeline.run(sample_range, ["user", "dev"])


EXPECTED = Expected(
    repo="acme/widgets",
    base="v1.0.0",
    head="v1.1.0",
    must_mention=["#10", "#11", "#12", "#99"],  # #99 is not in the input: unscoreable
    must_flag_breaking=["#11"],
    may_flag_breaking=["#12"],
    forbidden_claims=[r"Node 16"],
    categories={"#10": "feature", "#12": "fix", sha("e1"): "internal", sha("d1")[:7]: "docs"},
)


def test_scores_on_a_correct_run(sample_range):
    result = run(sample_range)
    metrics = score_case(
        collected=sample_range,
        outputs=result.outputs,
        markdown=result.markdown,
        verification=result.verification,
        expected=EXPECTED,
    )
    assert metrics["coverage_recall"] == 1.0
    assert metrics["hallucinated_refs"] == 0
    assert metrics["breaking_recall"] == 1.0 and metrics["breaking_precision"] == 1.0
    assert metrics["category_accuracy"] == 1.0
    assert metrics["link_validity"] == 1.0
    assert metrics["length_budget"] == 1.0 and metrics["json_valid"] == 1.0
    assert metrics["forbidden_claims"] == 0
    assert metrics["passed"] is True


def test_scorers_catch_regressions(sample_range):
    result = run(sample_range)
    dev = result.outputs["dev"]
    # simulate a renderer bug: a link to a PR outside the range, and a wrong category
    dev.sections[0].items[0].refs.append(
        Ref(kind="pr", id="#4242", url="https://github.com/acme/widgets/pull/4242", number=4242)
    )
    dev.sections[1].items[0].category = "fix"
    result.markdown["dev"] += "\nNow requires Node 16."
    metrics = score_case(
        collected=sample_range,
        outputs=result.outputs,
        markdown=result.markdown,
        verification=result.verification,
        expected=EXPECTED,
    )
    assert metrics["hallucinated_refs"] == 1
    assert metrics["link_validity"] < 1.0
    assert metrics["category_accuracy"] < 1.0
    assert metrics["forbidden_claims"] == 1
    assert metrics["passed"] is False


def test_missed_breaking_change_lowers_recall(sample_range):
    def no_breaking(message, schema, label):
        analysis = echo_map(message)
        for change in analysis.changes:
            change.breaking, change.breaking_confidence = False, 0.0
        return analysis

    result = run(sample_range, map={"map": no_breaking})
    metrics = score_case(
        collected=sample_range,
        outputs=result.outputs,
        markdown=result.markdown,
        verification=result.verification,
        expected=EXPECTED,
    )
    assert metrics["breaking_recall"] == 0.0
    assert metrics["breaking_precision"] is None  # nothing flagged


def test_cassette_replays_responses_and_costs():
    ledger = Ledger()
    tape = []
    recorder = RecordingLLM(FakeLLM(ledger), ledger, tape)
    recorder.complete_structured(
        '<item id="x" refs="#1">\ntitle: fix: a', GroupAnalysis, label="map:1"
    )
    assert tape[0]["label"] == "map:1" and len(tape[0]["records"]) == 1

    replay_ledger = Ledger()
    replay = ReplayLLM(json.loads(json.dumps(tape)), replay_ledger, ["openai/gpt-oss-20b"])
    result = replay.complete_structured("anything", GroupAnalysis, label="map:1")
    assert result.changes[0].refs == ["#1"]
    assert replay_ledger.total_usd == pytest.approx(ledger.total_usd)
    with pytest.raises(CassetteMiss):
        replay.complete_structured("x", GroupAnalysis, label="map:1")  # tape exhausted


def test_record_then_replay_the_golden_set(tmp_path, settings, sample_range, monkeypatch):
    slug = "acme__widgets"
    (tmp_path / slug).mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": "test-v1",
                "cases": [
                    {"slug": slug, "repo": "acme/widgets", "base": "v1.0.0", "head": "v1.1.0"},
                    {
                        "slug": "later",
                        "repo": "a/b",
                        "base": "1",
                        "head": "2",
                        "status": "todo",
                        "todo": "uv run evals collect a/b 1..2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / slug / "input.json").write_text(sample_range.model_dump_json(), encoding="utf-8")
    (tmp_path / slug / "expected.json").write_text(EXPECTED.model_dump_json(), encoding="utf-8")
    engine = make_engine(settings)

    live = runner.run_golden_set(engine, live=True, record=True, root=tmp_path)
    assert (tmp_path / slug / "cassette.json").is_file()
    assert (tmp_path / slug / "output.dev.md").is_file()
    recorded = runner.run_golden_set(engine, live=False, root=tmp_path)

    live_metrics = live["cases"][0]["metrics"]
    assert recorded["cases"][0]["metrics"] == live_metrics
    assert recorded["aggregate"]["usd"] == pytest.approx(live["aggregate"]["usd"])
    assert recorded["aggregate"]["passed"] == 1
    assert recorded["todo"][0]["slug"] == "later"

    out = tmp_path / "evals.md"
    runner.write_markdown(recorded, out)
    text = out.read_text(encoding="utf-8")
    assert "| acme__widgets | 6 |" in text and "per 100 commits" in text
    assert "uv run evals collect a/b 1..2" in text
