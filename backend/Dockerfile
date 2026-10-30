# Build from the repo root (see render.yaml and docker-compose.yml) so the law data can be copied in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    LAW_DATA_DIR=/app/data/law

# Pango and HarfBuzz for WeasyPrint (complaint PDF); the fonts ship in haqqi/pdf/fonts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.8.*

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/haqqi ./haqqi
RUN uv sync --frozen --no-dev

# Law text and the Law Pack: retrieval and citation checks read them at runtime.
COPY data/law/*.json ./data/law/
RUN python -c "from haqqi.rag.lawdata import load_chunks, load_law_pack; load_law_pack(); assert load_chunks()"
# DEMO_REPLAY's recorded Gemma 4 run of TC-02 (off unless DEMO_REPLAY=1).
COPY eval/demo/tc02_gemma_run1.json ./eval/demo/
ENV DEMO_REPLAY_FILE=/app/eval/demo/tc02_gemma_run1.json
# Fail the build if the PDF stack can't render Arabic.
RUN python -m haqqi.pdf.smoke /tmp/smoke.pdf && rm /tmp/smoke.pdf

# Hosts such as Render set PORT; 8000 is the local default.
ENV PORT=8000
EXPOSE 8000
RUN useradd --create-home --uid 1000 app
USER app
CMD ["sh", "-c", "uvicorn haqqi.api.main:app --host 0.0.0.0 --port ${PORT}"]
