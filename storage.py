# storage.py - Supabase Storage integration for images (DEBUG, simplified)

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

    secrets = st.secrets if hasattr(st, "secrets") else {}

    # Read URL / KEY from top-level secrets or env vars
    url = secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")

    st.write("DEBUG(storage): Has SUPABASE_URL?", bool(url))
    st.write("DEBUG(storage): Has SUPABASE_KEY?", bool(key))

    if not url or not key:
        st.error("DEBUG(storage): Missing SUPABASE_URL or SUPABASE_KEY")
        return None

    # Import and create client
    try:
        from supabase import create_client
    except Exception as e:
        st.error(f"DEBUG(storage): Could not import supabase client: {e}")
        return None

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
    Uses a minimal upload() call to avoid client bugs.
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

    # ---- Upload file (minimal args; no file_options) ----
    try:
        upload_response = sb.storage.from_(bucket).upload(path, content)
        st.write("DEBUG(storage): upload() response:", upload_response)
    except Exception as e:
        st.error(f"DEBUG(storage): Supabase upload error: {e}")
        return None

    # ---- Get public URL ----
    try:
        public_url = sb.storage.from_(bucket).get_public_url(path)
        st.write("DEBUG(storage): get_public_url returned:", public_url)
        return public_url or None
    except Exception as e:
        st.error(f"DEBUG(storage): get_public_url error: {e}")
        return None
