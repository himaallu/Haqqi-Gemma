"""Case API (task 3.11).

POST   /v1/cases               story + form → Intake agent → routing; stores the case (UUIDv4)
GET    /v1/cases/{id}          the case as stored (no story), plus its Analysis once analysed
PATCH  /v1/cases/{id}          the worker confirms or edits the facts → strict CaseFacts
POST   /v1/cases/{id}/analyze  Server-Sent Events: one event per stage, then the Analysis
POST   /v1/cases/{id}/complaint the complaint PDF (Arabic + the worker's language), not stored

The story is stored only for the analysis and expires with the case (7 days); it is never logged.
The complaint's identity fields (name, labour card, employer) are printed into the PDF and dropped:
never stored or logged (flag 8).
"""

import json
import logging
import queue
import threading
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone
from functools import cache
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from haqqi import demo_replay, tracing
from haqqi.agents.intake import run_intake
from haqqi.agents.pipeline import Search, analyze_case
from haqqi.api.schemas import ComplaintRequest, CreateCaseRequest
from haqqi.config import get_settings
from haqqi.core.routing import MISSING_FIELDS, Referral, RouteDecision, route_case
from haqqi.llm.client import (
    Completer,
    LLMClient,
    LLMError,
    LLMUnavailable,
    Provider,
    providers_from_settings,
)
from haqqi.models import Analysis, CaseFacts, ExtractedFacts, IssueType
from haqqi.pdf.letter import Identity, LetterError, build_letter, render_pdf
from haqqi.rag.embed import Embedder, get_embedder
from haqqi.rag.lawdata import load_law_pack
from haqqi.rag.retrieve import RetrievedChunk, retrieve
from haqqi.usage import UsageStore, key_id

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/cases")

Status = Literal["out_of_scope", "need_info", "ready", "confirmed", "analysed"]
# Stop proxies (Render, nginx) from buffering the stream, so stages reach the browser live.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
NOT_EDITABLE = {"story", "contract_text", "language"}
UAE = timezone(timedelta(hours=4), "GST")  # the complaint's date; the UAE has no DST


class CaseView(BaseModel):
    id: UUID
    status: Status
    extracted: ExtractedFacts
    missing: list[str] = []
    missing_fields: list[str] = []  # form fields to highlight for `missing`
    referral: str | None = None
    referral_kind: Referral | None = None
    confirmed: dict[str, Any] | None = None  # CaseFacts without the story
    analysis: Analysis | None = None


# Dependencies (overridden in tests)


@cache
def usage_store() -> UsageStore | None:
    url = get_settings().database_url
    return UsageStore(url) if url else None


def count_gemini_call(provider: Provider) -> None:
    """Counts a successful free-tier Gemini call (haqqi/usage.py), off the request's path."""
    store = usage_store()
    if store is None or provider.api_key is None or not provider.name.startswith("gemini:"):
        return
    key = key_id(provider.api_key.get_secret_value())
    threading.Thread(target=store.record, args=(key, provider.model), daemon=True).start()


@cache
def _main_llm() -> LLMClient:
    return LLMClient.from_settings(get_settings(), on_success=count_gemini_call)


DEMO_TIMEOUT_S = 40.0  # Gemini Flash took up to 35 s for a long Writer reply (task 3.10)
DEMO_PARK_ON_TIMEOUT_S = 900.0


@cache
def demo_llm() -> LLMClient:
    """The pitch demo's client: free Gemini models only, no K2.

    K2 makes a case take minutes, which doesn't work on stage. When the free quota is used up the
    demo gets a quota error at once and shows its prepared examples (docs/demo/TEST_SCRIPT.md).
    A free model that hangs (seen live on 25 Oct: two 90 s timeouts made one answer take 184 s)
    is given up after 40 s and skipped for 15 minutes, so the next model answers.
    """
    providers = providers_from_settings(get_settings())
    return LLMClient(
        [p for p in providers if p.name.startswith("gemini:")],
        on_success=count_gemini_call,
        timeout_s=DEMO_TIMEOUT_S,
        park_on_timeout_s=DEMO_PARK_ON_TIMEOUT_S,
    )


def get_llm(x_haqqi_demo: Annotated[str | None, Header()] = None) -> Completer:
    return demo_llm() if x_haqqi_demo == "1" else _main_llm()


@cache
def get_embedder_dep() -> Embedder:
    return get_embedder(get_settings())


def get_database_url() -> str:
    url = get_settings().database_url
    if not url:
        raise HTTPException(503, "database not configured")
    return url


