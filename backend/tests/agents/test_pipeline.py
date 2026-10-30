from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel

from haqqi.agents.pipeline import analyze_case
from haqqi.llm.client import LLMUnavailable, Message
from haqqi.models import IssueType
from haqqi.rag.retrieve import RetrievedChunk
from tests.agents.fakes import FakeLLM
from tests.agents.test_analysis import FACTS, PASS, REVISE, WAGES, pack_law, reply
from tests.agents.test_writer import writer

WAGE_LINE = ["Unpaid wages: [[AMOUNT_1]]"]


def search(_query: str, issue_types: Sequence[IssueType]) -> list[RetrievedChunk]:
    return pack_law(*issue_types)


def scripted(critic_verdicts: list[object]) -> FakeLLM:
    return FakeLLM(
        {
            "analyst": [reply(WAGES)],
            "critic": critic_verdicts,  # type: ignore[dict-item]
            "revision": [reply(WAGES)],
            "writer": [writer(letter_facts_ar="لم أتقاضَ أجري", amount_lines=WAGE_LINE)],
        }
    )


def test_stages_in_order_and_analysis_uses_calculator_money() -> None:
    stages: list[str] = []
    analysis = analyze_case(FACTS, "salary unpaid", scripted([PASS]), search, stages.append)

    assert stages == ["retrieving", "calculating", "analysing", "critiquing", "writing"]
    assert analysis.total_aed == Decimal("4800.00")  # 2 × 2,400
    assert analysis.violations[0].article.chunk_id == WAGES
    assert analysis.critic_verdict == "pass" and not analysis.revised
    assert analysis.writer and analysis.writer.amount_lines == ["Unpaid wages: AED 4,800.00"]


def test_revision_stage_is_reported() -> None:
    stages: list[str] = []
    analysis = analyze_case(FACTS, "salary unpaid", scripted([REVISE]), search, stages.append)

    assert "revising" in stages
    assert analysis.revised


def test_writer_failure_still_returns_the_checked_results() -> None:
    bad = writer(letter_facts_ar="لم أتقاضَ أجري", explanation="You are owed AED 99,999.")
    llm = FakeLLM(
        {"analyst": [reply(WAGES)], "critic": [PASS], "writer": [bad, bad]}  # rejected twice
    )
    analysis = analyze_case(FACTS, "salary unpaid", llm, search, lambda _stage: None)

    assert analysis.writer is None and analysis.writer_failed
    assert analysis.total_aed == Decimal("4800.00")  # the calculator's money is unaffected
    assert analysis.violations[0].article.chunk_id == WAGES


class _WriterDown(FakeLLM):
    """Analyst and Critic answer; the Writer's model is unreachable (5xx/timeouts, 30 Oct)."""

    def complete[T: BaseModel](self, stage: str, messages: Sequence[Message], schema: type[T]) -> T:
        if stage == "writer":
            raise LLMUnavailable("writer: the language model is not responding, try again later")
        return super().complete(stage, messages, schema)


def test_unreachable_writer_still_returns_the_checked_results() -> None:
    llm = _WriterDown({"analyst": [reply(WAGES)], "critic": [PASS]})
    stages: list[str] = []
    analysis = analyze_case(FACTS, "salary unpaid", llm, search, stages.append)

    assert stages[-1] == "writing"
    assert analysis.writer is None and analysis.writer_failed
    assert analysis.total_aed == Decimal("4800.00")  # the calculator's money is unaffected
    assert analysis.claim and analysis.claim[0].amount_aed == Decimal("4800.00")
    assert analysis.violations[0].article.chunk_id == WAGES
