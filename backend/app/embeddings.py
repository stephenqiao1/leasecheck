from openai import OpenAI
from app.config import settings

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

_client = None

def _get_client() -> OpenAI:
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client

def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in a single API call."""
    resp = _get_client().embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]

def embed_one(text: str) -> list[float]:
    return embed([text])[0]
