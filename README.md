# LeaseCheck

LeaseCheck is a rental-lease compliance auditor. You upload a residential lease
PDF, and it flags clauses that appear to violate landlord-tenant law, citing the
specific rule each clause breaks and explaining why.

The problem it addresses: standard-form leases frequently contain clauses that
are unenforceable or outright illegal under residential tenancy law — non-refundable
deposits, blanket no-pet or no-guest bans, illegal entry terms, NSF fees above
the statutory cap. A tenant or housing worker reading the lease cannot be expected
to know which clauses are void. LeaseCheck reads the lease clause by clause,
retrieves the rules that plausibly apply, and asks a language model for a grounded
verdict against those rules only.

The current implementation is scoped to **Ontario, Canada** (the Residential
Tenancies Act) with a corpus of **12 rules**, and has been evaluated against a
**single synthetic labeled lease**. See [Evaluation](#evaluation) and
[Limitations](#limitations) — the accuracy numbers reflect that narrow scope and
should not be read as validated real-world performance.

## Architecture

The pipeline has four stages. A lease moves left to right; each stage's output is
persisted in Postgres.

```
PDF ─▶ ingestion ─▶ retrieval (pgvector) ─▶ LLM review ─▶ reviewer UI
       clauses        candidate rules        findings       annotated document
```

### 1. Ingestion

`backend/app/ingest.py` extracts text with `pypdf` and splits it into clauses.
The splitter prefers numbered-clause markers (`^\d+\.` at line start) and falls
back to paragraph splitting when a document is not numbered. Each clause is stored
with its ordinal and character offsets. A `Document` row plus its `Clause` rows are
persisted; scanned/image-only PDFs (no extractable text) are rejected.

### 2. Rules corpus + pgvector retrieval

The rules corpus lives in `backend/scripts/seed_rules.py`: 12 Ontario RTA
provisions, each with a `code`, `title`, and plain-language `description`. Seeding
embeds `"{title}. {description}"` with OpenAI `text-embedding-3-small`
(1536-dimensional) and stores the vector in a pgvector `Vector(1536)` column.

At review time, `backend/app/retrieval.py` embeds the clause text and selects the
`k` nearest rules by cosine distance, scoped to the document's jurisdiction. `k`
is configurable; the default is 4.

### 3. LLM review with structured outputs

`backend/app/review.py` reviews each clause against its retrieved candidate rules.
It calls the OpenAI Chat Completions API (`gpt-5.6`) with a Pydantic
`response_format`, so the model is constrained to return exactly:

```
verdict:    "ok" | "violation" | "unclear"
rule_code:  string | null
rationale:  string
```

The prompt instructs the model to judge the clause **only** against the provided
candidate rules, not outside legal knowledge. Two guards constrain the output: the
verdict enum is enforced by constrained decoding, and a returned `rule_code` is
accepted only if it was actually in the candidate set (an anti-hallucination
check — a code the model invents is dropped and the finding is stored with no rule
link). Each result is persisted as a `Finding`.

### 4. Reviewer UI

`frontend/` is a Next.js (App Router) application. `frontend/app/documents/[id]`
renders the lease as a marked-up legal document: clause text in a reading column,
findings as margin annotations aligned to their clause, and a colored rail marking
each clause's verdict (violation / unclear / ok). A reviewer can accept or dismiss
each finding; a header counter tracks pending violations. The server component
fetches a single `/documents/{id}/review-view` payload; interaction is handled
client-side with optimistic updates.

### Data model

`backend/app/models.py` defines four tables: `Document` → `Clause` (one-to-many),
`Rule` (with the embedding vector), and `Finding` (links a clause to at most one
rule, with verdict, rationale, and a triage status).

## Quickstart

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node.js, and an OpenAI
API key.

**1. Start Postgres (pgvector) via Docker Compose.**

```bash
docker compose -f infra/docker-compose.yml up -d
```

This runs `pgvector/pgvector:pg16` on `localhost:5432` with database/user/password
`leasecheck` / `leasecheck` / `localdev`.

**2. Configure the backend.** Create `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://leasecheck:localdev@localhost:5432/leasecheck
OPENAI_API_KEY=sk-...
```

**3. Apply migrations** (enables the pgvector extension and creates the tables):

```bash
cd backend
uv run alembic upgrade head
```

**4. Seed the rules corpus** (embeds the 12 rules; requires the OpenAI key):

```bash
uv run python -m scripts.seed_rules
```

**5. Run the API:**

```bash
uv run uvicorn app.main:app --reload --port 8000
```

**6. Run the frontend.** Create `frontend/.env.local` with
`NEXT_PUBLIC_API_URL=http://localhost:8000`, then:

```bash
cd frontend
npm install
npm run dev
```

The API listens on `:8000` (CORS allows `http://localhost:3000`); the UI on `:3000`.
Upload a lease via `POST /documents`, trigger `POST /documents/{id}/review`, then
open `http://localhost:3000/documents/{id}`.

## Evaluation

The eval harness is the part of this project worth scrutinizing. LLM review is
non-deterministic and easy to fool yourself about, so the goal here is a
reproducible, labeled measurement rather than a demo.

### The labeled fixture

`backend/eval/sample_lease_ontario.pdf` is a synthetic Ontario lease with a
hand-written answer key, `backend/eval/sample_lease_answer_key.json`. The key
labels every clause with a ground-truth verdict and, for violations, the rule code
that should be cited:

- **24 clauses total**
- **12 labeled violations**, each mapped to one of the 12 seeded rule codes
- **12 clauses labeled `ok`**

`backend/eval/run_eval.py` ingests the fixture through the real `app.ingest`
pipeline (not over HTTP), runs the real `review_document`, aligns each finding to
its label by parsing the leading clause number, and fails loudly if any clause
number is missing or unmatched (a silent misalignment would invalidate every
number). Results are written to `backend/eval/results/`.

### Metrics

Detection treats verdict **`violation` as the positive class**; `ok` and `unclear`
are both negative. From the per-clause confusion counts (TP/FP/FN/TN):

- **Precision** = TP / (TP + FP) — of clauses flagged as violations, how many truly are.
- **Recall** = TP / (TP + FN) — of true violations, how many were caught.
- **F1** = harmonic mean of precision and recall.
- **Attribution accuracy** — of the true positives, the fraction that cited the
  *correct* `rule_code`. This is separate from detection: catching that a clause is
  a violation but citing the wrong rule counts as a detection success and an
  attribution failure.

Because outputs vary between runs, `--runs N` repeats the review N times and
reports the mean and sample standard deviation of each metric, plus any clause
whose verdict or cited rule changed across runs.

### Results

Model `gpt-5.6`, embeddings `text-embedding-3-small`, 3 runs per configuration.
The numbers below are copied directly from the aggregate JSONs in
`backend/eval/results/` (timestamps `2026-07-22T04:29–04:34Z`).

Retrieval-depth ablation (`--k`), mean ± sample standard deviation over 3 runs:

| k | Precision | Recall | F1 | Attribution | Unstable clauses |
|---|-----------|--------|-----|-------------|------------------|
| 2 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0 / 24 |
| 4 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0 / 24 |
| 8 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0 / 24 |

Every run at every `k` produced 12 TP, 0 FP, 0 FN, 12 TN, with the correct rule
cited on all 12 true positives. Variance across runs was zero on this fixture, and
no clause was classified or attributed differently between runs.

### Reading the results honestly

The scores are perfect, and that is a statement about the fixture as much as the
system. Two facts explain why `k` makes no difference: for all 12 violation
clauses the correct rule is the **rank-1** nearest neighbor by embedding distance,
so even `k=2` always contains it (no recall lost at low `k`); and with only 12
rules in the corpus, `k=8` feeds the model two-thirds of the corpus as candidates,
which it correctly ignores (no precision or attribution lost at high `k`). This
fixture therefore cannot discriminate between these `k` values — a flat line, not
a tuning result.

A perfect score also means the harness's failure-reporting and instability paths
were exercised structurally but never against an actual miss. The eval demonstrates
that the pipeline is correct and reproducible on an in-distribution synthetic case;
it does not demonstrate real-world accuracy.

## Limitations

- **One synthetic document.** All reported numbers come from a single hand-authored
  lease with a hand-authored answer key. The violations are cleanly injected and
  map one-to-one onto known rules; real leases are messier, and the sample size (24
  clauses) is far too small to estimate accuracy with any confidence.
- **12 rules.** The corpus is a small subset of the Residential Tenancies Act.
  Clauses that violate rules not in the corpus cannot be caught, and the retrieval
  step is trivial when the corpus is this small.
- **One jurisdiction.** Ontario only. Nothing about the labels, rules, or prompt
  generalizes to other provinces or countries without new corpora and fixtures.
- **Answer key is not authoritative law.** The ground-truth labels are a
  reasonable reading of the RTA, not legal advice or a court's determination.
- **Not legal advice.** LeaseCheck is a triage aid. Its output should be verified
  against primary sources and, where it matters, a qualified professional.

To make the evaluation meaningful, the corpus and fixtures would need to grow: more
rules (so retrieval depth actually matters and some gold rules rank below the top
result), multiple real leases, and cases where the correct answer is genuinely
ambiguous.
