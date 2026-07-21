from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text

class Settings(BaseSettings):
    database_url: str
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
engine = create_engine(settings.database_url)

app = FastAPI(title="LeaseCheck API")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db-check")
def db_check():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS ok")).scalar()
    return {"db": "reachable", "result": result}
