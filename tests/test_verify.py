from changelog_forge.models import (
    Change,
    DevDraft,
    DuplicateGroup,
    MergedItem,
    SectionDraft,
    UserDraft,
    Verification,
)
from changelog_forge.normalise import normalise
from changelog_forge.pipeline.verify import (
    LIMITS,
    RefIndex,
    apply_duplicates,
    enforce_item_budgets,
    plan_sections,
    record_downgrades,
    trim,
    verify_changes,
)

from .conftest import sha


def change(refs, **overrides) -> Change:
    data = {
        "category": "fix",
        "user_summary": "u",
        "dev_summary": "d",
        "breaking": False,
        "breaking_confidence": 0.0,
        "migration_note": None,
        "refs": refs,
    }
    data.update(overrides)
    return Change(**data)


def test_ref_index_resolves_prs_sha_prefixes_and_urls(sample_range):
    items, _ = normalise(sample_range)
    index = RefIndex(items)
    assert index.resolve("#10") == ("#10", "ok")
    assert index.resolve("PR #11")[0] == "#11"
    assert index.resolve("12")[0] == "#12"  # bare PR number, as gpt-oss-20b emits them
    assert index.resolve("13")[0] is None
    assert index.resolve("https://github.com/acme/widgets/pull/12")[0] == "#12"
    # a sha that belongs to a PR becomes the PR; a lone commit stays a full sha
    assert index.resolve(sha("a2")[:7])[0] == "#10"
    assert index.resolve(sha("d1")[:9])[0] == sha("d1")
    assert index.resolve(f"https://github.com/acme/widgets/commit/{sha('e1')}")[0] == sha("e1")
    assert index.resolve("#999")[0] is None
    assert index.resolve("deadbee")[0] is None
    assert index.resolve("v2.0.0")[0] is None


def test_unknown_refs_are_dropped_and_recorded_and_refless_items_removed(sample_range):
    items, _ = normalise(sample_range)
    verification = Verification()
    merged = verify_changes(
        [
            change(["#10", "#999"], category="feature"),
            change(["#4242"]),  # hallucinated entirely
            change(["#11", "#12", "#12"]),
            change([sha("d1")[:7]], category="docs"),
            change([sha("e1")], category="internal"),
        ],
        items,
        verification,
    )
    assert [d.ref for d in verification.dropped_refs] == ["#999", "#4242"]
    assert all(d.stage == "map" for d in verification.dropped_refs)
    assert verification.checked_refs == 8
    assert len(verification.dropped_items) == 1
    assert [m.refs for m in merged] == [["#10"], ["#11", "#12"], [sha("d1")], [sha("e1")]]
    assert [m.id for m in merged] == ["i1", "i2", "i3", "i4"]
    assert verification.uncovered_inputs == []


def test_inputs_the_model_skipped_get_fallback_items(sample_range):
    items, _ = normalise(sample_range)
    verification = Verification()
    merged = verify_changes([change(["#10"], category="feature")], items, verification)
    assert verification.uncovered_inputs == [
        "pr-11",
        "pr-12",
        f"c-{sha('d1')[:7]}",
        f"c-{sha('e1')[:7]}",
    ]
    fallback = {m.refs[0]: m for m in merged if m.source == "fallback"}
    assert fallback["#11"].breaking and fallback["#11"].breaking_confidence >= 0.6
    assert fallback["#12"].category == "fix"
    assert fallback[sha("e1")].category == "internal"


def test_confidence_is_clamped_and_the_same_change_twice_is_merged(sample_range):
    items, _ = normalise(sample_range)
    verification = Verification()
    merged = verify_changes(
        [
            change(["#11"], breaking=True, breaking_confidence=7.0),
            change(["#11"], breaking=True, breaking_confidence=0.5, migration_note="Use Node 20"),
        ],
        items,
        verification,
    )
    first = merged[0]
    assert first.breaking_confidence == 1.0
    assert first.migration_note == "Use Node 20"
    assert len(verification.clamped) == 1
    assert len([m for m in merged if m.refs == ["#11"]]) == 1


