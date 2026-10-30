"""DEMO_REPLAY through the API: TC-02 (Urdu) with no model call and no network, under 15 s.

Live test (local database): `make test-live`.
"""

import json
import socket
import time
from collections.abc import Iterator
from typing import Any

import pytest
from eval.cases_io import load_cases
from fastapi.testclient import TestClient

from haqqi import demo_replay
from haqqi.api import cases
from haqqi.api.main import create_app
from haqqi.config import get_settings
from tests.agents.fakes import FakeLLM

pytestmark = pytest.mark.live

TC02 = next(c for c in load_cases() if c.id == "TC-02")


@pytest.fixture
def replay_client(local_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)  # psycopg (libpq) is unaffected
    monkeypatch.setenv("DEMO_REPLAY", "1")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[cases.get_llm] = lambda: FakeLLM({})  # fails if anything calls it
    app.dependency_overrides[cases.get_database_url] = lambda: local_db_url
    yield TestClient(app)
    get_settings.cache_clear()


def events(body: str) -> list[tuple[str, Any]]:
    out = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_tc02_replays_end_to_end_without_a_model_or_network(replay_client: TestClient) -> None:
    started = time.perf_counter()
    body = {"language": "ur", "story": TC02.story, "contract_text": TC02.contract_text, **TC02.form}
    created = replay_client.post("/v1/cases", json=body)
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert replay_client.patch(f"/v1/cases/{case_id}", json=TC02.confirm).status_code == 200

    streamed = events(replay_client.post(f"/v1/cases/{case_id}/analyze").text)
    names = [name for name, _ in streamed]
    assert names == ["retrieving", "calculating", "analysing", "critiquing", "writing", "done"]
    analysis = streamed[-1][1]
    assert analysis["total_aed"] == "6229.59"
    assert analysis["replay_label"] == demo_replay.LABEL
    assert not analysis["writer_failed"]

    pdf = replay_client.post(f"/v1/cases/{case_id}/complaint", json={})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert time.perf_counter() - started < 15


def test_other_stories_go_to_the_live_pipeline(replay_client: TestClient) -> None:
    body = {"language": "ur", "story": "میری تنخواہ تین مہینے سے نہیں ملی۔", **TC02.form}
    # The guard LLM has no replies: reaching it (the live path) raises for the intake stage.
    with pytest.raises(KeyError, match="intake"):
        replay_client.post("/v1/cases", json=body)
