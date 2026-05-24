# app/database.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1) Allow Docker env vars to win.
# 2) For local dev, load backend.env or .env if they exist (without overriding real env).
root = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(root, "backend.env"), override=False)
load_dotenv(os.path.join(root, ".env"), override=False)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set (env or backend.env/.env).")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import app.models  # noqa: F401
Base.metadata.create_all(bind=engine)
