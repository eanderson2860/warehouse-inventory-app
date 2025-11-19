# storage.py - Supabase Storage integration for images
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

    # Support BOTH nested section ["supabase"] AND top-level keys
    sb_conf = secrets.get("supabase", {}) if secrets else {}
    url = (
        sb_conf.get("url")
        or secrets.get("SUPABASE_URL", None)
        or os.environ.get("SUPABASE_URL")
    )
    key = (
        sb_conf.get("key")
        or secrets.get("SUPABASE_KEY", None)
        or os.environ.get("SUPABASE_KEY")
    )

    if not url or not key:
        return None

    try:
        from supabase import create_client
        _supabase = create_client(url, key)
        return _supabase
    except Exception as e:
        print("Supabase initialization error:", e)
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

    # Support BOTH nested and top-level bucket settings
    sb_conf = secrets.get("supabase", {})
    bucket = (
        bucket
        or sb_conf.get("bucket")
        or secrets.get("SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_BUCKET")
        or "inventory-images"
    )

    path = filename

    try:
        sb.storage.from_(bucket).upload(
            path=path,
            file=content,
            file_options={
                "content-type": "image/jpeg",
                "upsert": True,
            }
        )
        public_url = sb.storage.from_(bucket).get_public_url(path)
        return public_url
    except Exception as e:
        print("Supabase upload error:", e)
        return None
