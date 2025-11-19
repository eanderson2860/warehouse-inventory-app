# storage.py - Supabase Storage integration for images (production)

import os
from typing import Optional

import requests
import streamlit as st


def _get_supabase_config():
    """Read Supabase URL, API key, and bucket name from Streamlit secrets or env vars."""
    secrets = st.secrets if hasattr(st, "secrets") else {}

    url = secrets.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or os.environ.get("SUPABASE_KEY")
    bucket = (
        secrets.get("SUPABASE_BUCKET")
        or os.environ.get("SUPABASE_BUCKET")
        or "inventory-images"
    )

    return url, key, bucket


def upload_image_and_get_url(
    content: bytes,
    filename: str,
    bucket: Optional[str] = None,
) -> Optional[str]:
    """
    Upload image bytes to Supabase Storage via HTTP and return a public URL.
    Returns None if Supabase is not configured or if upload fails.
    """
    url, key, default_bucket = _get_supabase_config()
    if not url or not key:
        # Supabase not configured; caller can fall back to local storage
        return None

    bucket = bucket or default_bucket
    path = filename

    # Upload endpoint:
    #   https://<project>.supabase.co/storage/v1/object/<bucket>/<path>
    upload_endpoint = f"{url.rstrip('/')}/storage/v1/object/{bucket}/{path}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",  # allow overwriting if same filename is reused
    }

    try:
        resp = requests.post(upload_endpoint, headers=headers, data=content)
    except Exception:
        return None

    if not (200 <= resp.status_code < 300):
        # Upload failed; do not raise, just signal failure
        return None

    # Public URL (bucket must be public in Supabase)
    public_url = f"{url.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"
    return public_url
