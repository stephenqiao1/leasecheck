"""End-to-end eval harness for the LeaseCheck review pipeline.

Ingests a labeled fixture lease directly through ``app.ingest`` (no HTTP),
runs ``app.review.review_document`` over its clauses, aligns each finding to a
ground-truth label by clause number, and reports detection + attribution
quality. See ``--help`` for options.
"""

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.embeddings import EMBED_MODEL
from app.ingest import extract_text, split_into_clauses, UnreadablePDF
from app.models import Document, Clause
from app.review import review_document, REVIEW_MODEL

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = EVAL_DIR / "sample_lease_ontario.pdf"
DEFAULT_KEY = EVAL_DIR / "sample_lease_answer_key.json"
RESULTS_DIR = EVAL_DIR / "results"

JURISDICTION = "ON"
DEFAULT_K = 4

CLAUSE_NUM_RE = re.compile(r"^\s*(\d+)\.")

POSITIVE = "violation"  # predicted/expected verdict treated as the positive class


class EvalError(Exception):
    """A fatal misalignment or integrity problem. Raised to fail loudly."""


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def ingest_and_persist(db, pdf_path: Path) -> Document:
    """Ingest the PDF through the real pipeline and persist Document + Clauses."""
    raw_text, page_count = extract_text(str(pdf_path))
    clause_dicts = split_into_clauses(raw_text)

    doc = Document(
        filename=pdf_path.name,
        jurisdiction=JURISDICTION,
        status="parsed",
        page_count=page_count,
        raw_text=raw_text,
    )
    db.add(doc)
    db.flush()
    for c in clause_dicts:
        db.add(Clause(document_id=doc.id, **c))
    db.commit()
    db.refresh(doc)
    return doc


def clause_number(clause: Clause) -> int | None:
    m = CLAUSE_NUM_RE.match(clause.text)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Answer key
# --------------------------------------------------------------------------- #
def load_answer_key(path: Path) -> dict:
    if not path.exists():
        raise EvalError(f"Answer key not found: {path}")
    with path.open() as f:
        key = json.load(f)

    for field in ("total_clauses", "violations", "labels"):
        if field not in key:
            raise EvalError(f"Answer key missing required field '{field}': {path}")

    labels = key["labels"]
    by_number: dict[int, dict] = {}
    for label in labels:
        for field in ("clause_number", "verdict", "rule_code"):
            if field not in label:
                raise EvalError(f"Answer-key label missing '{field}': {label!r}")
        num = label["clause_number"]
        if num in by_number:
            raise EvalError(f"Answer key has duplicate clause_number {num}")
        by_number[num] = label

    # Internal consistency of the key itself.
    if key["total_clauses"] != len(labels):
        raise EvalError(
            f"Answer key total_clauses={key['total_clauses']} but has {len(labels)} labels"
        )
    counted = sum(1 for l in labels if l["verdict"] == POSITIVE)
    if key["violations"] != counted:
        raise EvalError(
            f"Answer key violations={key['violations']} but {counted} labels are '{POSITIVE}'"
        )
    key["_by_number"] = by_number
    return key


# --------------------------------------------------------------------------- #
# Alignment — fail loudly on any gap
# --------------------------------------------------------------------------- #
def align(clauses: list[Clause], answer_key: dict) -> dict[int, Clause]:
    """Map ground-truth clause_number -> Clause. A misalignment is fatal."""
    missing = [c for c in clauses if clause_number(c) is None]
    if missing:
        preview = "\n".join(f"    ordinal {c.ordinal}: {c.text[:60]!r}" for c in missing)
        raise EvalError(
            f"{len(missing)} clause(s) have no leading number; cannot align:\n{preview}"
        )

    clause_by_number: dict[int, Clause] = {}
    for c in clauses:
        num = clause_number(c)
        if num in clause_by_number:
            raise EvalError(
                f"Duplicate clause number {num} across clauses "
                f"(ordinals {clause_by_number[num].ordinal} and {c.ordinal})"
            )
        clause_by_number[num] = c

    predicted = set(clause_by_number)
    expected = set(answer_key["_by_number"])
    if predicted != expected:
        only_pred = sorted(predicted - expected)
        only_key = sorted(expected - predicted)
        raise EvalError(
            "Clause numbers do not match the answer key.\n"
            f"    in document but not labeled: {only_pred}\n"
            f"    labeled but not in document: {only_key}"
        )
    return clause_by_number


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _safe_div(n: int, d: int) -> float:
    return n / d if d else 0.0


