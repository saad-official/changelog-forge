"""Record and replay model calls, so the whole pipeline can be evaluated with no network.

A cassette is the ordered list of (label, schema, response, call records) a live run
produced. Replay returns the same responses for the same labels in the same order and puts
the original call records back into the ledger, so a recorded eval reports the tokens and
dollars the live run actually spent.

A replay that asks for a label the cassette does not have raises `CassetteMiss` - loudly,
and deliberately *not* an LLMError, so the pipeline's graceful-degradation path cannot
swallow it. A miss means the pipeline's call pattern changed (different grouping, a new
call): re-record with `uv run evals --live --record`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, TypeVar

from llm_kit import Ledger
from pydantic import BaseModel

from ..pipeline.run import ledger_from_json

TModel = TypeVar("TModel", bound=BaseModel)


class CassetteMiss(RuntimeError):
    pass


class RecordingLLM:
    def __init__(self, inner: Any, ledger: Ledger, tape: list[dict[str, Any]]):
        self.inner = inner
        self.ledger = ledger
        self.tape = tape

    @property
    def served_by(self) -> list[str]:
        return getattr(self.inner, "served_by", [])

    def complete_structured(
        self,
        messages: Any,
        schema: type[TModel],
        *,
        system: str | None = None,
        label: str | None = None,
    ) -> TModel:
        before = len(self.ledger.records)
        try:
            result = self.inner.complete_structured(messages, schema, system=system, label=label)
        except Exception as exc:
            self.tape.append(
                {
                    "label": label,
                    "schema": schema.__name__,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                    "records": [r.as_dict() for r in self.ledger.records[before:]],
                }
            )
            raise
        self.tape.append(
            {
                "label": label,
                "schema": schema.__name__,
                "response": result.model_dump(mode="json"),
                "records": [r.as_dict() for r in self.ledger.records[before:]],
            }
        )
        return result


class ReplayLLM:
    def __init__(self, tape: list[dict[str, Any]], ledger: Ledger, served_by: list[str]):
        self.ledger = ledger
        self.served_by = list(served_by)
        self._by_label: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for entry in tape:
            self._by_label[str(entry["label"])].append(entry)

    def complete_structured(
        self,
        messages: Any,
        schema: type[TModel],
        *,
        system: str | None = None,
        label: str | None = None,
    ) -> TModel:
        queue = self._by_label.get(str(label))
        if not queue:
            raise CassetteMiss(f"no recorded response for {label!r}; re-record the cassette")
        entry = queue.popleft()
        if entry["schema"] != schema.__name__:
            raise CassetteMiss(
                f"{label!r} was recorded as {entry['schema']}, now {schema.__name__}"
            )
        for record in ledger_from_json(entry.get("records"), None).records:
            self.ledger.add(record)
        if "error" in entry:
            from llm_kit import LLMOutputError

            raise LLMOutputError(f"recorded failure: {entry['error']}")
        return schema.model_validate(entry["response"])
