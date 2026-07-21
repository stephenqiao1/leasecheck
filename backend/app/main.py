import os
import shutil
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import engine, get_db
from app.models import Document, Clause
from app.ingest import extract_text, split_into_clauses

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
    # 1. Save the uploaded file to disk
    dest = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)

    # 2. Extract text and split into clauses
    raw_text, page_count = extract_text(dest)
    clause_dicts = split_into_clauses(raw_text)

    # 3. Persist the document, then its clauses, in one transaction
    doc = Document(
        filename=file.filename,
        jurisdiction=jurisdiction,
        status="parsed",
        page_count=page_count,
        raw_text=raw_text,
    )
    db.add(doc)
    db.flush()  # assigns doc.id without committing yet

    for c in clause_dicts:
        db.add(Clause(document_id=doc.id, **c))

    db.commit()
    return {
        "document_id": str(doc.id),
        "page_count": page_count,
        "clause_count": len(clause_dicts),
        "status": doc.status,
    }

@app.get("/documents/{document_id}/clauses")
def list_clauses(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": document_id,
        "filename": doc.filename,
        "clauses": [
            {"ordinal": c.ordinal, "text": c.text,
             "char_start": c.char_start, "char_end": c.char_end}
            for c in doc.clauses
        ],
    }