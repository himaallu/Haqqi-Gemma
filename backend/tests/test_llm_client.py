import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from haqqi.config import Settings
from haqqi.llm.client import (
    LLMClient,
    LLMOutputError,
    LLMUnavailable,
    Message,
    Provider,
    extract_json,
    providers_from_settings,
)


class Verdict(BaseModel):
    verdict: str
    score: int


def reply(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def client_for(
    responses: list[httpx.Response], seen: list[dict[str, object]] | None = None
) -> tuple[LLMClient, list[float]]:
    queue = list(responses)
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return queue.pop(0)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    k2 = Provider("k2", "https://k2.test/v1", "m", SecretStr("secret-key"))
    return LLMClient([k2], http=http, sleep=sleeps.append), sleeps


ASK = [Message("system", "rules"), Message("user", "data")]


@pytest.mark.parametrize(
    "content",
    [
        '{"verdict": "pass", "score": 3}',
        'Sure!\n```json\n{"verdict": "pass", "score": 3}\n```',
        '<think>The user wants {json} ...</think>\n{"verdict": "pass", "score": 3}',
        # Gemma 4 puts its reasoning in the reply as <thought>, braces and all (30 Oct).
        '<thought>Reply as {"verdict": ...}.</thought>{"verdict": "pass", "score": 3}',
    ],
    ids=["plain", "fenced", "think-tag", "gemma-thought-tag"],
)
def test_parses_valid_fenced_and_think_tag_replies(content: str) -> None:
    client, _ = client_for([reply(content)])
    assert client.complete("critic", ASK, Verdict) == Verdict(verdict="pass", score=3)


def test_invalid_json_gets_one_correction_retry() -> None:
    seen: list[dict[str, object]] = []
    client, _ = client_for(
        [reply('{"verdict": "pass"}'), reply('{"verdict": "pass", "score": 1}')], seen
    )

    assert client.complete("critic", ASK, Verdict).score == 1
    retry_messages = seen[1]["messages"]
    assert isinstance(retry_messages, list)
    assert retry_messages[-1]["role"] == "user"
    assert "score" in retry_messages[-1]["content"]  # names the missing field


def test_invalid_twice_raises_llm_output_error() -> None:
    client, _ = client_for([reply("no json here"), reply('{"verdict": 1}')])
    with pytest.raises(LLMOutputError, match="critic: invalid JSON after one retry"):
        client.complete("critic", ASK, Verdict)


def test_rate_limit_waits_retry_after_then_succeeds() -> None:
    limited = httpx.Response(429, headers={"retry-after": "3"}, json={})
    client, sleeps = client_for([limited, reply('{"verdict": "pass", "score": 2}')])

    assert client.complete("intake", ASK, Verdict).score == 2
    assert 3.0 in sleeps


def test_repeated_server_errors_raise_unavailable_without_leaking_the_key() -> None:
    client, sleeps = client_for([httpx.Response(503), httpx.Response(502), httpx.Response(500)])
    with pytest.raises(LLMUnavailable) as err:
        client.complete("writer", ASK, Verdict)
    assert "secret-key" not in str(err.value)
    assert [s for s in sleeps if s >= 1] == [2.0, 5.0]  # three tries, backoff 2 s then 5 s


def test_a_server_error_is_retried_on_the_same_model_and_can_succeed_on_the_third_try() -> None:
    client, sleeps = client_for(
        [httpx.Response(500), httpx.Response(503), reply('{"verdict": "pass", "score": 4}')]
    )
    assert client.complete("analyst", ASK, Verdict).score == 4
    assert [s for s in sleeps if s >= 1] == [2.0, 5.0]


def test_the_writer_gets_a_longer_timeout_than_the_other_stages() -> None:
    timeouts: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        stage = json.loads(request.content)["messages"][0]["content"]
        timeouts[stage] = request.extensions["timeout"]["read"]
        return reply('{"verdict": "pass", "score": 1}')

    k2 = Provider("k2", "https://k2.test/v1", "m", SecretStr("a"))
    client = LLMClient(
        [k2], http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=_no_sleep
    )
    for stage in ("intake", "analyst", "critic", "writer"):
        client.complete(stage, [Message("user", stage)], Verdict)
    assert timeouts == {"intake": 60.0, "analyst": 60.0, "critic": 60.0, "writer": 120.0}


def test_falls_back_to_the_next_provider() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "k2.test":
            return httpx.Response(503)
        return reply('{"verdict": "pass", "score": 9}')

    http = httpx.Client(transport=httpx.MockTransport(handler))
    providers = [
        Provider("k2", "https://k2.test/v1", "m", SecretStr("a")),
        Provider("backup", "https://backup.test/v1", "m", SecretStr("b")),
    ]
    client = LLMClient(providers, http=http, sleep=_no_sleep)

    assert client.complete("intake", ASK, Verdict).score == 9
    assert calls == ["k2.test", "k2.test", "k2.test", "backup.test"]


def _no_sleep(_seconds: float) -> None:
    return None


def test_no_key_configured_is_unavailable() -> None:
    client = LLMClient([Provider("k2", "https://k2.test/v1", "m", None)])
    with pytest.raises(LLMUnavailable, match="K2_API_KEY"):
        client.complete("intake", ASK, Verdict)


def test_extract_json_rejects_text_without_an_object() -> None:
    with pytest.raises(ValueError):
        extract_json("I cannot help with that.")


def test_settings_put_the_chosen_provider_first_and_send_gemini_extras() -> None:
    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    models = [p.model for p in providers_from_settings(settings)]
    assert models == [
        "gemini-3-flash-preview",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-3.1-flash-lite",
        "IFM/K2-Horizon-375B-A23B",
    ]

    k2_first = Settings(_env_file=None, llm_provider="k2", gemini_api_key="g", k2_api_key="k")
    assert [p.name for p in providers_from_settings(k2_first)][:2] == [
        "k2",
        "gemini:gemini-3-flash-preview",
    ]

    seen: list[dict[str, object]] = []
    client, _ = client_for([reply('{"verdict": "pass", "score": 1}')], seen)
    gemini = providers_from_settings(settings)[0]
    client = LLMClient([gemini], http=client._http, sleep=_no_sleep)
    client.complete("intake", ASK, Verdict)
    assert seen[0]["reasoning_effort"] == "low"
    assert seen[0]["model"] == "gemini-3-flash-preview"


def test_gemma_models_on_the_gemini_endpoint_get_no_reasoning_effort() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key="g",
        gemini_model="gemma-4-31b-it",
        gemini_fallback_models=["gemini-3.5-flash"],
    )
    gemma, flash, _ = providers_from_settings(settings)
    assert gemma.extra == {}
    assert flash.extra == {"reasoning_effort": "low"}

    seen: list[dict[str, object]] = []
    client, _ = client_for([reply('{"verdict": "pass", "score": 1}')], seen)
    client = LLMClient([gemma], http=client._http, sleep=_no_sleep)
    client.complete("intake", ASK, Verdict)
    assert "reasoning_effort" not in seen[0]
    assert seen[0]["model"] == "gemma-4-31b-it"


