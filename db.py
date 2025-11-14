# db.py - SQLAlchemy engine for Postgres (Streamlit Cloud friendly, no psycopg2)

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
import streamlit as st

_engine: Engine | None = None

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        secrets = st.secrets

        # Read simple pieces from Streamlit Secrets
        user = secrets.get("DB_USER", "postgres")
        password = secrets["DB_PASSWORD"]          # required
        host = secrets["DB_HOST"]                  # required
        port = int(secrets.get("DB_PORT", 5432))
        dbname = secrets.get("DB_NAME", "postgres")

        # Build a proper URL for the psycopg v3 driver
        url = URL.create(
            "postgresql+psycopg",   # <-- this forces psycopg v3, NOT psycopg2
            username=user,
            password=password,
            host=host,
            port=port,
            database=dbname,
            query={"sslmode": "require"},
        )

        _engine = create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            future=True,
        )
    return _engine

def init_db():
    eng = get_engine()
    with eng.begin() as conn:
        # Create table with all new fields for fresh installs
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
            purchase_price NUMERIC(10, 2),
            repair_cost NUMERIC(10, 2),
            sale_price NUMERIC(10, 2),
            category TEXT,
            sold BOOLEAN NOT NULL DEFAULT FALSE,
            requested_by TEXT,
            request_status TEXT,
            created_at TEXT NOT NULL
        );
        """))

        # Migrate existing DBs: add missing columns if they don't exist
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(10, 2);
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS repair_cost NUMERIC(10, 2);
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS sale_price NUMERIC(10, 2);
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS category TEXT;
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS sold BOOLEAN NOT NULL DEFAULT FALSE;
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS requested_by TEXT;
        """))
        conn.execute(text("""
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS request_status TEXT;
        """))