def get_test_hooks() -> bool:
    return get_settings().haqqi_test_hooks


def _replaying(story: str, language: str) -> bool:
    return get_settings().demo_replay and demo_replay.matches(story, language)


DbUrl = Annotated[str, Depends(get_database_url)]
Llm = Annotated[Completer, Depends(get_llm)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder_dep)]


# Storage


def _save(
    db_url: str, case_id: UUID | None, language: str, status: Status, data: dict[str, Any]
) -> UUID:
    with psycopg.connect(db_url) as conn:
        if case_id is None:
            row = conn.execute(
                "INSERT INTO cases (language, status, facts) VALUES (%s, %s, %s) RETURNING id",
                (language, status, Jsonb(data)),
            ).fetchone()
            assert row is not None
            return UUID(str(row[0]))
        conn.execute(
            "UPDATE cases SET status = %s, facts = %s WHERE id = %s", (status, Jsonb(data), case_id)
        )
        return case_id


def _load(db_url: str, case_id: UUID) -> tuple[Status, dict[str, Any]]:
    status, data, _analysis = _load_full(db_url, case_id)
    return status, data


def _load_full(db_url: str, case_id: UUID) -> tuple[Status, dict[str, Any], dict[str, Any] | None]:
    with psycopg.connect(db_url) as conn:
        row = conn.execute(
            "SELECT status, facts, analysis FROM cases WHERE id = %s AND expires_at > now()",
            (case_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "case not found")
    return row[0], row[1], row[2]


def _save_analysis(db_url: str, case_id: UUID, analysis: Analysis) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE cases SET status = 'analysed', analysis = %s WHERE id = %s",
            (Jsonb(analysis.model_dump(mode="json")), case_id),
        )


def _view(
    case_id: UUID, status: Status, data: dict[str, Any], analysis: Analysis | None = None
) -> CaseView:
    route = data["route"]
    confirmed = data.get("confirmed")
    return CaseView(
        id=case_id,
        status=status,
        extracted=ExtractedFacts.model_validate(data["extracted"]),
        missing=route["missing"],
        missing_fields=[f for m in route["missing"] for f in MISSING_FIELDS.get(m, [])],
        referral=route["referral_text"],
        referral_kind=route["referral"],
        confirmed={k: v for k, v in confirmed.items() if k not in NOT_EDITABLE | {"language"}}
        if confirmed
        else None,
        analysis=analysis,
    )


def _route_data(decision: RouteDecision) -> dict[str, Any]:
    return {
        "route": decision.route,
        "referral": decision.referral,
        "referral_text": decision.referral_text,
        "missing": decision.missing,
    }


# Endpoints


@router.post("", status_code=201)
def create_case(req: CreateCaseRequest, llm: Llm, db_url: DbUrl) -> CaseView:
    if _replaying(req.story, req.language):
        llm = demo_replay.ReplayLLM()
    try:
        with tracing.trace("intake", language=req.language):
            extracted = run_intake(llm, req)
    except LLMError as exc:
        raise _llm_http_error(exc) from None
    decision = route_case(extracted, req.zone, req.worker_type)
    data = {
        "request": req.model_dump(mode="json"),
        "extracted": extracted.model_dump(mode="json"),
        "route": _route_data(decision),
        "confirmed": None,
    }
    case_id = _save(db_url, None, req.language, decision.route, data)
    return _view(case_id, decision.route, data)


@router.get("/{case_id}")
def get_case(case_id: UUID, db_url: DbUrl) -> CaseView:
    status, data, analysis = _load_full(db_url, case_id)
    return _view(
        case_id, status, data, Analysis.model_validate(analysis) if analysis is not None else None
    )


@router.patch("/{case_id}")
def confirm_case(case_id: UUID, edits: dict[str, Any], db_url: DbUrl) -> CaseView:
    _status, data = _load(db_url, case_id)
    bad = sorted(set(edits) - (set(CaseFacts.model_fields) - NOT_EDITABLE))
    if bad:
        raise HTTPException(422, f"fields that cannot be edited here: {bad}")
    request = data["request"]
    extracted = {
        k: v for k, v in data["extracted"].items() if v is not None and k in CaseFacts.model_fields
    }
    merged = {
        **extracted,
        **edits,
        "language": request["language"],
        "story": request["story"],
        "contract_text": request.get("contract_text"),
    }
    try:
        facts = CaseFacts.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            422, exc.errors(include_url=False, include_context=False, include_input=False)
        ) from None
    decision = route_case(
        ExtractedFacts.model_validate(facts.model_dump(include=set(ExtractedFacts.model_fields)))
    )
    status: Status = "out_of_scope" if decision.route == "out_of_scope" else "confirmed"
    data = {**data, "route": _route_data(decision), "confirmed": facts.model_dump(mode="json")}
    _save(db_url, case_id, request["language"], status, data)
    return _view(case_id, status, data)


