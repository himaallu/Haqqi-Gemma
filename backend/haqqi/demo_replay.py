"""Demo replay (DEMO_REPLAY=1): TC-02 (Urdu) from a recorded Gemma 4 run, without calling a model.

Only the model replies and the retrieved law are replayed. Routing, the calculator, citation
checks and the PDF run live on them, so the amounts and the letter are computed for real. Any
other story goes to the live pipeline. Recorded with `python -m eval.demo.record`.
"""

import json
import os
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from haqqi.llm.client import Completer, Message
from haqqi.models import IssueType
from haqqi.rag.lawdata import load_chunks
from haqqi.rag.retrieve import RetrievedChunk

RECORDING = Path(
    os.environ.get("DEMO_REPLAY_FILE")
    or Path(__file__).resolve().parents[2] / "eval" / "demo" / "tc02_gemma_run1.json"
)
LABEL = "Replay of a recorded Gemma 4 run (30 Oct 2026)"
# Short pauses so the progress view ticks like a real run (Gemma 4 26B took 1-66 s per step).
STAGE_DELAY_S = {"intake": 2.0, "analyst": 2.5, "critic": 1.5, "revision": 2.0, "writer": 3.0}
SEARCH_DELAY_S = 1.0


def _normal(text: str) -> str:
    return " ".join(text.split())


@cache
def recording() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RECORDING.read_text())
    return data


def matches(story: str, language: str) -> bool:
    """True for the recorded case's story (whitespace aside) in its language."""
    rec = recording()
    return language == rec["language"] and _normal(story) == _normal(rec["story"])


class ReplayLLM:
    """A `Completer` that returns the recorded reply for each stage, in order."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self._replies: dict[str, list[Any]] = defaultdict(list)
        for call in recording()["calls"]:
            self._replies[call["stage"]].append(call["output"])
        self._sleep = sleep

    def complete[T: BaseModel](self, stage: str, messages: Sequence[Message], schema: type[T]) -> T:
        if not self._replies[stage]:
            raise RuntimeError(f"demo replay: no recorded {stage} reply left")
        self._sleep(STAGE_DELAY_S.get(stage, 2.0))
        return schema.model_validate(self._replies[stage].pop(0))


def replay_search(
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[str, Sequence[IssueType]], list[RetrievedChunk]]:
    """The law the recorded run retrieved, read from data/law (no embedder, no database)."""

    def search(_text: str, _issue_types: Sequence[IssueType]) -> list[RetrievedChunk]:
        sleep(SEARCH_DELAY_S)
        by_id = {c.id: c for c in load_chunks()}
        return [
            RetrievedChunk(
                id=hit["id"],
                article_no=by_id[hit["id"]].article_no,
                clause_no=by_id[hit["id"]].clause_no,
                title=by_id[hit["id"]].title,
                text_en=by_id[hit["id"]].text_en,
                text_ar=by_id[hit["id"]].text_ar,
                source=hit["source"],
            )
            for hit in recording()["retrieved"]
        ]

    return search


class RecordingLLM:
    """Wraps a live `Completer` and keeps each stage's checked reply (for `eval.demo.record`)."""

    def __init__(self, inner: Completer) -> None:
        self.inner = inner
        self.calls: list[dict[str, Any]] = []

    def complete[T: BaseModel](self, stage: str, messages: Sequence[Message], schema: type[T]) -> T:
        result = self.inner.complete(stage, messages, schema)
        self.calls.append({"stage": stage, "output": result.model_dump(mode="json")})
        return result
