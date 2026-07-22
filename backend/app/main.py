import os
import shutil
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.models import Document, Clause, Rule
from app.ingest import extract_text, split_into_clauses, UnreadablePDF
from app.embeddings import embed_one

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="LeaseCheck API")

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