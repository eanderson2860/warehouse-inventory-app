# storage.py - Supabase Storage integration for images (DEBUG)

import os
from typing import Optional

import streamlit as st

_supabase = None


def _get_supabase():
    """
    Initialize and cache the Supabase client.
    Emits DEBUG info to the Streamlit app.
    """
    global _supabase
    if _supabase is not None:
        return _supabase

    # ---- Read URL / KEY from Streamlit secrets or env vars ----
    secrets = st.secrets if hasattr(st, "secrets") else {}
    url = secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

    st.write("DEBUG(storage): Has SUPABASE_URL?", bool(url))
    st.write("DEBUG(storage): Has SUPABASE_KEY?", bool(key))

    if not url or not key:
        st.error("DEBUG(storage): Missing SUPABASE_URL or SUPABASE_KEY")
        return None

    # ---- Import Supabase client ----
    try:
        from supabase import create_client
    except Exception as e:
        st.error(f"DEBUG(storage): Could not import supabase client: {e}")
        return None

    # ---- Create client ----
    try:
        _supabase = create_client(url, key)
        st.write("DEBUG(storage): Supabase client created successfully.")
        return _supabase
    except Exception as e:
        st.error(f"DEBUG(storage): Error creating Supabase client: {e}")
        return None


def upload_image_and_get_url(
    content: bytes,
    filename: str,
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    Upload image bytes to Supabase Storage and return a public URL.
    Emits DEBUG info to the Streamlit app.
    Returns None if Supabase is not configured or if upload fails.
    """
    sb = _get_supabase()
    if sb is None:
        st.error("DEBUG(storage): Supabase client is None; upload aborted.")
        return None

    secrets = st.secrets if hasattr(st, "secrets") else {}
    bucket = (
        bucket
        or secrets.get("SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_BUCKET")
        or "inventory-images"
    )

    st.write("DEBUG(storage): Using bucket:", bucket)
    path = filename

    try:
        # IMPORTANT: file_options values must be strings, not booleans
        sb.storage.from_(bucket).upload(
            path=path,
            file=content,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true",  # string, not True
            },
        )
        public_url = sb.storage.from_(bucket).get_public_url(path)
        st.write("DEBUG(storage): get_public_url returned:", public_url)
        return public_url
    except Exception as e:
        st.error(f"DEBUG(storage): Supabase upload error: {e}")
        return None
