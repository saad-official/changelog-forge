"""The GitHub Action's glue: work out the range from the event, then publish the notes.

    python -m changelog_forge.action range               -> prints "base..head"
    python -m changelog_forge.action publish notes.json  -> release body or PR comment

`action/entrypoint.sh` runs `range`, then the normal CLI (`changelog-forge ... --json`),
then `publish`. Everything GitHub-specific lives here so the CLI stays a plain CLI.

Inputs arrive as environment variables set in action.yml (CF_*), plus the runner's own
GITHUB_* variables. The token is the workflow's GITHUB_TOKEN unless the user passes one.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from .models import ReleaseNotes
from .pipeline.render import render_markdown

API = "https://api.github.com"
MARKER = "<!-- changelog-forge -->"
_NUMBERS = re.compile(r"\d+")


class ActionError(RuntimeError):
    pass


def _client(token: str | None) -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "changelog-forge-action"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=os.environ.get("GITHUB_API_URL", API), headers=headers, timeout=20)


def _version_key(tag: str) -> tuple[str, tuple[int, ...]]:
    """("v", (1, 2, 3)) for "v1.2.3"; ("ai@", (7, 0, 1)) for "ai@7.0.1". The prefix keeps
    monorepo package tags apart: the previous `ai@` tag is never a `@ai-sdk/zai@` tag."""
    match = _NUMBERS.search(tag)
    prefix = tag[: match.start()] if match else tag
    return prefix, tuple(int(n) for n in _NUMBERS.findall(tag[len(prefix) :]))


def previous_tag(tags: list[str], head: str) -> str | None:
    prefix, version = _version_key(head)
    pre_release = re.compile(r"(alpha|beta|rc|canary|next|preview)", re.IGNORECASE)
    candidates = [
        tag
        for tag in tags
        if tag != head
        and _version_key(tag)[0] == prefix
        and _version_key(tag)[1] < version
        and not pre_release.search(tag)
    ]
    return max(candidates, key=lambda tag: _version_key(tag)[1], default=None)


def _event(env: dict[str, str]) -> dict[str, Any]:
    path = env.get("GITHUB_EVENT_PATH")
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {}


def resolve_range(env: dict[str, str], http: httpx.Client) -> tuple[str, str]:
    """base/head from explicit inputs, else from the triggering event."""
    event = _event(env)
    base, head = env.get("CF_BASE") or "", env.get("CF_HEAD") or ""
    if "pull_request" in event:
        base = base or event["pull_request"]["base"]["sha"]
        head = head or event["pull_request"]["head"]["sha"]
    elif "release" in event:
        head = head or event["release"]["tag_name"]
    elif env.get("GITHUB_REF", "").startswith("refs/tags/"):
        head = head or env.get("GITHUB_REF_NAME", "")
    head = head or env.get("GITHUB_SHA", "")
    if not base:
        repo = env["GITHUB_REPOSITORY"]
        response = http.get(f"/repos/{repo}/tags", params={"per_page": 100})
        response.raise_for_status()
        base = previous_tag([tag["name"] for tag in response.json()], head) or ""
    if not base or not head:
        raise ActionError(
            "could not work out the range: set the `base` input, or run on a tag push, "
            "a release, or a pull request"
        )
    return base, head


def compose_body(outputs: dict[str, ReleaseNotes]) -> str:
    """User notes first; developer notes folded underneath, so one body serves both."""
    parts = [MARKER]
    if "user" in outputs:
        parts.append(render_markdown(outputs["user"]))
    if "dev" in outputs:
        dev = render_markdown(outputs["dev"])
        if "user" in outputs:
            parts.append(f"<details>\n<summary>Developer notes</summary>\n\n{dev}\n</details>")
        else:
            parts.append(dev)
    return "\n\n".join(parts) + "\n"


def publish(env: dict[str, str], http: httpx.Client, notes_path: Path) -> str:
    data = json.loads(notes_path.read_text(encoding="utf-8"))
    outputs = {k: ReleaseNotes.model_validate(v) for k, v in data["outputs"].items()}
    body = compose_body(outputs)
    repo = env["GITHUB_REPOSITORY"]
    mode = env.get("CF_OUTPUT", "pr-comment")
    head = next(iter(outputs.values())).head

    if mode == "release-body":
        existing = http.get(f"/repos/{repo}/releases/tags/{head}")
        if existing.status_code == 404:
            created = http.post(
                f"/repos/{repo}/releases", json={"tag_name": head, "name": head, "body": body}
            )
            created.raise_for_status()
            return created.json().get("html_url", "")
        existing.raise_for_status()
        updated = http.patch(f"/repos/{repo}/releases/{existing.json()['id']}", json={"body": body})
        updated.raise_for_status()
        return updated.json().get("html_url", "")

    if mode == "pr-comment":
        event = _event(env)
        number = (event.get("pull_request") or {}).get("number") or env.get("CF_PR_NUMBER")
        if not number:
            raise ActionError("output: pr-comment needs a pull_request event (or CF_PR_NUMBER)")
        comment = http.post(f"/repos/{repo}/issues/{number}/comments", json={"body": body})
        comment.raise_for_status()
        return comment.json().get("html_url", "")

    raise ActionError(f"unknown output {mode!r}: use release-body or pr-comment")


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    env = dict(os.environ)
    with _client(env.get("GITHUB_TOKEN")) as http:
        try:
            if args[:1] == ["range"]:
                base, head = resolve_range(env, http)
                print(f"{base}..{head}")
            elif args[:1] == ["publish"] and len(args) == 2:
                url = publish(env, http, Path(args[1]))
                print(f"published: {url}", file=sys.stderr)
            else:
                raise ActionError("usage: python -m changelog_forge.action range|publish FILE")
        except (ActionError, httpx.HTTPError) as exc:
            print(f"::error::{exc}", file=sys.stderr)
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
