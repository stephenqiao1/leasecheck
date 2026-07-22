# LeaseCheck

Rental-lease compliance auditor. Upload a lease PDF, split it into clauses, retrieve the
most relevant jurisdiction rules per clause, and get an LLM verdict stored as a Finding.

## Monorepo layout
- `backend/` — FastAPI + SQLAlchemy + Alembic + Postgres (pgvector), managed with **uv**.
  Run: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
- `infra/` — `docker-compose.yml` running Postgres on `:5432`
- `frontend/` — empty; about to become a Next.js app

## Backend modules (`backend/app/`)
- `models.py` — SQLAlchemy models (Document, Clause, Rule, Finding)
- `ingest.py` — PDF → text → clauses (`extract_text`, `split_into_clauses`, `UnreadablePDF`)
- `embeddings.py` — `embed_one` (OpenAI embeddings, 1536-dim)
- `retrieval.py` — pgvector cosine-distance similarity search
- `review.py` — `review_document`; LLM verdicts via OpenAI structured outputs
- `main.py` — FastAPI endpoints
- `db.py` — engine + `get_db` session dependency

## Pipeline
upload PDF → split into clauses → per-clause retrieve relevant rules (by jurisdiction,
pgvector) → LLM verdict (`ok`/`violation`/`unclear` + rule_code + rationale) → store Finding.

## Schema (Postgres, UUID primary keys)
- **Document** — filename, jurisdiction, status (`uploaded`→`parsed`→`reviewed`), page_count,
  raw_text, created_at; has many Clauses (ordered by ordinal, cascade delete).
- **Clause** — document_id (FK), ordinal, text, char_start/char_end, created_at;
  has many Findings.
- **Rule** — jurisdiction, code, title, description, `embedding` Vector(1536), created_at.
- **Finding** — clause_id (FK), rule_id (nullable FK, SET NULL), verdict (`ok`/`violation`/
  `unclear`), rationale, status (`pending`/`accepted`/`dismissed`), created_at.

## Endpoints (`main.py`)
- `GET  /health` — liveness
- `GET  /db-check` — verifies DB connectivity (`SELECT 1`)
- `POST /documents` — form: `jurisdiction` + `file` (PDF); ingests and splits into clauses,
  returns document_id, page_count, clause_count, status
- `GET  /documents/{id}/clauses` — list clauses for a document
- `GET  /clauses/{id}/relevant-rules?k=3` — top-k rules by pgvector similarity, scoped to the
  document's jurisdiction
- `POST /documents/{id}/review` — clears prior findings (idempotent), runs LLM review over all
  clauses, marks document `reviewed`; returns clauses_reviewed + violation count
- `GET  /documents/{id}/findings` — list findings (verdict, rule_code, rationale, status)

## Notes
- Uploaded files are saved to `backend/uploads/`.
- Requires an OpenAI API key in the environment for embeddings and review.