@router.post("/{case_id}/analyze")
def analyze(
    case_id: UUID,
    llm: Llm,
    embedder: EmbedderDep,
    db_url: DbUrl,
    test_hooks: Annotated[bool, Depends(get_test_hooks)],
    seed_bad_citation: bool = False,
) -> StreamingResponse:
    status, data = _load(db_url, case_id)
    if status == "out_of_scope":
        referral = Analysis(in_scope=False, referral=data["route"]["referral_text"])
        return _sse([("done", referral.model_dump_json())])
    if status not in ("confirmed", "analysed"):
        raise HTTPException(409, "confirm the case facts first (PATCH /v1/cases/{id})")
    facts = CaseFacts.model_validate(data["confirmed"])
    query = data["extracted"].get("facts_summary_en") or facts.story

    def live_search(text: str, issue_types: Sequence[IssueType]) -> list[RetrievedChunk]:
        with psycopg.connect(db_url) as conn:
            return retrieve(conn, text, embedder, load_law_pack(), list(issue_types))

    search: Search = live_search
    replay = _replaying(facts.story, facts.language)
    if replay:
        llm, search = demo_replay.ReplayLLM(), demo_replay.replay_search()
    seed = seed_bad_citation and test_hooks and not replay
    return StreamingResponse(
        _run_streamed(case_id, facts, query, llm, search, db_url, seed, replay=replay),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{case_id}/complaint")
def complaint(case_id: UUID, req: ComplaintRequest, db_url: DbUrl) -> Response:
    status, data, analysis = _load_full(db_url, case_id)
    if status != "analysed" or analysis is None:
        raise HTTPException(409, "analyse the case first (POST /v1/cases/{id}/analyze)")
    try:
        letter = build_letter(
            CaseFacts.model_validate(data["confirmed"]),
            Analysis.model_validate(analysis),
            Identity(name=req.name, labour_card=req.labour_card, employer=req.employer),
            datetime.now(UAE).date(),
        )
    except LetterError as exc:
        raise HTTPException(409, str(exc)) from None
    return Response(
        render_pdf(letter),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="haqqi-complaint.pdf"',
            "Cache-Control": "no-store",
        },
    )


def _run_streamed(
    case_id: UUID,
    facts: CaseFacts,
    query: str,
    llm: Completer,
    search: Search,
    db_url: str,
    seed: bool,
    *,
    replay: bool = False,
) -> Iterator[str]:
    events: queue.Queue[tuple[str, str] | None] = queue.Queue()

    def work() -> None:
        try:
            with tracing.trace("analysis", language=facts.language):
                analysis = analyze_case(
                    facts,
                    query,
                    llm,
                    search,
                    lambda stage: events.put((stage, "{}")),
                    seed_bad_citation=seed,
                )
            if replay:
                analysis = analysis.model_copy(update={"replay_label": demo_replay.LABEL})
            _save_analysis(db_url, case_id, analysis)
            events.put(("done", analysis.model_dump_json()))
        except LLMError as exc:
            log.warning("analysis failed: %s", type(exc).__name__)
            events.put(("error", json.dumps({"detail": _user_message(exc)})))
        except Exception:
            log.exception("analysis crashed")
            events.put(("error", json.dumps({"detail": "Something went wrong. Please try again."})))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (event := events.get()) is not None:
        yield _sse_event(*event)


def _sse(events: Sequence[tuple[str, str]]) -> StreamingResponse:
    return StreamingResponse(
        iter([_sse_event(name, data) for name, data in events]),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _sse_event(name: str, data: str) -> str:
    return f"event: {name}\ndata: {data}\n\n"


def _user_message(exc: LLMError) -> str:
    if isinstance(exc, LLMUnavailable) and exc.quota:
        return (
            "The assistant is busy: the free AI quota is used up for now. Please try again later."
        )
    if isinstance(exc, LLMUnavailable):
        return "The assistant is busy or offline. Please try again in a few minutes."
    return "The assistant gave an answer we could not check. Please try again."


def _llm_http_error(exc: LLMError) -> HTTPException:
    return HTTPException(503 if isinstance(exc, LLMUnavailable) else 502, _user_message(exc))