def test_free_tier_quota_falls_back_to_k2() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(429, headers={"retry-after": "1"}, json={})
        return reply('{"verdict": "pass", "score": 4}')

    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    client = LLMClient(
        providers_from_settings(settings),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )

    assert client.complete("intake", ASK, Verdict).score == 4
    # Every free Gemini model is tried once (no waiting on a quota), then K2.
    assert hosts == ["generativelanguage.googleapis.com"] * 4 + ["api.ifm.ai"]


def test_rate_limited_model_hands_over_to_the_next_free_model_without_waiting() -> None:
    models: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "gemini-3-flash-preview":
            return httpx.Response(429, headers={"retry-after": "40"}, json={})
        return reply('{"verdict": "pass", "score": 5}')

    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    client = LLMClient(
        providers_from_settings(settings),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    assert client.complete("intake", ASK, Verdict).score == 5
    assert models == ["gemini-3-flash-preview", "gemini-3.5-flash"]
    assert all(s <= 0.5 for s in sleeps)  # only the 2 req/s spacing, never the 40 s quota wait


def test_fallback_models_read_from_a_comma_separated_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite, gemini-3.5-flash")
    settings = Settings(_env_file=None)
    assert settings.gemini_fallback_models == ["gemini-3.1-flash-lite", "gemini-3.5-flash"]


DAILY_QUOTA = {
    "error": {
        "code": 429,
        "details": [
            {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]},
            {"retryDelay": "4632s"},
        ],
    }
}


def test_a_model_over_its_daily_quota_is_skipped_on_later_calls() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "gemini-3-flash-preview":
            return httpx.Response(429, json=[DAILY_QUOTA])
        return reply('{"verdict": "pass", "score": 6}')

    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    client = LLMClient(
        providers_from_settings(settings),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )

    client.complete("intake", ASK, Verdict)
    client.complete("analyst", ASK, Verdict)
    assert models == ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.5-flash"]


def test_a_short_rate_limit_does_not_park_the_model() -> None:
    models: list[str] = []
    limited = iter([True])

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == "gemini-3-flash-preview" and next(limited, False):
            return httpx.Response(429, headers={"retry-after": "40"}, json={})
        return reply('{"verdict": "pass", "score": 6}')

    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    client = LLMClient(
        providers_from_settings(settings),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )

    client.complete("intake", ASK, Verdict)
    client.complete("analyst", ASK, Verdict)
    assert models == ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3-flash-preview"]


