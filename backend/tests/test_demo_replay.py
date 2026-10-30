"""DEMO_REPLAY without a database or network: TC-02 (Urdu, and the English pitch story) from
recorded Gemma 4 runs (no model calls).

The API version, with the database and the streamed stages, is in tests/api/test_demo_replay.py.
"""

import socket
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from eval.cases_io import load_cases
from eval.demo.record import ENGLISH_PITCH_STORY
from pypdf import PdfReader

from haqqi import demo_replay
from haqqi.agents.intake import run_intake
from haqqi.agents.pipeline import analyze_case
from haqqi.api.schemas import CreateCaseRequest
from haqqi.models import CaseFacts
from haqqi.pdf.letter import Identity, build_letter, render_pdf

TC02 = next(c for c in load_cases() if c.id == "TC-02")
# (language, story): the Urdu eval story and the /demo page's English example (same facts).
REPLAYED = [("ur", TC02.story), ("en", ENGLISH_PITCH_STORY)]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_only_the_recorded_stories_in_their_language_are_replayed() -> None:
    assert demo_replay.find(TC02.story, "ur") is not None
    assert demo_replay.find("  " + TC02.story.replace(" ", "\n", 1) + " ", "ur") is not None
    assert demo_replay.find(ENGLISH_PITCH_STORY, "en") is not None
    assert demo_replay.find(TC02.story, "en") is None
    assert demo_replay.find(ENGLISH_PITCH_STORY, "ur") is None
    assert demo_replay.find("My salary has not been paid for 3 months.", "en") is None


@pytest.mark.parametrize(("language", "story"), REPLAYED, ids=["ur", "en"])
def test_replayed_stages_take_realistic_but_short_pauses(language: str, story: str) -> None:
    rec = demo_replay.find(story, language)
    assert rec is not None
    stages = [call["stage"] for call in rec["calls"]]
    total = demo_replay.SEARCH_DELAY_S + sum(demo_replay.STAGE_DELAY_S[s] for s in stages)
    assert all(1 <= demo_replay.STAGE_DELAY_S[s] <= 3 for s in stages)
    assert total < 15


@pytest.mark.parametrize(("language", "story"), REPLAYED, ids=["ur", "en"])
def test_tc02_replay_computes_the_claim_and_the_arabic_pdf_live(language: str, story: str) -> None:
    rec = demo_replay.find(story, language)
    assert rec is not None
    pauses: list[float] = []
    llm = demo_replay.ReplayLLM(rec, sleep=pauses.append)
    req = CreateCaseRequest.model_validate(
        {"language": language, "story": story, "contract_text": TC02.contract_text, **TC02.form}
    )
    extracted = run_intake(llm, req)
    known = {k: v for k, v in extracted.model_dump().items() if v is not None}
    facts = CaseFacts.model_validate(
        {
            **{k: v for k, v in known.items() if k in CaseFacts.model_fields},
            **TC02.confirm,
            "language": language,
            "story": story,
        }
    )
    stages: list[str] = []
    analysis = analyze_case(
        facts,
        extracted.facts_summary_en or story,
        llm,
        demo_replay.replay_search(rec, sleep=pauses.append),
        stages.append,
    )

    assert stages == ["retrieving", "calculating", "analysing", "critiquing", "writing"]
    assert analysis.total_aed == Decimal("6229.59")  # the calculator, run live (CASES.md)
    assert not analysis.writer_failed and analysis.writer is not None
    assert "fdl33-2021:art43:cl3" in {v.article.chunk_id for v in analysis.violations}
    assert sum(pauses) < 15

    pdf = render_pdf(build_letter(facts, analysis, Identity(), date(2026, 10, 30)))
    text = "".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert pdf.startswith(b"%PDF") and "6,229.59" in text
