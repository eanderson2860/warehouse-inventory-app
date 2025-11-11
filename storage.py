# storage.py - Optional Supabase Storage integration for images
import os
from typing import Optional

_supabase = None

def _get_supabase():
    global _supabase
    if _supabase is not None:
        return _supabase
    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        secrets = {}
    url = (secrets.get("SUPABASE_URL") if secrets else None) or os.environ.get("SUPABASE_URL")
    key = (secrets.get("SUPABASE_KEY") if secrets else None) or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _supabase = create_client(url, key)
        return _supabase
    except Exception:
        return None

def upload_image_and_get_url(content: bytes, filename: str, bucket: Optional[str] = None) -> Optional[str]:
    sb = _get_supabase()
    if sb is None:
        return None
    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        secrets = {}
    bucket = bucket or (secrets.get("SUPABASE_BUCKET") if secrets else None) or os.environ.get("SUPABASE_BUCKET") or "inventory-images"
    path = filename
    try:
        sb.storage.from_(bucket).upload(path=path, file=content, file_options={"content-type": "image/jpeg", "upsert": True})
        public_url = sb.storage.from_(bucket).get_public_url(path)
        return public_url
    except Exception:
        return None
