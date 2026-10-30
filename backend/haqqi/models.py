"""Data contracts for a case (task 3.1, flags 12-13).

Flow: the Intake agent returns `ExtractedFacts` (everything optional), the worker confirms or
edits them, and the result is a strict `CaseFacts`. Money is `Decimal` and is only ever
written by `haqqi.core.calculator`; LLM outputs (`CriticReport`, `WriterOutput`) carry no amounts.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["en", "hi", "ur", "ml", "bn", "tl", "ne", "ar"]
Zone = Literal["mainland", "free_zone", "difc", "adgm"]
WorkerType = Literal["private_sector", "domestic"]
ContractType = Literal["full_time", "part_time", "temporary", "flexible"]
Termination = Literal["employer", "resigned", "still_employed"]
Confidence = Literal["high", "medium", "low"]
IssueType = Literal[
    "unpaid_wages",
    "illegal_deduction",
    "termination",
    "notice_pay",
    "gratuity",
    "leave",
    "overtime",
    "document_retention",
    "other",
]

Money = Decimal  # AED; written only by the calculator


class Emirate(StrEnum):
    ABU_DHABI = "abu_dhabi"
    DUBAI = "dubai"
    SHARJAH = "sharjah"
    AJMAN = "ajman"
    UMM_AL_QUWAIN = "umm_al_quwain"
    RAS_AL_KHAIMAH = "ras_al_khaimah"
    FUJAIRAH = "fujairah"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedFacts(_Model):
    """What the Intake agent read from the story and form. Anything may be missing."""

    language: Language | None = None
    issue_types: list[IssueType] = []
    emirate: Emirate | None = None
    zone: Zone | None = None
    free_zone_name: str | None = None
    worker_type: WorkerType | None = None
    contract_type: ContractType | None = None
    weekly_hours: Decimal | None = Field(default=None, gt=0, le=168)
    start_date: date | None = None
    end_date: date | None = None
    basic_wage_aed: Decimal | None = Field(default=None, ge=0)
    total_wage_aed: Decimal | None = Field(default=None, ge=0)
    months_unpaid: int | None = Field(default=None, ge=0)
    deducted_amount_aed: Decimal | None = Field(default=None, ge=0)
    deducted_monthly_aed: Decimal | None = Field(default=None, ge=0)
    unused_leave_days: int | None = Field(default=None, ge=0)
    unpaid_absence_days: int | None = Field(default=None, ge=0)
    termination: Termination | None = None
    notice_days_contract: int | None = Field(default=None, ge=0)
    notice_days_given: int | None = Field(default=None, ge=0)
    in_scope: bool | None = None
    scope_reason: str = ""
    missing_info: list[str] = []
    facts_summary_en: str = ""


class CaseFacts(_Model):
    """Facts the worker has confirmed. Strict: the calculator and agents work from this."""

    language: Language
    emirate: Emirate
    zone: Zone
    free_zone_name: str | None = None
    worker_type: WorkerType
    contract_type: ContractType = "full_time"
    weekly_hours: Decimal | None = Field(default=None, gt=0, le=168)
    start_date: date
    end_date: date | None = None
    basic_wage_aed: Money = Field(gt=0)
    total_wage_aed: Money = Field(gt=0)
    months_unpaid: int = Field(default=0, ge=0)
    deducted_amount_aed: Money = Field(default=Decimal(0), ge=0)
    deducted_monthly_aed: Money | None = Field(default=None, ge=0)
    unused_leave_days: int | None = Field(default=None, ge=0)  # None = the worker doesn't know
    unpaid_absence_days: int = Field(default=0, ge=0)
    termination: Termination
    notice_days_contract: int = Field(default=30, ge=0)
    notice_days_given: int = Field(default=0, ge=0)
    issue_types: list[IssueType] = []
    story: str = ""
    contract_text: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.basic_wage_aed > self.total_wage_aed:
            raise ValueError("basic wage cannot exceed total wage")
        if self.termination == "still_employed":
            if self.end_date is not None:
                raise ValueError("end_date must be empty while still employed")
        elif self.end_date is None:
            raise ValueError("end_date is required when the job has ended")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class Citation(_Model):
    chunk_id: str  # e.g. fdl33-2021:art51:cl2; must exist in the retrieved law
    law_id: str
    article_no: int
    clause_no: int | None
    quote: str


class Violation(_Model):
    issue: str
    article: Citation
    confidence: Confidence


class ClaimLine(_Model):
    item: str  # e.g. "Gratuity"
    amount_aed: Money | None  # None = not calculated (see note)
    formula: str  # e.g. "21 × (2,000 ÷ 30) × 3 years"
    article: Citation
    note: str = ""


class CriticProblem(_Model):
    where: str
    problem: str
    fix: str


class CriticReport(_Model):
    verdict: Literal["pass", "revise"]
    problems: list[CriticProblem] = []
    missed_issues: list[str] = []


class WriterOutput(_Model):
    """Worker-facing text and the letter's facts section. Amounts are inserted from the calculator.

    Code builds the rest of the complaint letter (haqqi/pdf/letter.py); the Writer only narrates.
    """

    headline: str
    explanation: str  # in the worker's language
    amount_lines: list[str]  # one per claim line, in the worker's language
    checklist: list[str]
    letter_facts_ar: str  # the letter's facts section, formal Arabic
    letter_facts_translation: str  # the same section in the worker's language (flag 9)


class Analysis(_Model):
    in_scope: bool
    referral: str | None = None
    violations: list[Violation] = []
    not_covered: list[str] = []
    claim: list[ClaimLine] = []
    worker_owes: list[ClaimLine] = []  # e.g. notice the worker didn't serve (flag 2)
    total_aed: Money = Decimal(0)
    above_mohre_limit: bool = False
    explanation: str = ""
    next_steps: list[str] = []
    documents_to_gather: list[str] = []
    time_limit_note: str = ""
    critic_verdict: Literal["pass", "revise"] | None = None
    revised: bool = False
    writer: WriterOutput | None = None  # worker-language text and the Arabic letter
    writer_failed: bool = False  # the Writer's output failed our checks; the rest is still valid
    # Set by DEMO_REPLAY: the model replies came from a recording (shown on the results page).
    replay_label: str | None = None
    # Task 8.5: no finding of medium or high confidence. Always recomputed from the findings.
    unsure: bool = False

    @model_validator(mode="before")
    @classmethod
    def _upgrade_stored_writer(cls, data: object) -> object:
        """Analyses saved before CHANGES.md 22 hold the whole letter; keep the rest of their text.

        Their facts section is empty, so the complaint download asks for a fresh analysis.
        """
        if isinstance(data, dict) and isinstance(data.get("writer"), dict):
            writer = dict(data["writer"])
            if "arabic_letter" in writer:
                writer.pop("arabic_letter")
                writer.pop("letter_translation", None)
                writer.setdefault("letter_facts_ar", "")
                writer.setdefault("letter_facts_translation", "")
                data = {**data, "writer": writer}
        return data

    @model_validator(mode="after")
    def _set_unsure(self) -> Self:
        """'I'm not sure' (task 8.5): in scope, but no finding is more than a possibility."""
        self.unsure = self.in_scope and not any(
            v.confidence in ("high", "medium") for v in self.violations
        )
        return self
