
# Warehouse Inventory App — Streamlit Cloud Bundle (Option B)

Follow these steps to deploy on **Streamlit Community Cloud** using **Supabase Postgres** (plus optional Storage for images).

## 1) Supabase (Postgres)
- Create a new project at https://supabase.com
- Copy your Postgres connection string.
- Table is auto-created on first run (see `db.py`).

## 2) Supabase Storage (optional for images)
- Create a public bucket named `inventory-images` (or pick a name and set SUPABASE_BUCKET).
- The app uploads images and stores the public URL in the DB.

## 3) GitHub repo
- Add these files: `inventory_app.py`, `db.py`, `storage.py`, `requirements.txt`.
- (Optional) add your logo file named `AS logo shaded EASA and CAA.jpg`.

## 4) Streamlit Cloud deploy
- Connect the repo and set **Secrets**:
```
DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@HOST:5432/DBNAME"
SUPABASE_URL = "https://YOUR_PROJECT_ID.supabase.co"
SUPABASE_KEY = "YOUR_SERVICE_OR_ANON_KEY"
SUPABASE_BUCKET = "inventory-images"
```
`DATABASE_URL` required. The `SUPABASE_*` trio is optional (for persistent image uploads).

## 5) Use the app
- Receive Inventory, Inventory List & Search, Print Labels (Avery 5160), Scan to Pick, Inventory Audit, Export/Import.
