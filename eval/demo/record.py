"""Record a case on the live model for DEMO_REPLAY → eval/demo/<out>.json.

Usage (from backend/, local database with the BGE-M3 law index, GEMINI_API_KEY set):
    PYTHONPATH=.. uv run python -m eval.demo.record                  # TC-02, Urdu
    PYTHONPATH=.. uv run python -m eval.demo.record --english-pitch  # the /demo English story

The English pitch story is frontend/components/demo/data.ts AYESHA_STORY (TC-02's facts in English),
which the /demo page's "Fired without notice" example sends.

Runs the API in-process (create → confirm → analyze → complaint PDF, as eval.language_check does)
and keeps each stage's checked model reply and the retrieved law ids. Writes nothing if the run
fails or the Writer was skipped.
"""

import argparse
import json
import sys
from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from eval.cases_io import load_cases
from eval.language_check import run
from haqqi import demo_replay
from haqqi.api import cases
from haqqi.api.main import create_app
from haqqi.config import get_settings
from haqqi.llm.client import LLMClient

CASE = "TC-02"
# frontend/components/demo/data.ts AYESHA_STORY: keep the two in sync, or the replay won't match.
ENGLISH_PITCH_STORY = (
    "I worked as a cashier in a supermarket in Abu Dhabi, not in a free zone, from 1 June 2024. "
    "On 20 September my manager told me my job ends today. They gave me no notice. My contract "
    "says 30 days' notice. My basic salary is 2,000 dirhams and my total salary is 3,000."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--english-pitch", action="store_true", help="the /demo English story")
    args = parser.parse_args()
    settings = get_settings()
    llm = demo_replay.RecordingLLM(LLMClient.from_settings(settings))
    retrieved: list[dict[str, Any]] = []
    live_retrieve = cases.retrieve  # type: ignore[attr-defined]

    def recording_retrieve(*args: Any, **kwargs: Any) -> Any:
        chunks = live_retrieve(*args, **kwargs)
        retrieved[:] = [{"id": c.id, "source": c.source} for c in chunks]
        return chunks

    cases.retrieve = recording_retrieve  # type: ignore[attr-defined]
    app = create_app()
    app.dependency_overrides[cases.get_llm] = lambda: llm
    case = next(c for c in load_cases() if c.id == CASE)
    out = demo_replay.RECORDINGS_DIR / "tc02_gemma_run1.json"
    if args.english_pitch:
        case = case.model_copy(update={"language": "en", "story": ENGLISH_PITCH_STORY})
        out = demo_replay.RECORDINGS_DIR / "tc02_en_pitch_gemma.json"
    with TestClient(app) as client:
        result = run(case, client)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if "error" in result or result.get("writer_failed") or not retrieved:
        print("not recorded: the run failed or skipped the Writer", file=sys.stderr)
        return 1
    recording = {
        "note": "Model replies and retrieved law from a live run, replayed by haqqi/demo_replay.py",
        "case": CASE,
        "recorded_on": date.today().isoformat(),
        "models": [settings.gemini_model, *settings.gemini_fallback_models],
        "language": case.language,
        "story": case.story,
        "calls": llm.calls,
        "retrieved": retrieved,
        "live_result": result,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recording, ensure_ascii=False, indent=1) + "\n")
    print(f"recorded {len(llm.calls)} calls → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
