"""Map: one group of ChangeItems -> GroupAnalysis, on the cheap tier.

Each call sees only its group, so groups are independent: they can be checkpointed one at a
time, a failure costs one group rather than the run, and the input stays far below the
size where models start skimming. What a map call cannot do is see the whole release; that
is the reducer's job (chunk-and-merge, notes/concepts/chunk-and-merge.md).
"""

from __future__ import annotations

from ..chunk import item_prompt_text
from ..llm import StructuredLLM
from ..models import ChangeItem, GroupAnalysis
from ..prompts import Prompt, wrap_untrusted


def build_map_message(repo: str, base: str, head: str, group: list[ChangeItem]) -> str:
    content = "\n\n".join(item_prompt_text(item) for item in group)
    return (
        f"Repository: {repo}\nRange: {base}...{head}\nItems in this batch: {len(group)}\n\n"
        f"{wrap_untrusted('repository_content', content)}\n\n"
        "Return the changes for every item above as JSON."
    )


def map_group(
    llm: StructuredLLM,
    prompt: Prompt,
    *,
    repo: str,
    base: str,
    head: str,
    group: list[ChangeItem],
    index: int,
) -> GroupAnalysis:
    return llm.complete_structured(
        build_map_message(repo, base, head, group),
        GroupAnalysis,
        system=prompt.text,
        label=f"map:{index}",
    )
