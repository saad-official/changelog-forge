"""Chunk: ChangeItem[] -> groups that each fit one map call.

Why chunk at all: a 400-commit range is ~100k tokens of titles and PR bodies. Even where a
context window would take it, quality drops on long inputs (items in the middle get
skimmed), output limits truncate the JSON, and Groq's free tier allows 8,000 tokens per
minute. Smaller groups are summarised more faithfully, fail independently, and can be
retried or checkpointed one at a time.

Why tokens, not item counts: 30 dependency bumps and 30 PRs with 1,500-character bodies
differ ten-fold in size. Counting with `tiktoken` `o200k_base` is an *approximation* (the
gpt-oss models use o200k-family encodings; Gemini does not) - good enough to pack groups,
and the provider's reported usage is what the ledger records afterwards.

The one invariant: a PR's commits are never split across groups. Normalise already folded
each PR into a single ChangeItem, so packing whole items guarantees it.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Protocol

from .models import ChangeItem

log = logging.getLogger(__name__)

TARGET_TOKENS = 4500  # see routing.toml [chunk]
MAX_FILES_IN_PROMPT = 20


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class ApproxCounter:
    """~4 characters per token. The offline fallback, and the deterministic test double."""

    name = "approx-4cpt"

    def count(self, text: str) -> int:
        return math.ceil(len(text) / 4)


class TiktokenCounter:
    name = "tiktoken:o200k_base"

    def __init__(self) -> None:
        import tiktoken

        self._encoding = tiktoken.get_encoding("o200k_base")

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))


@lru_cache(maxsize=1)
def default_counter() -> TokenCounter:
    """tiktoken when its encoding file is available, otherwise the approximation.

    `tiktoken` downloads the encoding on first use. The Docker image pre-fetches it at build
    time; anywhere offline we degrade to the 4-chars-per-token estimate and say so, rather
    than failing a run over a packing heuristic.
    """
    try:
        return TiktokenCounter()
    except Exception as exc:
        log.warning("tiktoken unavailable (%s); using the 4-chars-per-token estimate", exc)
        return ApproxCounter()


def _escape(text: str) -> str:
    # Repository text is untrusted. A PR body containing "</repository_content>" must not
    # be able to close our delimiter and start talking to the model as if it were us.
    return text.replace("</item", "&lt;/item").replace(
        "</repository_content", "&lt;/repository_content"
    )


def item_prompt_text(item: ChangeItem) -> str:
    """How one item appears inside the map prompt. Counted by the chunker, so it is the
    single definition of an item's size."""
    lines = [f'<item id="{item.id}" refs="{", ".join(item.refs)}">']
    lines.append(f"title: {_escape(item.title)}")
    if item.conventional_type:
        scope = f"({item.conventional_scope})" if item.conventional_scope else ""
        bang = "!" if item.conventional_breaking else ""
        lines.append(f"conventional: {item.conventional_type}{scope}{bang}")
    if item.labels:
        lines.append(f"labels: {_escape(', '.join(item.labels))}")
    if item.files:
        shown = item.files[:MAX_FILES_IN_PROMPT]
        more = len(item.files) - len(shown)
        suffix = f" (+{more} more)" if more > 0 else ""
        lines.append(f"files: {_escape(', '.join(shown))}{suffix}")
    if item.body:
        lines.append(f"body:\n{_escape(item.body)}")
    lines.append("</item>")
    return "\n".join(lines)


def chunk_items(
    items: list[ChangeItem],
    *,
    target_tokens: int = TARGET_TOKENS,
    counter: TokenCounter | None = None,
) -> list[list[ChangeItem]]:
    """Greedy, order-preserving packing up to `target_tokens` per group.

    Order-preserving rather than bin-packing: items next to each other in history are
    usually related (a feature and its follow-up fix), and the model dedupes better when it
    sees them together. An item larger than the target on its own gets its own group - it
    cannot be split without splitting a PR.
    """
    counter = counter or default_counter()
    groups: list[list[ChangeItem]] = []
    current: list[ChangeItem] = []
    current_tokens = 0
    for item in items:
        size = counter.count(item_prompt_text(item))
        if current and current_tokens + size > target_tokens:
            groups.append(current)
            current, current_tokens = [], 0
        current.append(item)
        current_tokens += size
    if current:
        groups.append(current)
    return groups


def group_tokens(group: list[ChangeItem], counter: TokenCounter | None = None) -> int:
    counter = counter or default_counter()
    return sum(counter.count(item_prompt_text(item)) for item in group)
