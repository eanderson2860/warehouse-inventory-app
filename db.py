# db.py - SQLAlchemy engine for Postgres (Streamlit Cloud friendly)
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

try:
    import streamlit as st
    _secrets = st.secrets
except Exception:
    _secrets = {}

DATABASE_URL = (
    (_secrets.get("DATABASE_URL") if _secrets else None)
    or os.environ.get("DATABASE_URL")
)

_engine = None

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set. Add it to Streamlit Secrets or env.")
        _engine = create_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            future=True,
        )
    return _engine

def init_db():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            make TEXT NOT NULL,
            model TEXT NOT NULL,
            part_number TEXT,
            serial_number TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            photo_url TEXT,
            code_type TEXT NOT NULL,
            code_value TEXT NOT NULL,
            bin_location TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        """))