def evaluate(clause_by_number, finding_by_clause_id, answer_key) -> dict:
    records = []
    for num in sorted(clause_by_number):
        clause = clause_by_number[num]
        finding = finding_by_clause_id[clause.id]
        label = answer_key["_by_number"][num]

        expected_verdict = label["verdict"]
        predicted_verdict = finding.verdict
        expected_rule = label["rule_code"]
        predicted_rule = finding.rule.code if finding.rule else None

        exp_pos = expected_verdict == POSITIVE
        pred_pos = predicted_verdict == POSITIVE
        if exp_pos and pred_pos:
            outcome = "TP"
        elif not exp_pos and pred_pos:
            outcome = "FP"
        elif exp_pos and not pred_pos:
            outcome = "FN"
        else:
            outcome = "TN"

        rule_match = outcome == "TP" and predicted_rule == expected_rule

        records.append({
            "clause_number": num,
            "expected_verdict": expected_verdict,
            "predicted_verdict": predicted_verdict,
            "expected_rule_code": expected_rule,
            "predicted_rule_code": predicted_rule,
            "outcome": outcome,
            "rule_match": rule_match,
            "rationale": finding.rationale,
        })

    tp = sum(1 for r in records if r["outcome"] == "TP")
    fp = sum(1 for r in records if r["outcome"] == "FP")
    fn = sum(1 for r in records if r["outcome"] == "FN")
    tn = sum(1 for r in records if r["outcome"] == "TN")

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    accuracy = _safe_div(tp + tn, tp + fp + fn + tn)

    attr_correct = sum(1 for r in records if r["outcome"] == "TP" and r["rule_match"])
    attribution = _safe_div(attr_correct, tp)

    return {
        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "total": len(records)},
        "detection": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
        },
        "attribution": {"correct": attr_correct, "true_positives": tp, "accuracy": attribution},
        "clauses": records,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
BAR = "=" * 64
SUB = "-" * 64


def _fmt_rule(code: str | None) -> str:
    return code if code else "—"


def print_report(result: dict, config: dict) -> None:
    c = result["counts"]
    d = result["detection"]
    a = result["attribution"]

    print(BAR)
    print(" LeaseCheck review-pipeline eval")
    print(BAR)
    print(" config")
    print(f"   review model       {config['review_model']}")
    print(f"   embedding model    {config['embedding_model']}")
    print(f"   retrieval k        {config['retrieval_k']}")
    print(f"   jurisdiction       {config['jurisdiction']}")
    print(f"   clauses evaluated  {c['total']}")
    print(SUB)
    print(" detection  (verdict 'violation' = positive)")
    print(f"   precision   {d['precision']:.3f}")
    print(f"   recall      {d['recall']:.3f}")
    print(f"   f1          {d['f1']:.3f}")
    print(f"   accuracy    {d['accuracy']:.3f}")
    print(f"   TP {c['tp']}   FP {c['fp']}   FN {c['fn']}   TN {c['tn']}")
    print(SUB)
    print(" attribution  (correct rule_code among true positives)")
    print(f"   accuracy    {a['accuracy']:.3f}  ({a['correct']} / {a['true_positives']})")
    print(SUB)

    failures = [
        r for r in result["clauses"]
        if r["outcome"] in ("FP", "FN") or (r["outcome"] == "TP" and not r["rule_match"])
    ]
    if not failures:
        print(" failures   none — every clause classified and attributed correctly")
        print(BAR)
        return

    print(f" failures ({len(failures)})   [FP/FN = detection miss, RULE = wrong rule_code]")
    print(SUB)
    for r in failures:
        kind = "RULE" if r["outcome"] == "TP" else r["outcome"]
        print(
            f" #{r['clause_number']:<3} {kind:<4} "
            f"verdict: {r['expected_verdict']} → {r['predicted_verdict']}    "
            f"rule: {_fmt_rule(r['expected_rule_code'])} → {_fmt_rule(r['predicted_rule_code'])}"
        )
        print(f"      rationale: {r['rationale']}")
    print(BAR)


