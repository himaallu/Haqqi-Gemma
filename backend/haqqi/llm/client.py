"""OpenAI-compatible chat client for the agents (task 3.5).

Every reply is parsed into a Pydantic model (CLAUDE.md): invalid JSON gets one retry with a
short correction, then `LLMOutputError`. Transport failures (5xx, timeout) get two more tries on
the same model after 2 s and 5 s, then the next
provider in the list (flag 18: free-tier Gemini models, then K2), then `LLMUnavailable`. A rate
limit moves straight on to the next provider; only the last one waits it out. Calls are serialised
and spaced to respect K2's 2 requests/second (flag 20). Logs never contain content or keys.
"""

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from haqqi import tracing
from haqqi.config import Settings

log = logging.getLogger(__name__)

TIMEOUT_S = 60.0  # per call; Gemma 4 26B answered intake/analyst/critic in 1-13 s on 30 Oct
# Gemma 4 26B's Writer took 66 s on 30 Oct (a long bilingual reply), so it gets more time.
STAGE_TIMEOUT_S = {"writer": 120.0}
RETRY_BACKOFF_S = (2.0, 5.0)  # waits before the 2nd and 3rd try on a 5xx or timeout
MIN_GAP_S = 0.5  # 2 requests/second
MAX_RETRY_AFTER_S = 10.0
# A 429 asking us to wait longer than this (e.g. a free-tier daily quota, 20 requests per model per
# day) parks that provider instead of costing a request on every later call. Capped at an hour.
PARK_AFTER_S = 60.0
MAX_PARK_S = 3600.0
_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')

# Reasoning blocks: K2 writes <think>, Gemma 4 writes <thought>; either may contain braces.
_THINK = re.compile(r"<(think|thought)>.*?</\1>", re.S)
_FENCE = re.compile(r"```(?:json)?")


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """No provider answered (timeouts, 5xx, rate limits). Show "try again later".

    `quota` is true when every provider turned us away for its rate limit or quota, so the pitch
    demo can switch to its prepared examples instead of retrying.
    """

    def __init__(self, message: str, *, quota: bool = False) -> None:
        super().__init__(message)
        self.quota = quota