def item(i: int, category="fix", breaking=False, confidence=0.0, refs=None) -> MergedItem:
    return MergedItem(
        id=f"i{i}",
        category=category,
        user_summary=f"user {i}",
        dev_summary=f"dev {i}",
        breaking=breaking,
        breaking_confidence=confidence,
        refs=refs or [f"#{i}"],
    )


def test_duplicates_merge_only_known_ids():
    items = [item(1), item(2), item(3)]
    verification = Verification()
    draft = DevDraft(
        intro="",
        sections=[],
        duplicates=[
            DuplicateGroup(keep="i1", merge=["i2", "i99"]),
            DuplicateGroup(keep="i42", merge=["i3"]),
        ],
    )
    merged = apply_duplicates(items, draft, verification)
    assert [m.id for m in merged] == ["i1", "i3"]
    assert merged[0].refs == ["#1", "#2"]
    assert set(verification.unknown_item_ids) == {"i99", "i42"}


def test_low_confidence_breaking_is_possibly_breaking_for_devs_and_not_breaking_for_users():
    items = [
        item(1, "feature", breaking=True, confidence=0.9),
        item(2, "fix", breaking=True, confidence=0.4),
        item(3, "docs"),
        item(4, "internal"),
    ]
    verification = Verification()
    record_downgrades(items, verification, "acme/widgets")
    assert [d.item_id for d in verification.downgraded] == ["i2"]
    assert verification.downgraded[0].refs[0].url == "https://github.com/acme/widgets/pull/2"
    assert "below 0.6" in verification.downgraded[0].reason

    empty = UserDraft(intro="", sections=[])
    dev = plan_sections(items, DevDraft(intro="", sections=[], duplicates=[]), "dev", verification)
    user = plan_sections(items, empty, "user", verification)
    assert [(key, [i.id for i in its]) for key, _, its in dev] == [
        ("breaking", ["i1"]),
        ("possibly_breaking", ["i2"]),
        ("docs", ["i3"]),
        ("internal", ["i4"]),
    ]
    assert [(key, [i.id for i in its]) for key, _, its in user] == [
        ("breaking", ["i1"]),
        ("fix", ["i2"]),
    ]


def test_reducer_orders_but_cannot_invent_or_move_items():
    items = [item(1, "fix"), item(2, "fix"), item(3, "feature")]
    verification = Verification()
    draft = UserDraft(
        intro="",
        sections=[
            # i3 placed under "fix" by the reducer: it stays a feature; i9 does not exist
            SectionDraft(section="fix", prose="Fixed things.", item_ids=["i2", "i9", "i3", "i2"]),
        ],
    )
    plan = plan_sections(items, draft, "user", verification)
    as_ids = {key: [i.id for i in its] for key, _, its in plan}
    assert as_ids == {"feature": ["i3"], "fix": ["i2", "i1"]}
    assert dict((k, p) for k, p, _ in plan)["fix"] == "Fixed things."
    assert verification.unknown_item_ids == ["user:i9"]


def test_length_budgets_trim_at_word_boundaries_and_record_it():
    long = "word " * 200
    items = [item(1)]
    items[0].user_summary = long
    items[0].migration_note = long
    verification = Verification()
    enforce_item_budgets(items, verification)
    assert len(items[0].user_summary) <= LIMITS["user_summary"]
    assert items[0].user_summary.endswith("word…")
    assert "i1.user_summary" in verification.trimmed and "i1.migration_note" in verification.trimmed
    assert trim("short", 10) == "short"


def test_fallback_for_a_meaningless_commit_title():
    from changelog_forge.models import ChangeItem
    from changelog_forge.pipeline.verify import fallback_item

    item = ChangeItem(id="c-1", kind="commit", title="+", shas=[sha("plus")])
    fallback = fallback_item(item, RefIndex([item]))
    assert fallback.user_summary == f"Maintenance commit {sha('plus')[:7]}"
    assert fallback.source == "fallback" and fallback.refs == [sha("plus")]
