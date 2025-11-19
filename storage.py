# storage.py - Supabase Storage integration for images

import os
from typing import Optional

import streamlit as st

_supabase = None


def _get_supabase():
    """
    Initialize and cache the Supabase client using URL/KEY from
    Streamlit secrets or environment variables.
    """
    global _supabase
    if _supabase is not None:
        return _supabase

    # Read from Streamlit secrets or env vars
    secrets = st.secrets if hasattr(st, "secrets") else {}
    url = secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        # If either is missing, we silently return None so the app can still run
        return None

    try:
        from supabase import create_client
        _supabase = create_client(url, key)
        return _supabase
    except Exception:
        # If client creation fails, just disable Supabase for this run
        return None


def upload_image_and_get_url(
    content: bytes,
    filename: str,
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    Upload image bytes to Supabase Storage and return a public URL.
    Returns None if Supabase is not configured or if upload fails.
    """
    sb = _get_supabase()
    if sb is None:
        return None

    secrets = st.secrets if hasattr(st, "secrets") else {}
    bucket = (
        bucket
        or secrets.get("SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_BUCKET")
        or "inventory-images"
    )

    path = filename

    try:
        # IMPORTANT: all file_options values must be strings
        sb.storage.from_(bucket).upload(
            path=path,
            file=content,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true",  # must be string, not boolean
            },
        )
        public_url = sb.storage.from_(bucket).get_public_url(path)
        return public_url
    except Exception:
        # On any error, just return None so caller can handle gracefully
        return None
