import json

import httpx
import pytest
import respx

from changelog_forge.action import (
    MARKER,
    ActionError,
    compose_body,
    previous_tag,
    publish,
    resolve_range,
)
from changelog_forge.pipeline import Pipeline

from .conftest import FakeLLM


def test_previous_tag_respects_prefixes_and_skips_prereleases():
    tags = [
        "v1.2.0",
        "v1.10.0",
        "v1.9.3",
        "v2.0.0-rc.1",
        "v1.11.0",
        "@ai-sdk/zai@3.0.1",
        "ai@7.0.1",
    ]
    assert previous_tag(tags, "v1.11.0") == "v1.10.0"
    assert previous_tag(tags, "v2.0.0") == "v1.11.0"
    assert previous_tag(tags, "ai@7.0.2") == "ai@7.0.1"
    assert previous_tag(tags, "v1.2.0") is None


def env_with_event(tmp_path, event: dict, **extra) -> dict:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    return {"GITHUB_EVENT_PATH": str(path), "GITHUB_REPOSITORY": "acme/widgets", **extra}


def test_range_for_a_pull_request(tmp_path):
    env = env_with_event(
        tmp_path, {"pull_request": {"number": 7, "base": {"sha": "aaa"}, "head": {"sha": "bbb"}}}
    )
    with httpx.Client(base_url="https://api.github.com") as http:
        assert resolve_range(env, http) == ("aaa", "bbb")


@respx.mock
def test_range_for_a_tag_push_uses_the_previous_tag(tmp_path):
    respx.get("https://api.github.com/repos/acme/widgets/tags").mock(
        return_value=httpx.Response(200, json=[{"name": "v1.1.0"}, {"name": "v1.0.0"}])
    )
    env = env_with_event(tmp_path, {}, GITHUB_REF="refs/tags/v1.1.0", GITHUB_REF_NAME="v1.1.0")
    with httpx.Client(base_url="https://api.github.com") as http:
        assert resolve_range(env, http) == ("v1.0.0", "v1.1.0")


@respx.mock
def test_range_without_a_previous_tag_is_a_clear_error(tmp_path):
    respx.get("https://api.github.com/repos/acme/widgets/tags").mock(
        return_value=httpx.Response(200, json=[])
    )
    env = env_with_event(tmp_path, {}, GITHUB_SHA="abc")
    with httpx.Client(base_url="https://api.github.com") as http, pytest.raises(ActionError):
        resolve_range(env, http)


@pytest.fixture
def notes_file(tmp_path, sample_range):
    from llm_kit import Ledger

    from changelog_forge.chunk import ApproxCounter

    ledger = Ledger()
    result = Pipeline(
        map_llm=FakeLLM(ledger), reduce_llm=FakeLLM(ledger), ledger=ledger, counter=ApproxCounter()
    ).run(sample_range, ["user", "dev"])
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps({"outputs": {k: v.model_dump(mode="json") for k, v in result.outputs.items()}}),
        encoding="utf-8",
    )
    return path


def test_body_puts_user_notes_first_and_folds_developer_notes(notes_file):
    from changelog_forge.models import ReleaseNotes

    data = json.loads(notes_file.read_text(encoding="utf-8"))
    body = compose_body({k: ReleaseNotes.model_validate(v) for k, v in data["outputs"].items()})
    assert body.startswith(MARKER)
    assert body.index("What's new") < body.index("<summary>Developer notes</summary>")


@respx.mock
def test_publish_creates_or_updates_the_release(tmp_path, notes_file):
    env = env_with_event(tmp_path, {}, CF_OUTPUT="release-body")
    respx.get("https://api.github.com/repos/acme/widgets/releases/tags/v1.1.0").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    patch = respx.patch("https://api.github.com/repos/acme/widgets/releases/5").mock(
        return_value=httpx.Response(200, json={"html_url": "https://github.com/r/5"})
    )
    with httpx.Client(base_url="https://api.github.com") as http:
        assert publish(env, http, notes_file) == "https://github.com/r/5"
    assert MARKER in json.loads(patch.calls.last.request.content)["body"]


@respx.mock
def test_publish_comments_on_the_pull_request(tmp_path, notes_file):
    env = env_with_event(tmp_path, {"pull_request": {"number": 7}}, CF_OUTPUT="pr-comment")
    comment = respx.post("https://api.github.com/repos/acme/widgets/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"html_url": "https://github.com/c/1"})
    )
    with httpx.Client(base_url="https://api.github.com") as http:
        assert publish(env, http, notes_file) == "https://github.com/c/1"
    assert comment.called
