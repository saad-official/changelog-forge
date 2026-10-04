from changelog_forge.models import MergedItem, ReleaseNotes, UserDraft, Verification
from changelog_forge.pipeline.render import build_notes, md_safe, render_markdown

from .conftest import collected, commit, sha


def build(audience: str, items: list[MergedItem]) -> ReleaseNotes:
    data = collected([commit("a", "x", pr=1), commit("b", "y")])
    return build_notes(
        audience=audience,
        items=items,
        draft=UserDraft(intro="Intro @everyone <b>bold</b>", sections=[]),
        collected=data,
        verification=Verification(),
        prompt_versions={"map": "map.v1@abc"},
        models={"map": "openai/gpt-oss-20b"},
    )


ITEMS = [
    MergedItem(
        id="i1",
        category="feature",
        user_summary="You can export CSV.",
        dev_summary="Adds `export()`; thanks @octocat.",
        breaking=False,
        breaking_confidence=0.0,
        refs=["#1"],
    ),
    MergedItem(
        id="i2",
        category="fix",
        user_summary="Crash fixed.",
        dev_summary="Fixes a crash.",
        breaking=True,
        breaking_confidence=0.4,
        migration_note="Nothing to do.",
        refs=[sha("b")],
    ),
    MergedItem(
        id="i3",
        category="internal",
        user_summary="Chore.",
        dev_summary="Bumps deps.",
        breaking=False,
        breaking_confidence=0.0,
        refs=[sha("b")],
    ),
]


def test_links_and_sections_in_the_dev_document():
    notes = build("dev", [i.model_copy(deep=True) for i in ITEMS])
    md = render_markdown(notes)
    assert "[#1](https://github.com/acme/widgets/pull/1)" in md
    assert f"[{sha('b')[:7]}](https://github.com/acme/widgets/commit/{sha('b')})" in md
    assert md.index("### Possibly breaking") < md.index("### Features") < md.index("### Internal")
    assert "(confidence 0.4)" in md
    assert "  - Migration: Nothing to do." in md
    assert "`@octocat`" in md  # mentions never ping


def test_user_document_hides_internal_items_and_unconfirmed_breaking_flags():
    notes = build("user", [i.model_copy(deep=True) for i in ITEMS])
    assert [s.category for s in notes.sections] == ["feature", "fix"]
    fix = notes.sections[1].items[0]
    assert not fix.breaking and not fix.possibly_breaking and fix.migration_note is None
    md = render_markdown(notes)
    assert "Internal" not in md and "Possibly breaking" not in md


def test_json_shape_matches_the_web_contract():
    notes = build("user", [i.model_copy(deep=True) for i in ITEMS])
    data = notes.model_dump(mode="json")
    section = data["sections"][0]
    assert set(section) >= {"category", "title", "prose", "items"}
    ref = section["items"][0]["refs"][0]
    assert ref == {
        "kind": "pr",
        "id": "#1",
        "url": "https://github.com/acme/widgets/pull/1",
        "number": 1,
        "sha": None,
    }
    assert ReleaseNotes.model_validate(data) == notes


def test_markdown_is_safe_to_post():
    assert md_safe("hi @team <script>\n# heading") == "hi `@team` &lt;script> # heading"
    assert md_safe("email a@b.com") == "email a@b.com"
    md = render_markdown(build("user", []))
    assert "_No changes in this range are relevant to this audience._" in md
    assert "&lt;b>" in md
