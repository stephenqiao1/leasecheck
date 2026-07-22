import os
import shutil
from typing import Literal

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.models import Document, Clause, Rule, Finding
from app.ingest import extract_text, split_into_clauses, UnreadablePDF
from app.embeddings import embed_one
from app.review import review_document

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="LeaseCheck API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db-check")
def db_check():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS ok")).scalar()
    return {"db": "reachable", "result": result}

@app.post("/documents")
def upload_document(
    jurisdiction: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    dest = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        raw_text, page_count = extract_text(dest)
    except UnreadablePDF as e:
        raise HTTPException(status_code=400, detail=str(e))

    clause_dicts = split_into_clauses(raw_text)
    doc = Document(filename=file.filename, jurisdiction=jurisdiction,
                   status="parsed", page_count=page_count, raw_text=raw_text)
    db.add(doc)
    db.flush()
    for c in clause_dicts:
        db.add(Clause(document_id=doc.id, **c))
    db.commit()
    return {"document_id": str(doc.id), "page_count": page_count,
            "clause_count": len(clause_dicts), "status": doc.status}

@app.get("/documents/{document_id}/clauses")
def list_clauses(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": document_id,
        "filename": doc.filename,
        "clauses": [
            {"id": str(c.id), "ordinal": c.ordinal, "text": c.text,
             "char_start": c.char_start, "char_end": c.char_end}
            for c in doc.clauses
        ],
    }

@app.get("/clauses/{clause_id}/relevant-rules")
def relevant_rules(clause_id: str, k: int = 3, db: Session = Depends(get_db)):
    clause = db.get(Clause, clause_id)
    if clause is None:
        raise HTTPException(status_code=404, detail="Clause not found")

    query_vec = embed_one(clause.text)
    distance = Rule.embedding.cosine_distance(query_vec).label("distance")
    stmt = (
        select(Rule, distance)
        .where(Rule.jurisdiction == clause.document.jurisdiction)
        .order_by(distance)
        .limit(k)
    )
    rows = db.execute(stmt).all()
    return {
        "clause_ordinal": clause.ordinal,
        "matches": [
            {"code": r.code, "title": r.title, "similarity": round(1 - dist, 3)}
            for r, dist in rows
        ],
    }

@app.post("/documents/{document_id}/review")
def review_document_endpoint(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Clear any prior findings so re-running is idempotent
    for clause in doc.clauses:
        for f in list(clause.findings):
            db.delete(f)
    db.flush()

    findings = review_document(db, list(doc.clauses))
    doc.status = "reviewed"
    db.commit()

    violations = sum(1 for f in findings if f.verdict == "violation")
    return {"document_id": document_id, "clauses_reviewed": len(findings),
            "violations": violations, "status": doc.status}

@app.get("/documents/{document_id}/findings")
def list_findings(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    results = []
    for clause in doc.clauses:
        for f in clause.findings:
            results.append({
                "clause_ordinal": clause.ordinal,
                "clause_preview": clause.text[:100],
                "verdict": f.verdict,
                "rule_code": f.rule.code if f.rule else None,
                "rationale": f.rationale,
                "status": f.status,
            })
    return {"document_id": document_id, "findings": results}

@app.get("/documents/{document_id}/review-view")
def review_view(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    clauses = []
    violation_count = 0
    for clause in doc.clauses:
        finding = clause.findings[0] if clause.findings else None
        if finding is not None and finding.verdict == "violation":
            violation_count += 1
        clauses.append({
            "id": str(clause.id),
            "ordinal": clause.ordinal,
            "text": clause.text,
            "finding": {
                "id": str(finding.id),
                "verdict": finding.verdict,
                "rule_code": finding.rule.code if finding.rule else None,
                "rule_title": finding.rule.title if finding.rule else None,
                "rationale": finding.rationale,
                "status": finding.status,
            } if finding is not None else None,
        })

    return {
        "document_id": str(doc.id),
        "filename": doc.filename,
        "jurisdiction": doc.jurisdiction,
        "status": doc.status,
        "clause_count": len(doc.clauses),
        "violation_count": violation_count,
        "clauses": clauses,
    }

class FindingStatusUpdate(BaseModel):
    status: Literal["accepted", "dismissed", "pending"]

@app.patch("/findings/{finding_id}")
def update_finding(finding_id: str, body: FindingStatusUpdate, db: Session = Depends(get_db)):
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.status = body.status
    db.commit()
    return {
        "id": str(finding.id),
        "clause_id": str(finding.clause_id),
        "verdict": finding.verdict,
        "rule_code": finding.rule.code if finding.rule else None,
        "rationale": finding.rationale,
        "status": finding.status,
    }