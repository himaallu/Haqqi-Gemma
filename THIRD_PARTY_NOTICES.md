# Third-party notices

The MIT licence in `LICENSE` covers Haqqi's own code. These parts keep their own terms:

| What | Where | Terms |
| --- | --- | --- |
| Noto fonts (Naskh Arabic, Nastaliq Urdu, Sans, Devanagari, Malayalam, Bengali) | `backend/haqqi/pdf/fonts/` | SIL Open Font License 1.1, see `backend/haqqi/pdf/fonts/OFL.txt` |
| Noto fonts in the web app (self-hosted by `next/font`) | `frontend/` | SIL Open Font License 1.1 |
| UAE law text (Federal Decree-Law No. 33 of 2021, Cabinet Resolution No. 1 of 2022) | `data/law/` | Official public legislation from uaelegislation.gov.ae; sources and dates in `data/law/SOURCES.md` |
| Gemma 4 model | Called over Google's API, not shipped here | The Gemma model licence published by Google (ai.google.dev/gemma) |
| npm and Python dependencies | `frontend/package.json`, `backend/pyproject.toml` | Each package's own licence |
