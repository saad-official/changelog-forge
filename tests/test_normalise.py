from changelog_forge.normalise import (
    BODY_LIMIT,
    clean_body,
    hint_breaking,
    hint_category,
    normalise,
    parse_conventional,
)

from .conftest import collected, commit, sha


def test_conventional_commit_parsing():
    parsed = parse_conventional("feat(router)!: drop legacy mode")
    assert (parsed.type, parsed.scope, parsed.breaking) == ("feat", "router", True)
    assert parse_conventional("fix: x", "body\n\nBREAKING CHANGE: y").breaking is True
    assert parse_conventional("Fix: Typo").type == "fix"
    assert parse_conventional("WIP: stuff") is None  # unknown type is not conventional
    assert parse_conventional("Add a thing") is None


def test_squash_commit_becomes_one_pr_item_even_without_api_association():
    items, _ = normalise(collected([commit("s", "Add retries (#42)\n\nDetails here")]))
    assert len(items) == 1
    assert items[0].kind == "pr" and items[0].pr_number == 42
    assert items[0].title == "Add retries"
    assert items[0].refs == ["#42", sha("s")[:7]]


def test_merge_commit_and_its_branch_commits_fold_into_the_pr():
    commits = [
        commit(
            "m1",
            "wip",
            pr=7,
            pr_title="Faster startup",
            pr_body="Lazy imports.",
            labels=["performance"],
            files=["a.py"],
        ),
        commit("m2", "more wip", pr=7, pr_title="Faster startup", files=["a.py", "b.py"]),
        commit("m3", "Merge pull request #7 from me/fast\n\nFaster startup", parents=2),
    ]
    items, _ = normalise(collected(commits))
    assert len(items) == 1
    item = items[0]
    assert item.title == "Faster startup"
    assert item.shas == [sha("m1"), sha("m2"), sha("m3")]
    assert item.files == ["a.py", "b.py"]
    assert hint_category(item) == "performance"


def test_merge_commit_without_api_data_uses_the_body_line_as_title():
    items, _ = normalise(
        collected([commit("m", "Merge pull request #9 from x/y\n\nFix the parser", parents=2)])
    )
    assert items[0].pr_number == 9 and items[0].title == "Fix the parser"


def test_branch_sync_merges_are_skipped():
    commits = [
        commit("x", "Merge branch 'main' into feature", parents=2),
        commit("y", "Merge branches 'pr-1', 'pr-2' and 'pr-3'", parents=3),
        commit("z", "fix: real change"),
    ]
    items, skipped = normalise(collected(commits))
    assert [i.title for i in items] == ["fix: real change"]
    assert skipped == [sha("x"), sha("y")]


def test_body_is_cleaned_and_truncated():
    body = "<!-- template -->\r\nReal text\n\n\n\nmore" + "x" * 5000
    cleaned = clean_body(body)
    assert "template" not in cleaned and "\n\n\n" not in cleaned
    assert len(cleaned) == BODY_LIMIT and cleaned.endswith("…")


def test_category_hints_prefer_labels_then_types_then_words():
    items, _ = normalise(
        collected(
            [
                commit("1", "x", pr=1, pr_title="chore: thing", labels=["type: bug"]),
                commit(
                    "2", "y", pr=2, pr_title="perf(core): faster", labels=["contributor: internal"]
                ),
                commit("3", "[ios][ui] Add toolbar modifiers"),
                commit("4", "\U0001f41b Fix crash on start"),
                commit("5", "Update docker image", labels=["docker"]),
            ]
        )
    )
    assert [hint_category(i) for i in items] == ["fix", "performance", "feature", "fix", "internal"]


def test_breaking_hint_from_bang_footer_or_label():
    items, _ = normalise(
        collected(
            [
                commit("1", "feat!: x"),
                commit("2", "y", pr=2, pr_title="Change default", labels=["breaking change"]),
                commit("3", "fix: z"),
            ]
        )
    )
    assert [hint_breaking(i) for i in items] == [True, True, False]
