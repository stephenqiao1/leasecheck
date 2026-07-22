from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Rule
from app.embeddings import embed_one

def retrieve_rules(db: Session, text: str, jurisdiction: str, k: int = 4) -> list[Rule]:
    """Return the k rules whose embeddings are closest to the given text."""
    query_vec = embed_one(text)
    distance = Rule.embedding.cosine_distance(query_vec)
    stmt = (
        select(Rule)
        .where(Rule.jurisdiction == jurisdiction)
        .order_by(distance)
        .limit(k)
    )
    return list(db.scalars(stmt).all())