class LLMOutputError(LLMError):
    """The model's reply did not parse into the expected schema, even after one retry."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    api_key: SecretStr | None
    extra: dict[str, object] = field(default_factory=dict)  # provider-specific request fields


def providers_from_settings(settings: Settings) -> list[Provider]:
    """The configured primary provider first, the other as fallback (flag 18).

    Gemini is one provider per free-tier model: each model has its own quota, so a rate-limited
    model hands over to the next one instead of waiting.
    """
    gemini = [
        Provider(
            f"gemini:{model}",
            settings.gemini_base_url,
            model,
            settings.gemini_api_key,
            # Less hidden "thinking" means faster replies; our prompts ask for extraction and JSON.
            # Only Gemini models take it: Gemma on the same endpoint may reject the field.
            extra={"reasoning_effort": "low"} if model.startswith("gemini") else {},
        )
        for model in dict.fromkeys([settings.gemini_model, *settings.gemini_fallback_models])
    ]
    k2 = Provider("k2", settings.k2_base_url, settings.k2_model, settings.k2_api_key)
    return [*gemini, k2] if settings.llm_provider == "gemini" else [k2, *gemini]


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def extract_json(text: str) -> str:
    """Strip reasoning tags and code fences; keep the outermost JSON object (ports `parseK2`)."""
    text = _FENCE.sub("", _THINK.sub("", text)).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the reply")
    return text[start : end + 1]


def parse_reply[T: BaseModel](text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate_json(extract_json(text))
    except (ValueError, ValidationError) as exc:
        raise _ParseFailure(_short_error(exc)) from exc


class _ParseFailure(Exception):
    pass


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(parts)
    return str(exc)[:200]


@dataclass(frozen=True)
class _Retry:
    wait_s: float
    rate_limited: bool = False
    parked: bool = False  # timed out and parked: go straight to the next provider


PREVIOUS_LIMIT = 4000  # characters of the rejected reply quoted back


def correction(messages: Sequence[Message], previous: str, reason: str) -> list[Message]:
    """The one correction retry, as a single new user turn.

    The rejected reply is quoted as data instead of being sent as an assistant turn: K2's API
    refuses multi-turn history whose assistant messages lack its "thinking" field (HTTP 400;
    found in the 4 Oct eval run, where it failed every retry). This works for every provider.
    """
    quoted = previous[:PREVIOUS_LIMIT]
    return [
        *messages,
        Message(
            "user",
            f"Your previous reply was rejected because {reason}.\n"
            f"Previous reply (for reference only):\n<<<PREVIOUS_REPLY>>>\n{quoted}\n"
            "<<<END_PREVIOUS_REPLY>>>\n"
            "Reply again with ONLY the corrected JSON object.",
        ),
    ]


class Completer(Protocol):
    """What agents need from a client; `LLMClient` in production, a scripted fake in tests."""

    def complete[T: BaseModel](
        self, stage: str, messages: Sequence[Message], schema: type[T]
    ) -> T: ...


class LLMClient:
    def __init__(
        self,
        providers: Sequence[Provider],
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_success: Callable[[Provider], None] | None = None,
        timeout_s: float = TIMEOUT_S,
        park_on_timeout_s: float = 0.0,
        stage_timeouts_s: dict[str, float] | None = None,
    ) -> None:
        self._providers = [p for p in providers if p.api_key and p.api_key.get_secret_value()]
        self._on_success = on_success  # e.g. counting free-tier calls (haqqi/usage.py)
        self._timeout_s = timeout_s
        self._stage_timeouts = STAGE_TIMEOUT_S if stage_timeouts_s is None else stage_timeouts_s
        # > 0: a model that times out is skipped for this long instead of costing a second wait
        # (the demo's free models sometimes hang; one hang on stage is enough).
        self._park_on_timeout_s = park_on_timeout_s
        self._http = http or httpx.Client(timeout=timeout_s)
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._parked_until: dict[str, float] = {}  # provider name -> time.monotonic() deadline

    @classmethod
    def from_settings(
        cls, settings: Settings, on_success: Callable[[Provider], None] | None = None
    ) -> "LLMClient":
        return cls(providers_from_settings(settings), on_success=on_success)

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers)

    def is_parked(self, provider: Provider) -> bool:
        return self._parked_until.get(provider.name, 0.0) > time.monotonic()

    def has_capacity(self) -> bool:
        """False when no provider is configured or every one is parked over its daily quota."""
        now = time.monotonic()
        return any(self._parked_until.get(p.name, 0.0) <= now for p in self._providers)

    def complete[T: BaseModel](self, stage: str, messages: Sequence[Message], schema: type[T]) -> T:
        """Chat call parsed into `schema`; one correction retry on bad output."""
        convo = list(messages)
        reply = self._chat(stage, convo)
        try:
            return parse_reply(reply, schema)
        except _ParseFailure as first:
            log.warning("llm %s: invalid output, retrying once (%s)", stage, first)
            reason = f"it was not valid for the required JSON format ({first})"
            reply = self._chat(stage, correction(convo, reply, reason))
            try:
                return parse_reply(reply, schema)
            except _ParseFailure as second:
                raise LLMOutputError(f"{stage}: invalid JSON after one retry ({second})") from None

    def _chat(self, stage: str, messages: Sequence[Message]) -> str:
        if not self._providers:
            raise LLMUnavailable("no LLM provider configured (set GEMINI_API_KEY or K2_API_KEY)")
        now = time.monotonic()
        available = [p for p in self._providers if self._parked_until.get(p.name, 0.0) <= now]
        if not available:
            raise LLMUnavailable(
                f"{stage}: every provider is over its quota, try again later", quota=True
            )
        last = available[-1]
        all_rate_limited = True
        for provider in available:
            for attempt in range(1 + len(RETRY_BACKOFF_S)):
                outcome = self._post(stage, provider, messages)
                if isinstance(outcome, str):
                    return outcome
                all_rate_limited = all_rate_limited and outcome.rate_limited
                if outcome.parked:
                    break
                if outcome.rate_limited:
                    if provider is not last or attempt > 0:
                        break  # another provider may be free, or we already waited this one out
                    self._sleep(outcome.wait_s)
                elif attempt < len(RETRY_BACKOFF_S):
                    self._sleep(RETRY_BACKOFF_S[attempt])
            log.warning("llm %s: provider %s unavailable", stage, provider.name)
        raise LLMUnavailable(
            f"{stage}: the language model is not responding, try again later",
            quota=all_rate_limited,
        )

    def _post(self, stage: str, provider: Provider, messages: Sequence[Message]) -> str | _Retry:
        """The reply text, or how long to wait before retrying."""
        assert provider.api_key is not None
        with self._lock:
            wait = self._last_call + MIN_GAP_S - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
        started = time.perf_counter()
        began = datetime.now(UTC)

        def traced(outcome: str, usage: dict[str, Any] | None = None) -> None:
            tracing.generation(
                stage=stage,
                provider=provider.name,
                model=provider.model,
                start=began,
                end=datetime.now(UTC),
                outcome=outcome,
                tokens_in=(usage or {}).get("prompt_tokens"),
                tokens_out=(usage or {}).get("completion_tokens"),
            )

        try:
            resp = self._http.post(
                f"{provider.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {provider.api_key.get_secret_value()}"},
                json={
                    "model": provider.model,
                    "messages": [m.as_dict() for m in messages],
                    "temperature": 0,
                    **provider.extra,
                },
                timeout=self._stage_timeouts.get(stage, self._timeout_s),
            )
        except httpx.HTTPError as exc:
            log.warning("llm %s: %s %s", stage, provider.name, type(exc).__name__)
            traced(type(exc).__name__)
            if isinstance(exc, httpx.TimeoutException) and self._park_on_timeout_s > 0:
                self._parked_until[provider.name] = time.monotonic() + self._park_on_timeout_s
                log.warning("llm %s: %s timed out, parked", stage, provider.name)
                return _Retry(0.0, parked=True)
            return _Retry(1.0)
        latency = time.perf_counter() - started
        if resp.status_code == 429:
            retry_after = _retry_after(resp)
            quota_wait = _quota_wait(resp)
            if quota_wait > PARK_AFTER_S:
                park = min(quota_wait, MAX_PARK_S)
                self._parked_until[provider.name] = time.monotonic() + park
                log.warning("llm %s: %s over quota, parked for %.0fs", stage, provider.name, park)
            log.warning("llm %s: %s rate limited", stage, provider.name)
            traced("rate limited")
            return _Retry(retry_after, rate_limited=True)
        if resp.status_code >= 500:
            log.warning("llm %s: HTTP %s", stage, resp.status_code)
            traced(f"HTTP {resp.status_code}")
            return _Retry(1.0)
        if resp.status_code != 200:
            # The provider's own error text says why (e.g. K2's 400 on multi-turn history).
            log.warning(
                "llm %s: %s HTTP %s: %s", stage, provider.name, resp.status_code, _error_text(resp)
            )
            traced(f"HTTP {resp.status_code}")
            raise LLMUnavailable(f"{stage}: HTTP {resp.status_code} from {provider.name}")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            log.warning("llm %s: unexpected response shape", stage)
            traced("unexpected response shape")
            return _Retry(1.0)
        usage = body.get("usage") or {}
        traced("ok", usage)
        if self._on_success is not None:
            try:
                self._on_success(provider)
            except Exception:  # counting must never cost the worker an answer
                log.warning("llm %s: usage hook failed", stage)
        log.info(
            "llm %s: %s ok in %.1fs, tokens in=%s out=%s",
            stage,
            provider.name,
            latency,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        return str(text)


def _error_text(resp: httpx.Response) -> str:
    """The provider's error message, shortened. Error bodies carry no request content."""
    try:
        body = resp.json()
        error = body.get("error", body) if isinstance(body, dict) else body
        text = error.get("message", error) if isinstance(error, dict) else error
    except ValueError:
        text = resp.text
    return " ".join(str(text).split())[:200]


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(float(resp.headers.get("retry-after", "2")), MAX_RETRY_AFTER_S)
    except ValueError:
        return 2.0


def _quota_wait(resp: httpx.Response) -> float:
    """How long the provider asks us to wait: Gemini puts it in the body, others in Retry-After."""
    match = _RETRY_DELAY.search(resp.text)
    if match:
        return float(match.group(1))
    try:
        return float(resp.headers.get("retry-after", "0"))
    except ValueError:
        return 0.0


def dump_json(data: object) -> str:
    """Compact, stable JSON for prompts."""
    return json.dumps(data, ensure_ascii=False, indent=1, default=str)