def test_every_provider_parked_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=[DAILY_QUOTA])

    k2 = Provider("k2", "https://k2.test/v1", "m", SecretStr("a"))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LLMClient([k2], http=http, sleep=_no_sleep)
    with pytest.raises(LLMUnavailable):
        client.complete("intake", ASK, Verdict)
    with pytest.raises(LLMUnavailable, match="over its quota"):
        client.complete("intake", ASK, Verdict)


def test_the_correction_retry_has_no_assistant_turn() -> None:
    # K2 rejects multi-turn history whose assistant messages lack its "thinking" field (HTTP 400,
    # 4 Oct eval run). The rejected reply is quoted inside one new user turn instead.
    seen: list[dict[str, object]] = []
    client, _ = client_for(
        [reply('{"verdict": "pass"}'), reply('{"verdict": "pass", "score": 1}')], seen
    )

    assert client.complete("critic", ASK, Verdict).score == 1
    retry = seen[1]["messages"]
    assert isinstance(retry, list)
    assert [m["role"] for m in retry] == ["system", "user", "user"]
    last = retry[-1]["content"]
    assert '{"verdict": "pass"}' in last and "score" in last  # the old reply and the reason


def test_a_provider_error_message_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    body = {"error": {"message": "Add a supported thinking field to each assistant message"}}
    client, _ = client_for([httpx.Response(400, json=body)])
    with pytest.raises(LLMUnavailable, match="HTTP 400"):
        client.complete("writer", ASK, Verdict)
    assert "thinking field" in caplog.text


def test_quota_errors_are_marked_and_capacity_drops_when_every_model_is_parked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json=[DAILY_QUOTA])

    settings = Settings(_env_file=None, gemini_api_key="g")
    gemini_only = [p for p in providers_from_settings(settings) if p.name.startswith("gemini:")]
    client = LLMClient(
        gemini_only, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=_no_sleep
    )
    assert client.has_capacity()

    with pytest.raises(LLMUnavailable) as first:
        client.complete("ask", ASK, Verdict)
    assert first.value.quota
    assert not client.has_capacity()  # every free model parked over its daily quota
    with pytest.raises(LLMUnavailable) as second:
        client.complete("ask", ASK, Verdict)
    assert second.value.quota


def test_a_timeout_is_not_a_quota_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    k2 = Provider("k2", "https://k2.test/v1", "m", SecretStr("a"))
    client = LLMClient(
        [k2], http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=_no_sleep
    )
    with pytest.raises(LLMUnavailable) as err:
        client.complete("ask", ASK, Verdict)
    assert not err.value.quota


def test_a_timed_out_model_is_parked_and_the_next_one_answers_at_once() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "slow":
            raise httpx.ReadTimeout("hung")
        return reply('{"verdict": "pass", "score": 1}')

    slow = Provider("gemini:slow", "https://g.test/v1", "slow", SecretStr("a"))
    fast = Provider("gemini:fast", "https://g.test/v1", "fast", SecretStr("a"))
    client = LLMClient(
        [slow, fast],
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
        park_on_timeout_s=900,
    )
    assert client.complete("ask", ASK, Verdict).score == 1
    assert calls == ["slow", "fast"]  # no second wait on the hung model
    assert client.is_parked(slow)
    assert client.complete("ask", ASK, Verdict).score == 1
    assert calls == ["slow", "fast", "fast"]  # skipped while parked


def test_without_park_on_timeout_a_timeout_is_retried_twice() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append("k2")
        raise httpx.ReadTimeout("slow")

    k2 = Provider("k2", "https://k2.test/v1", "m", SecretStr("a"))
    client = LLMClient(
        [k2], http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=_no_sleep
    )
    with pytest.raises(LLMUnavailable):
        client.complete("ask", ASK, Verdict)
    assert calls == ["k2", "k2", "k2"]
    assert not client.is_parked(k2)


def test_no_provider_means_no_capacity() -> None:
    assert not LLMClient([]).has_capacity()


def test_the_success_hook_sees_each_answered_call_and_never_breaks_one() -> None:
    seen: list[str] = []
    replies = iter([httpx.Response(429, headers={"retry-after": "1"}, json={})])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(replies, reply('{"verdict": "pass", "score": 1}'))

    def hook(provider: Provider) -> None:
        seen.append(provider.name)
        raise RuntimeError("database down")

    settings = Settings(_env_file=None, gemini_api_key="g", k2_api_key="k")
    client = LLMClient(
        providers_from_settings(settings),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
        on_success=hook,
    )
    assert client.complete("ask", ASK, Verdict).score == 1
    assert seen == ["gemini:gemini-3.5-flash"]  # the refused call isn't counted
