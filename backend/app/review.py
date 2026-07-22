from typing import Literal
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Clause, Rule, Finding
from app.retrieval import retrieve_rules

REVIEW_MODEL = "gpt-5.6"

_client = None

def _get_client() -> OpenAI:
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client

# The schema the model is FORCED to return (constrained decoding).
class ClauseVerdict(BaseModel):
    verdict: Literal["ok", "violation", "unclear"]
    rule_code: str | None
    rationale: str

SYSTEM_PROMPT = """You are a residential tenancy compliance reviewer for Ontario, Canada.
You are given one clause from a lease and a short list of candidate legal rules.
Decide whether the clause violates any of the provided rules.

- Judge the clause ONLY against the candidate rules provided. Do not rely on outside legal knowledge.
- If the clause violates one of the candidate rules, return verdict "violation" and set rule_code to that rule's exact code.
- If the clause is consistent with the rules, or none of them apply, return verdict "ok" and rule_code null.
- If you genuinely cannot tell from the provided rules, return verdict "unclear" and rule_code null.
- Keep the rationale to one or two sentences, naming the rule code when relevant."""

def _build_user_prompt(clause_text: str, rules: list[Rule]) -> str:
    rule_lines = "\n".join(f"- {r.code}: {r.title}. {r.description}" for r in rules)
    return f"Candidate rules:\n{rule_lines}\n\nClause to review:\n\"{clause_text}\""

def review_clause(db: Session, clause: Clause, k: int = 4) -> Finding:
    rules = retrieve_rules(db, clause.text, clause.document.jurisdiction, k=k)
    user_prompt = _build_user_prompt(clause.text, rules)

    completion = _get_client().chat.completions.parse(
        model=REVIEW_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=ClauseVerdict,
    )
    message = completion.choices[0].message
    if message.refusal:
        result = ClauseVerdict(verdict="unclear", rule_code=None,
                               rationale=f"Model refused: {message.refusal}")
    else:
        result = message.parsed

    # Only accept a rule_code that was actually in the candidate set (anti-hallucination guard).
    rule = next((r for r in rules if r.code == result.rule_code), None) if result.rule_code else None

    finding = Finding(
        clause_id=clause.id,
        rule_id=rule.id if rule else None,
        verdict=result.verdict,
        rationale=result.rationale,
    )
    db.add(finding)
    return finding

def review_document(db: Session, clauses: list[Clause], k: int = 4) -> list[Finding]:
    return [review_clause(db, clause, k=k) for clause in clauses]