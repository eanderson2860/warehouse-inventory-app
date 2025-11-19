# storage.py - Supabase Storage integration for images using direct HTTP

import os
from typing import Optional

import streamlit as st

try:
    import requests
except ImportError:
    requests = None


def _get_supabase_config():
    """
    Read Supabase URL, API key, and bucket name from Streamlit secrets or env vars.
    """
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
    Upload image bytes directly to Supabase Storage via HTTP and
    return a public URL. Returns None if upload fails.
    """
    if requests is None:
        st.error(
            "Requests library not available. "
            "Add 'requests' to your requirements.txt for image uploads."
        )
        return None

    url, key, default_bucket = _get_supabase_config()
    if not url or not key:
        # Supabase not configured; fail quietly so the app still works without photos.
        st.warning("Supabase URL or KEY not configured; skipping photo upload.")
        return None

    bucket = bucket or default_bucket
    path = filename

    # Example:
    #   upload endpoint:  https://<project>.supabase.co/storage/v1/object/<bucket>/<path>
    #   public URL:       https://<project>.supabase.co/storage/v1/object/public/<bucket>/<path>
    upload_endpoint = f"{url.rstrip('/')}/storage/v1/object/{bucket}/{path}"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "image/jpeg",
        # allow overwriting same filename if needed
        "x-upsert": "true",
    }

    try:
        resp = requests.post(upload_endpoint, headers=headers, data=content)
    except Exception as e:
        st.error(f"DEBUG(storage): HTTP error talking to Supabase: {e}")
        return None

    if not (200 <= resp.status_code < 300):
        st.error(
            f"DEBUG(storage): Upload failed. Status {resp.status_code}, "
            f"body: {resp.text[:200]}"
        )
        return None

    # Construct public URL (bucket must be public in Supabase)
    public_url = f"{url.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"
    st.write("DEBUG(storage): Public URL:", public_url)
    return public_url