# --------------------------------------------------------------------------- #
# Persistence of results
# --------------------------------------------------------------------------- #
def write_results(
    result: dict,
    config: dict,
    inputs: dict,
    timestamp: datetime,
    run_index: int | None = None,
    multi: bool = False,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
    name = f"{stamp}-run{run_index}.json" if multi else f"{stamp}.json"
    out_path = RESULTS_DIR / name
    payload = {
        "timestamp": timestamp.isoformat(),
        "run_index": run_index,
        "config": config,
        "inputs": inputs,
        "counts": result["counts"],
        "detection": result["detection"],
        "attribution": result["attribution"],
        "clauses": result["clauses"],
    }
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return out_path


# --------------------------------------------------------------------------- #
# Aggregation across repeated runs
# --------------------------------------------------------------------------- #
def _mean_std(values: list[float]) -> dict:
    return {
        "mean": statistics.fmean(values),
        # Sample std (ddof=1); undefined for a single run, reported as 0.0.
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "values": values,
    }


def aggregate_runs(run_results: list[dict]) -> dict:
    metric_series = {
        "precision": [r["detection"]["precision"] for r in run_results],
        "recall": [r["detection"]["recall"] for r in run_results],
        "f1": [r["detection"]["f1"] for r in run_results],
        "attribution_accuracy": [r["attribution"]["accuracy"] for r in run_results],
    }
    metrics = {name: _mean_std(vals) for name, vals in metric_series.items()}

    # Per-clause behaviour across runs.
    by_clause: dict[int, dict] = {}
    for r in run_results:
        for rec in r["clauses"]:
            num = rec["clause_number"]
            slot = by_clause.setdefault(num, {
                "clause_number": num,
                "expected_verdict": rec["expected_verdict"],
                "expected_rule_code": rec["expected_rule_code"],
                "verdicts": [],
                "predicted_rule_codes": [],
            })
            slot["verdicts"].append(rec["predicted_verdict"])
            slot["predicted_rule_codes"].append(rec["predicted_rule_code"])

    unstable = []
    for num in sorted(by_clause):
        slot = by_clause[num]
        vcounts = Counter(slot["verdicts"])
        rcounts = Counter(slot["predicted_rule_codes"])
        verdict_unstable = len(vcounts) > 1
        rule_unstable = len(rcounts) > 1
        if verdict_unstable or rule_unstable:
            unstable.append({
                "clause_number": num,
                "expected_verdict": slot["expected_verdict"],
                "expected_rule_code": slot["expected_rule_code"],
                "verdict_unstable": verdict_unstable,
                "rule_unstable": rule_unstable,
                "verdict_distribution": dict(vcounts),
                "rule_code_distribution": {_fmt_rule(k): v for k, v in rcounts.items()},
            })

    stability = {
        "total_clauses": len(by_clause),
        "stable_clauses": len(by_clause) - len(unstable),
        "unstable_clauses": len(unstable),
    }
    return {"metrics": metrics, "stability": stability, "unstable": unstable}


def print_aggregate_report(aggregate: dict, config: dict, n_runs: int) -> None:
    m = aggregate["metrics"]
    s = aggregate["stability"]

    print(BAR)
    print(f" LeaseCheck review-pipeline eval — {n_runs} runs")
    print(BAR)
    print(" config")
    print(f"   review model       {config['review_model']}")
    print(f"   embedding model    {config['embedding_model']}")
    print(f"   retrieval k        {config['retrieval_k']}")
    print(f"   jurisdiction       {config['jurisdiction']}")
    print(f"   runs               {n_runs}")
    print(SUB)
    print(f" detection & attribution  (mean ± sample std over {n_runs} runs)")

    def line(label: str, key: str) -> None:
        d = m[key]
        vals = ", ".join(f"{v:.3f}" for v in d["values"])
        print(f"   {label:<12} {d['mean']:.3f} ± {d['std']:.3f}    [{vals}]")

    line("precision", "precision")
    line("recall", "recall")
    line("f1", "f1")
    line("attribution", "attribution_accuracy")
    print(SUB)
    print(" stability")
    print(f"   stable clauses     {s['stable_clauses']} / {s['total_clauses']}")
    print(f"   unstable clauses   {s['unstable_clauses']}")

    if aggregate["unstable"]:
        print(SUB)
        print(" unstable clauses  (classified or attributed differently across runs)")
        for u in aggregate["unstable"]:
            tags = []
            if u["verdict_unstable"]:
                tags.append("verdict")
            if u["rule_unstable"]:
                tags.append("rule")
            print(
                f"   #{u['clause_number']:<3} [{'+'.join(tags)}]  "
                f"expected {u['expected_verdict']} / {_fmt_rule(u['expected_rule_code'])}"
            )
            vd = "  ".join(f"{k}×{v}" for k, v in u["verdict_distribution"].items())
            print(f"        verdicts:   {vd}")
            if u["rule_unstable"]:
                rd = "  ".join(f"{k}×{v}" for k, v in u["rule_code_distribution"].items())
                print(f"        rule_codes: {rd}")
    print(BAR)


def write_aggregate(
    aggregate: dict,
    run_paths: list[Path],
    config: dict,
    inputs: dict,
    timestamp: datetime,
    n_runs: int,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = timestamp.strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = RESULTS_DIR / f"{stamp}-aggregate.json"
    payload = {
        "timestamp": timestamp.isoformat(),
        "config": config,
        "inputs": inputs,
        "runs": n_runs,
        "run_files": [p.name for p in run_paths],
        "metrics": aggregate["metrics"],
        "stability": aggregate["stability"],
        "unstable_clauses": aggregate["unstable"],
    }
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return out_path


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="fixture lease PDF")
    parser.add_argument("--answer-key", type=Path, default=DEFAULT_KEY, help="labeled answer key JSON")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="rules retrieved per clause")
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="repeat the review N times and report mean/std + unstable clauses (default: 1)",
    )
    parser.add_argument(
        "--keep-doc",
        action="store_true",
        help="leave the ingested Document in the DB (default: delete it afterward)",
    )
    args = parser.parse_args()

    if args.runs < 1:
        print("error: --runs must be >= 1", file=sys.stderr)
        return 2
    if settings.openai_api_key is None:
        print("error: OPENAI_API_KEY is not set — embeddings and review need it.", file=sys.stderr)
        return 2
    if not args.pdf.exists():
        print(f"error: fixture PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    # Load & validate the answer key before spending any API calls.
    try:
        answer_key = load_answer_key(args.answer_key)
    except EvalError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    timestamp = datetime.now(timezone.utc)
    config = {
        "review_model": REVIEW_MODEL,
        "embedding_model": EMBED_MODEL,
        "retrieval_k": args.k,
        "jurisdiction": JURISDICTION,
        "runs": args.runs,
    }

    db = SessionLocal()
    doc = None
    try:
        try:
            doc = ingest_and_persist(db, args.pdf)
        except UnreadablePDF as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        clauses = list(doc.clauses)
        if len(clauses) != answer_key["total_clauses"]:
            raise EvalError(
                f"ingested {len(clauses)} clauses but answer key expects "
                f"{answer_key['total_clauses']} — splitter/fixture mismatch"
            )

        # Fail loudly on misalignment *before* running the model. Ingestion and
        # alignment are deterministic, so they run once; only the review repeats.
        clause_by_number = align(clauses, answer_key)

        multi = args.runs > 1
        inputs = {
            "pdf": str(args.pdf),
            "answer_key": str(args.answer_key),
            "document_id": str(doc.id) if args.keep_doc else None,
            "runs": args.runs,
        }

        run_results = []
        for i in range(1, args.runs + 1):
            if multi:
                print(f" review run {i}/{args.runs} …", flush=True)
            findings = review_document(db, clauses, k=args.k)
            db.commit()
            finding_by_clause_id = {f.clause_id: f for f in findings}
            run_results.append(
                evaluate(clause_by_number, finding_by_clause_id, answer_key)
            )

        run_paths = [
            write_results(r, config, inputs, timestamp, run_index=i, multi=multi)
            for i, r in enumerate(run_results, start=1)
        ]

        if multi:
            aggregate = aggregate_runs(run_results)
            agg_path = write_aggregate(
                aggregate, run_paths, config, inputs, timestamp, args.runs
            )
            print_aggregate_report(aggregate, config, args.runs)
            print(f"\n wrote {len(run_paths)} run files + aggregate:")
            for p in run_paths:
                print(f"   {p}")
            print(f"   {agg_path}")
        else:
            print_report(run_results[0], config)
            print(f"\n wrote {run_paths[0]}")

        if args.keep_doc:
            print(f" kept document {doc.id} in the database")
        return 0

    except EvalError as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        return 1
    finally:
        if doc is not None and not args.keep_doc:
            db.delete(doc)  # cascades to clauses + findings
            db.commit()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
