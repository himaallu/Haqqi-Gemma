# Haqqi (حقّي, "my right")

Haqqi helps blue-collar workers in the UAE find out, in their own language:
- whether their employer broke the labour law;
- what they are owed;
- how to file a formal complaint with MOHRE, in Arabic.

A worker tells their story by voice or text. Haqqi answers with the rights that were likely broken, each citing an
article of the law, an itemised claim from a deterministic calculator, and a ready-to-file Arabic complaint PDF with a
translation alongside.

**Live (original Haqqi, still on Gemini Flash):** https://haqqi-ai.vercel.app

## Hacktoberfest Hack Day Dubai (30 Oct 2026)

This repo is built for Hacktoberfest Hack Day Dubai x Legesher. It is a copy of my
[Haqqi project](https://github.com/himaallu/Haqqi-AI), with its full history, so everything before today's commits was
built for Haqqi. What changed today:

- **Open-weight Gemma 4 is now the only model.** Every LLM step (intake, analyst, critic, revision, writer) runs on
  `gemma-4-26b-a4b-it` through Google's OpenAI-compatible Gemini API endpoint, with no fallback model and no K2
  (`gemma-4-31b-it` was dropped: on 30 Oct it returned 500s and timed out on every step). A 5xx or timeout is retried
  twice on the same model (after 2 s, then 5 s); calls time out after 60 s, the Writer's after 120 s. If the Writer
  still can't be reached, the checked findings and amounts are shown with a "Try again" notice.
- **Demo replay (`DEMO_REPLAY=1`, off by default).** The TC-02 (Urdu) story answers from a recorded Gemma 4 run
  (`eval/demo/tc02_gemma_run1.json`, 30 Oct 2026) with no model call and no network: routing, the calculator, the
  citation checks and the PDF still run live on the recorded replies, the progress stages stream with 1–3 s pauses,
  and the results page says "Replay of a recorded Gemma 4 run (30 Oct 2026)". Any other story runs live. Re-record
  with `cd backend && PYTHONPATH=.. uv run python -m eval.demo.record`. The client now sends the Gemini-only `reasoning_effort` field to
  Gemini models only.
- **Open source:** an MIT licence (`LICENSE`) for Haqqi's code. Fonts stay under the SIL OFL, and the other terms are
  in `THIRD_PARTY_NOTICES.md`.

The evaluation scores below come from the original Haqqi runs (K2 and Gemini Flash). They have not been re-run on Gemma 4.

<p align="center"><img src="docs/demo.gif" width="300" alt="Haqqi on a phone, in Urdu: choose a language, tell the story, confirm the facts, watch the checks run, read the result, download the Arabic complaint"></p>

<sub>One case in Urdu, from real screenshots (`docs/screens/make_demo_gif.py`). A screen recording comes with the demo video.</sub>

## The problem

MOHRE settles almost every labour dispute that reaches it. In H1 2026 it recorded about 188,000 disputes and settled
98.6% of them without court
([WAM](https://www.wam.ae/en/article/c1kxr4e-mohre-resolves-986-labour-disputes-amicably-2026)). It also handled about
9.43 million consultation and complaint contacts in 2025
([MOHRE](https://mohre.gov.ae/en/media-center/news/9/3/2026/mohre-successfully-settles-98-percent-of-labour-disputes-in-2025)).

The hard part is getting there with a clear, correct claim. Low-wage migrant workers face three barriers:
- **Language:** the law and the complaint are in Arabic or English.
- **Legal knowledge:** which rights apply, which articles were broken, and what is owed.
- **Power:** a vague or wrong claim is easy to dismiss.

> MOHRE settles 98.6% of disputes. Haqqi helps the workers who never get as far as filing one.

## What it does

1. **Choose a language.** English, Hindi, Urdu, Malayalam, Bengali, Tagalog, Nepali or Arabic.
2. **Tell the story** by voice or text.
3. **Confirm the facts** Haqqi read from it: emirate, dates, wages, notice, leave. Anything missing is asked for.
4. **See the verdict.** Each likely violation is shown with the article it breaks, and the law text one tap away.
5. **See the claim.** Unpaid wages, notice pay, gratuity, leave and deductions, each with its formula.
6. **Get next steps:** where to file, the time limit, and the documents to gather.
7. **Download the complaint:** a formal Arabic letter to MOHRE with the worker's language alongside.

Cases outside the federal law get a referral instead of a verdict: DIFC/ADGM, other free zones, and domestic workers.
When Haqqi is not confident, it says so and points to MOHRE (80084) rather than guessing.

## Architecture

```mermaid
flowchart TD
    W([Worker on a phone]) -->|voice| STT[Whisper speech-to-text<br/>Cloudflare Workers AI]
    W -->|text| UI
    STT --> UI[Next.js web app<br/>Vercel]
    UI -->|REST + live progress| API[FastAPI service<br/>Render]
    API --> IN[Intake agent<br/>facts from the story]:::llm
    IN --> RT{Routing<br/>code}
    RT -->|DIFC / ADGM / free zone / domestic| REF[Referral + MOHRE 80084]
    RT -->|wage or start date missing| ASK[Ask the worker]
    RT -->|ready| CF[Worker confirms the facts]
    CF --> RET[Hybrid law search<br/>BGE-M3 vectors + full text, RRF,<br/>plus the issue's Law Pack]
    CF --> CALC[Claim calculator<br/>deterministic Python]
    RET --> AN[Analyst agent<br/>findings with clause ids]:::llm
    CALC --> AN
    AN --> CHK[Citation check<br/>code drops any clause not retrieved]
    CHK --> CR[Critic agent]:::llm
    CR -->|problems| RV[One revision]:::llm
    RV --> CHK2[Citation check again]
    CR -->|pass| WR
    CHK2 --> WR[Writer agent<br/>plain explanation + letter facts]:::llm
    WR --> PDF[Arabic complaint PDF<br/>WeasyPrint, amounts filled by code]
    DB[(Supabase Postgres<br/>pgvector law index, cases<br/>7-day purge)] --- RET
    DB --- API
    classDef llm fill:#fde7c8,stroke:#c77700,color:#222
```

The tinted steps call an LLM: open-weight Gemma 4 (`gemma-4-26b-a4b-it`) through Google's Gemini API. K2 Horizon
(IFM) can still be added as a fallback by setting `K2_API_KEY`. Everything else is
plain code, so no amount or article reaches the worker unchecked.

**Trust rules (enforced in code, see `CLAUDE.md`):**
- **Money** is computed only in `backend/haqqi/core/calculator.py`. The LLM writes `[[AMOUNT_n]]` tokens, and code
  fills them and rejects any other figure.
- **Every finding cites a clause id from the retrieved law.** Code drops any other citation, and the quote shown comes
  from our law text, not the model.
- **The worker's story is untrusted data**, fenced in delimiters. Prompt-injection cases are part of the evaluation.
- **Every LLM reply is parsed into a Pydantic model.** Bad output gets one correction retry, then a clear error.
- **Logs never hold story text, names, phone or ID numbers** (`backend/haqqi/logs.py`).

**Stack (all free tiers):**

| Part | Choice |
| --- | --- |
| Frontend | Next.js (App Router), TypeScript, Tailwind, shadcn/ui, pnpm, Vercel |
| Backend | Python 3.12, FastAPI, Pydantic v2, Docker on Render |
| Database | Supabase Postgres with pgvector and Arabic/English full-text search; pg_cron deletes cases after 7 days |
| Law | Federal Decree-Law 33/2021 (as amended) and Cabinet Resolution 1/2022, English and Arabic, one chunk per clause (`data/law/`) |
| Embeddings, speech | BGE-M3 and Whisper large-v3-turbo on Cloudflare Workers AI |
| LLM | Gemma 4 (26B A4B) on Google's free API tier; K2 Horizon optional. Gemini Flash models still work via `GEMINI_MODEL` |
| Tracing | Langfuse via OpenTelemetry: stage, model, timing and tokens per LLM call, never content |
| PDF | WeasyPrint with Noto Naskh Arabic and the Noto font for each worker language |

## Evaluation

These are the PRD metrics on 50 hand-labelled cases (`eval/cases.jsonl`), in all 8 languages. The cases include
referrals, missing information, prompt injection and seeded bad citations, and every expected amount is worked out by
hand in `eval/CASES.md`. Run with `make eval` (`eval/run_eval.py`); history is in `eval/CHANGELOG.md`. 40 cases ran
on K2 and 10 on the free Gemini models that production uses.

| Metric | Score | Target |
| --- | --- | --- |
| Outcome accuracy (analyse / refer / ask for info) | 100% | ≥ 95% |
| Issue detection | 95% | ≥ 85% |
| Retrieval hit@5 | 92% | ≥ 90% |
| Citations cited (from the retrieved law) | 100% | 100% |
| Citations supported (hand labels) | 97% | ≥ 90% |
| Critic catch rate (seeded bad citations) | 100% (2/2) | ≥ 90% |
| Calculator correctness | 100% (40/40) | 100% |
| Injection resistance | 100% (2/2) | 100% |
| Latency p95: Gemini (production) / K2 | 32 s / 292 s | < 90 s |

The calculator check also runs on every pull request without an LLM (`make eval-offline`).

## Run it locally

You need Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 22 with pnpm.

```bash
cp .env.example .env    # fill in the keys; never commit .env
make dev                # Postgres + backend (:8000) + frontend (:3000)
cd backend && DATABASE_URL=postgresql://haqqi:haqqi@localhost:5432/haqqi \
  uv run alembic upgrade head && uv run python -m haqqi.ingest   # law index (make db)
```

| Command | What it does |
| --- | --- |
| `make test` | Backend (pytest) and frontend (vitest) unit tests, no network |
| `make test-live` | Tests against a local database (its own `haqqi_test`) and the real APIs |
| `make lint` | ruff, mypy (strict), eslint, tsc |
| `make eval-offline` | Calculator vs the hand-worked cases, no LLM (runs in CI) |
| `make eval` | The full evaluation (K2 by default; `EVAL_ARGS="--provider gemini"`) |

Keys: `GEMINI_API_KEY` for Gemma 4 (`K2_API_KEY` optional), and `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` with
`EMBEDDER=cloudflare` for search and voice. Tests use a fake embedder and need no keys. `DEMO_REPLAY=1` runs the
TC-02 (Urdu) case from a recorded Gemma 4 run with no model or network (see the Hack Day notes above). Deploying to Vercel, Render and
Supabase is covered in [`docs/DEPLOY.md`](docs/DEPLOY.md).

```
backend/haqqi/   api/ (routes, limits) · agents/ (intake, analysis, writer) · core/ (calculator, routing)
                 rag/ (parse, ingest, retrieval, prompts) · pdf/ (complaint letter) · llm/ (client)
frontend/        Next.js app: language picker, story, confirm form, progress, results, complaint
data/law/        Law text (EN + AR) and the Law Pack, with sources
eval/            50 cases, hand-worked claims, runner, metrics, changelog
legacy/n8n/      The hackathon workflow (v0)
docs/            PRD, implementation plan, deploy guide, reviews, screenshots
```

## From n8n to code

Haqqi started as a one-day build for the **n8n Dubai Hackathon "Automate with K2 Horizon"** (25 Sep 2026), where it
placed in the **top 4 of 400+**. That version is a 31-node n8n workflow, kept in
[`legacy/n8n/`](legacy/n8n/) as v0.

| Kept from the hackathon | Changed in the rebuild |
| --- | --- |
| Four agents: Intake → Analyst → Critic (one revision) → Writer | A typed Python service and a real web app instead of n8n nodes |
| The Law Pack of 10 topics | Retrieval over the full law and executive regulations, English and Arabic, with article-level citations |
| A deterministic calculator | Ported to Python, with whole-day service counting, part-time and unpaid-absence rules, and hand-worked tests |
| Out-of-scope and need-info routes | Smarter referrals (DIFC/ADGM vs other free zones), a confirm step, and a "not sure" route |
| 22 test cases, including injection and a seeded bad citation | A 50-case evaluation with 8 metrics; voice input; an Arabic PDF; CI; log redaction; rate limits |

## Privacy and limits

- **Legal information, not legal advice.** MOHRE decides; every page and the PDF give the MOHRE number, 80084.
- **The story is processed by Google (Gemma 4 on the Gemini API free tier)**, which may use the text to improve its products. Workers
  are told not to include names, phone numbers, passport, Emirates ID or labour card numbers.
- **Cases are deleted after 7 days.** The name, labour card and employer typed for the complaint are printed into the
  PDF and never stored.
- **Mainland private-sector cases only.** Others get a referral.

Progress, decisions and open items are tracked in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
Still open:
- an Arabic reader's sign-off on the complaint;
- native-speaker review of the translations;
- error reporting (Sentry, deferred);
- the 90-second demo video.

## Licence

MIT, copyright 2026 Himasri Allu (`LICENSE`). Third-party fonts, law text and dependencies keep their own terms
(`THIRD_PARTY_NOTICES.md`).
