# inventory_app.py - Streamlit Cloud + Postgres + optional Supabase Storage
import io
import os
import uuid
from datetime import datetime

import pandas as pd
from PIL import Image
import streamlit as st

from sqlalchemy import text

from db import get_engine, init_db
from storage import upload_image_and_get_url

from barcode import Code128
from barcode.writer import ImageWriter
import qrcode

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader

st.set_page_config(page_title="Warehouse Inventory (Cloud)", layout="wide")

LOGO_FILE = "AS logo shaded EASA and CAA.jpg"
if os.path.exists(LOGO_FILE):
    try:
        st.image(Image.open(LOGO_FILE), width=500)
    except Exception:
        pass

st.title("📦 Warehouse Inventory (Cloud)")

try:
    init_db()
except Exception as e:
    st.error(f"Database initialization failed: {e}")
    st.stop()

@st.cache_data(show_spinner=False)
def load_df():
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql("SELECT * FROM items ORDER BY created_at DESC", conn)
    return df

def refresh_data():
    load_df.clear()

def insert_item(payload: dict):
    eng = get_engine()
    cols = ", ".join(payload.keys())
    params = ", ".join([f":{k}" for k in payload.keys()])
    sql = f"INSERT INTO items ({cols}) VALUES ({params})"
    with eng.begin() as conn:
        conn.execute(text(sql), payload)
    refresh_data()

def update_item(item_id: str, updates: dict):
    if not updates: 
        return
    eng = get_engine()
    sets = ", ".join([f"{k}=:{k}" for k in updates.keys()])
    sql = f"UPDATE items SET {sets} WHERE id=:id"
    updates["id"] = item_id
    with eng.begin() as conn:
        conn.execute(text(sql), updates)
    refresh_data()

def update_quantity(item_id: str, new_qty: int):
    update_item(item_id, {"quantity": int(new_qty)})

def delete_item(item_id: str):
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM items WHERE id=:id"), {"id": item_id})
    refresh_data()

def generate_barcode_image_bytes(code_value: str) -> bytes:
    buf = io.BytesIO()
    Code128(code_value, writer=ImageWriter()).write(buf, options={"write_text": False})
    return buf.getvalue()

def generate_qr_image_bytes(code_value: str) -> bytes:
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(code_value)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

def draw_label(c, x, y, w, h, row):
    padding = 6
    text_left = x + padding
    text_top = y + h - padding

    c.setFont("Helvetica-Bold", 9)
    title = f"{(row.get('make') or '').upper()} {(row.get('model') or '')}"
    c.drawString(text_left, text_top - 12, title[:40])

    c.setFont("Helvetica", 8)
    pn = row.get('part_number') or ""
    c.drawString(text_left, text_top - 24, f"PN: {pn}")
    serial = row.get("serial_number") or ""
    if serial:
        c.drawString(text_left, text_top - 36, f"SN: {serial}")
    binloc = row.get("bin_location") or ""
    if binloc:
        c.drawString(text_left, text_top - 48, f"BIN: {binloc}")
    c.drawString(text_left, text_top - 60, f"Qty: {row.get('quantity', 1)}")

    code_value = row.get("code_value", "")
    code_type = row.get("code_type", "Barcode (Code128)")
    try:
        if code_type == "Barcode (Code128)":
            img_bytes = generate_barcode_image_bytes(code_value)
        else:
            img_bytes = generate_qr_image_bytes(code_value)
        img = Image.open(io.BytesIO(img_bytes))
        img_w, img_h = img.size
        code_box_w = w * 0.48
        code_box_h = h * 0.70
        scale = min(code_box_w / img_w, code_box_h / img_h)
        disp_w = img_w * scale
        disp_h = img_h * scale
        code_x = x + w - disp_w - 6
        code_y = y + (h - disp_h) / 2
        c.drawImage(ImageReader(img), code_x, code_y, width=disp_w, height=disp_h, preserveAspectRatio=True, mask='auto')
    except Exception:
        pass

    c.setFont("Helvetica", 7)
    c.drawString(text_left, y + 4, f"ID: {code_value}")

def labels_pdf_bytes(df: pd.DataFrame, labels_per_item: int = 1,
                     page_size=letter, cols=3, rows=10,
                     left_margin=0.1875*inch, top_margin=0.5*inch,
                     label_w=2.625*inch, label_h=1.0*inch,
                     h_spacing=0.125*inch, v_spacing=0.0*inch) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=page_size)

    col_positions = [left_margin + i*(label_w + h_spacing) for i in range(cols)]
    row_positions = [page_size[1] - top_margin - label_h - i*(label_h + v_spacing) for i in range(rows)]

    labels = []
    for _, row in df.iterrows():
        for _ in range(labels_per_item):
            labels.append(row)

    idx = 0
    for row in labels:
        col_idx = (idx % (cols*rows)) % cols
        row_idx = (idx % (cols*rows)) // cols
        x = col_positions[col_idx]
        y = row_positions[row_idx]
        draw_label(c, x, y, label_w, label_h, row)
        idx += 1
        if idx % (cols*rows) == 0:
            c.showPage()

    if idx % (cols*rows) != 0:
        c.showPage()
    c.save()
    out.seek(0)
    return out.read()

def save_photo_and_get_url(file):
    if file is None:
        return None
    try:
        raw = file.read()
        public_url = upload_image_and_get_url(raw, filename=f"{uuid.uuid4().hex}.jpg")
        if public_url:
            return public_url
        # fallback: local temp (non-persistent)
        tmp_dir = "images"
        os.makedirs(tmp_dir, exist_ok=True)
        path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.jpg")
        with open(path, "wb") as f:
            f.write(raw)
        return path
    except Exception:
        return None

with st.sidebar:
    st.header("Navigation")
    page = st.radio("Go to", ["Receive Inventory", "Inventory List & Search", "Print Labels", "Scan to Pick", "Perform Inventory Audit", "Export/Import"])
    st.caption("Streamlit Cloud + Postgres. Set secrets in the deployment settings.")

if page == "Receive Inventory":
    st.subheader("Receive Inventory")
    with st.form("receive_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            make = st.text_input("Make *")
            model = st.text_input("Model *")
            part_number = st.text_input("Part Number (optional)")
            serial_number = st.text_input("Serial Number (optional)")
            quantity = st.number_input("Quantity", min_value=1, step=1, value=1)
            bin_location = st.text_input("Bin Location *", placeholder="e.g., Aisle 1 / Bin B3")
        with cols[1]:
            code_type = st.selectbox("Code Type", ["Barcode (Code128)", "QR Code"], index=0)
            photo = st.file_uploader("Photo (JPG/PNG)", type=["jpg","jpeg","png"])
            notes = st.text_area("Notes (optional)")

        submitted = st.form_submit_button("Add to Inventory")
        if submitted:
            if not make or not model or not bin_location:
                st.error("Make, Model, and Bin Location are required.")
            else:
                item_id = str(uuid.uuid4())[:12]
                photo_url = save_photo_and_get_url(photo)
                payload = {
                    "id": item_id,
                    "make": make.strip(),
                    "model": model.strip(),
                    "part_number": (part_number.strip() or None),
                    "serial_number": (serial_number.strip() or None),
                    "quantity": int(quantity),
                    "photo_url": photo_url,
                    "code_type": code_type,
                    "code_value": item_id,
                    "bin_location": bin_location.strip(),
                    "notes": (notes.strip() or None),
                    "created_at": datetime.utcnow().isoformat(timespec="seconds")
                }
                insert_item(payload)
                st.success(f"Item added with ID: {item_id}")
                try:
                    img_bytes = generate_barcode_image_bytes(item_id) if code_type == "Barcode (Code128)" else generate_qr_image_bytes(item_id)
                    st.image(img_bytes, caption=f"{code_type} for {item_id}", width=260)
                except Exception:
                    pass

elif page == "Inventory List & Search":
    st.subheader("Inventory")
    df = load_df()
    filt_cols = st.columns(4)
    with filt_cols[0]:
        q = st.text_input("Search (Make/Model/PN/SN/ID/BIN/Notes)")
    with filt_cols[1]:
        make_f = st.text_input("Filter Make")
    with filt_cols[2]:
        model_f = st.text_input("Filter Model")
    with filt_cols[3]:
        part_f = st.text_input("Filter Part Number")

    if not df.empty:
        fdf = df.copy()
        if q:
            ql = q.lower()
            fdf = fdf[fdf.apply(lambda r: any(ql in str(r[c]).lower() for c in ["make","model","part_number","serial_number","id","bin_location","notes"]), axis=1)]
        if make_f:
            fdf = fdf[fdf["make"].str.contains(make_f, case=False, na=False)]
        if model_f:
            fdf = fdf[fdf["model"].str.contains(model_f, case=False, na=False)]
        if part_f:
            fdf = fdf[fdf["part_number"].str.contains(part_f, case=False, na=False)]

        from streamlit import column_config
        show_cols = ["id","make","model","part_number","serial_number","bin_location","quantity","created_at","photo_url"]
        rename = {"photo_url":"Photo"}
        img_col = column_config.ImageColumn("Photo", width="small")
        st.dataframe(fdf[show_cols].rename(columns=rename), use_container_width=True, column_config={"Photo": img_col})

        st.markdown("---")
        left, mid, right = st.columns([2,2,2])
        with left:
            st.subheader("Preview / Edit")
            ids = fdf["id"].tolist()
            if ids:
                sel_id = st.selectbox("Select Item ID", ids)
                row = fdf[fdf["id"]==sel_id].iloc[0].to_dict()
                if row.get("photo_url"):
                    try:
                        st.image(row["photo_url"], caption="Photo", use_column_width=True)
                    except Exception:
                        pass
                with st.form("edit_item"):
                    new_make = st.text_input("Make", row["make"] or "")
                    new_model = st.text_input("Model", row["model"] or "")
                    new_pn = st.text_input("Part Number (optional)", row.get("part_number") or "")
                    new_sn = st.text_input("Serial Number (optional)", row.get("serial_number") or "")
                    new_bin = st.text_input("Bin Location *", row.get("bin_location") or "")
                    new_qty = st.number_input("Quantity", min_value=0, value=int(row.get("quantity",1)))
                    new_notes = st.text_area("Notes", row.get("notes") or "")
                    saved = st.form_submit_button("Save changes")
                if saved:
                    if not new_make or not new_model or not new_bin:
                        st.error("Make, Model, and Bin Location are required.")
                    else:
                        updates = {
                            "make": new_make.strip(),
                            "model": new_model.strip(),
                            "part_number": (new_pn.strip() or None),
                            "serial_number": (new_sn.strip() or None),
                            "bin_location": new_bin.strip(),
                            "quantity": int(new_qty),
                            "notes": (new_notes.strip() or None),
                        }
                        update_item(sel_id, updates)
                        st.success("Item updated.")
        with mid:
            st.subheader("Adjust / Delete")
            ids2 = fdf["id"].tolist()
            if ids2:
                sel2 = st.selectbox("Select Item to Adjust/Delete", ids2, key="sel2")
                cur_qty = int(fdf.loc[fdf["id"]==sel2,"quantity"].iloc[0])
                new_qty2 = st.number_input("New Quantity", min_value=0, step=1, value=cur_qty)
                if st.button("Update Quantity"):
                    update_quantity(sel2, int(new_qty2))
                    st.success("Quantity updated.")
                if st.button("Delete Item"):
                    st.warning("Are you sure you want to delete this item? This cannot be undone.")
                    colA, colB = st.columns(2)
                    with colA:
                        if st.button("Yes, delete"):
                            delete_item(sel2)
                            st.success("Item deleted.")
                    with colB:
                        st.write("")
        with right:
            st.subheader("Quick Export")
            st.download_button(
                "Download CSV of current view",
                data=fdf.to_csv(index=False).encode("utf-8"),
                file_name="inventory_filtered_export.csv",
                mime="text/csv",
            )

    else:
        st.info("No items yet. Add some on the Receive page.")

elif page == "Print Labels":
    st.subheader("Print Labels")
    df = load_df()
    if df.empty:
        st.info("No items yet.")
    else:
        multi = st.multiselect("Select items to print", df["id"].tolist(), help="Choose one or more item IDs.")
        copies = st.number_input("Labels per selected item", min_value=1, step=1, value=1)
        st.caption("Avery 5160 layout by default. Adjust below if needed.")
        with st.expander("Advanced layout options"):
            cols = st.columns(3)
            with cols[0]:
                cols_per_row = st.number_input("Columns", min_value=1, value=3, step=1)
                rows_per_page = st.number_input("Rows", min_value=1, value=10, step=1)
            with cols[1]:
                label_w_in = st.number_input("Label width (in)", min_value=0.5, value=2.625, step=0.125)
                label_h_in = st.number_input("Label height (in)", min_value=0.5, value=1.0, step=0.125)
            with cols[2]:
                left_margin_in = st.number_input("Left margin (in)", min_value=0.0, value=0.1875, step=0.0625)
                top_margin_in = st.number_input("Top margin (in)", min_value=0.0, value=0.5, step=0.0625)
                h_spacing_in = st.number_input("Horizontal spacing (in)", min_value=0.0, value=0.125, step=0.0625)
                v_spacing_in = st.number_input("Vertical spacing (in)", min_value=0.0, value=0.0, step=0.0625)

        if st.button("Generate PDF"):
            if not multi:
                st.error("Select at least one item.")
            else:
                use_df = df[df["id"].isin(multi)].copy()
                from reportlab.lib.pagesizes import letter
                pdf_bytes = labels_pdf_bytes(
                    use_df, labels_per_item=int(copies),
                    page_size=letter, cols=int(cols_per_row), rows=int(rows_per_page),
                    left_margin=left_margin_in*inch, top_margin=top_margin_in*inch,
                    label_w=label_w_in*inch, label_h=label_h_in*inch,
                    h_spacing=h_spacing_in*inch, v_spacing=v_spacing_in*inch
                )
                st.download_button("Download labels PDF", data=pdf_bytes, file_name="labels.pdf", mime="application/pdf")
                st.success("PDF generated.")

elif page == "Scan to Pick":
    st.subheader("Scan to Pick")
    st.caption("Click the box and scan the label. Most scanners send Enter, which submits the form.")
    df = load_df()

    if "scan_result" not in st.session_state:
        st.session_state.scan_result = None
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False

    with st.form("scan_form", clear_on_submit=True):
        scan_code = st.text_input("Scan or type Item ID", key="scan_input")
        submitted = st.form_submit_button("Process Scan")
    if submitted and scan_code:
        st.session_state.scan_result = scan_code.strip()

    code = st.session_state.get("scan_result")
    if code:
        match = df[df["id"] == code]
        if match.empty:
            st.error(f"No item found with ID: {code}")
        else:
            row = match.iloc[0].to_dict()
            st.success(f"Found item ID {code}: {row['make']} {row['model']} (BIN {row.get('bin_location','')})")
            c1, c2 = st.columns([1,1])
            with c1:
                st.write("**Item Details**")
                st.json({k: row.get(k) for k in ["make","model","part_number","serial_number","bin_location","quantity","notes","created_at"]})
                if row.get("photo_url"):
                    try:
                        st.image(row["photo_url"], caption="Photo", width=300)
                    except Exception:
                        pass
            with c2:
                st.write("**Actions**")
                with st.form("edit_from_scan"):
                    new_make = st.text_input("Make", row["make"] or "")
                    new_model = st.text_input("Model", row["model"] or "")
                    new_pn = st.text_input("Part Number (optional)", row.get("part_number") or "")
                    new_sn = st.text_input("Serial Number (optional)", row.get("serial_number") or "")
                    new_bin = st.text_input("Bin Location *", row.get("bin_location") or "")
                    new_qty = st.number_input("Quantity", min_value=0, value=int(row.get("quantity",1)))
                    new_notes = st.text_area("Notes", row.get("notes") or "")
                    ok = st.form_submit_button("Save changes")
                if ok:
                    if not new_make or not new_model or not new_bin:
                        st.error("Make, Model, and Bin Location are required.")
                    else:
                        updates = {
                            "make": new_make.strip(),
                            "model": new_model.strip(),
                            "part_number": (new_pn.strip() or None),
                            "serial_number": (new_sn.strip() or None),
                            "bin_location": new_bin.strip(),
                            "quantity": int(new_qty),
                            "notes": (new_notes.strip() or None),
                        }
                        update_item(code, updates)
                        st.success("Item updated.")

                colA, colB = st.columns(2)
                with colA:
                    if st.button("Remove part from inventory"):
                        st.session_state.confirm_delete = True
                if st.session_state.get("confirm_delete"):
                    st.warning("Are you sure you want to remove this part? This cannot be undone.")
                    cY, cN = st.columns(2)
                    with cY:
                        if st.button("Yes, remove"):
                            delete_item(code)
                            st.session_state.scan_result = None
                            st.session_state.confirm_delete = False
                            st.success("Part removed.")
                    with cN:
                        if st.button("Cancel"):
                            st.session_state.confirm_delete = False

        if st.button("Scan another"):
            st.session_state.scan_result = None

elif page == "Perform Inventory Audit":
    st.subheader("Inventory Audit")
    st.caption("Start an audit, then scan each item once. Use Download to save results.")
    df = load_df()

    if "audit_started" not in st.session_state:
        st.session_state.audit_started = False
    if "audit_scanned" not in st.session_state:
        st.session_state.audit_scanned = set()

    if not st.session_state.audit_started:
        if st.button("Start Audit Session"):
            st.session_state.audit_started = True
            st.session_state.audit_scanned = set()
    else:
        colx, coly = st.columns([2,1])
        with colx:
            with st.form("audit_form", clear_on_submit=True):
                code = st.text_input("Scan or type Item ID", key="audit_scan")
                scanned = st.form_submit_button("Record Scan")
            if scanned and code:
                code = code.strip()
                if code in set(df["id"].tolist()):
                    st.session_state.audit_scanned.add(code)
                else:
                    st.error(f"Unknown ID: {code}")

        with coly:
            st.metric("Verified", len(st.session_state.audit_scanned))
            st.metric("Total Items", len(df))
            st.metric("Remaining", max(0, len(df) - len(st.session_state.audit_scanned)))

        verified_df = df[df["id"].isin(st.session_state.audit_scanned)].copy()
        missing_df = df[~df["id"].isin(st.session_state.audit_scanned)].copy()

        st.markdown("### ✅ Verified Items")
        st.dataframe(verified_df[["id","make","model","bin_location","quantity","created_at"]], use_container_width=True)

        st.markdown("### ❌ Not Yet Verified")
        st.dataframe(missing_df[["id","make","model","bin_location","quantity","created_at"]], use_container_width=True)

        st.markdown("---")
        results = []
        now = datetime.utcnow().isoformat(timespec="seconds")
        for _, r in df.iterrows():
            results.append({
                "id": r["id"],
                "make": r["make"],
                "model": r["model"],
                "bin_location": r.get("bin_location"),
                "quantity": r.get("quantity"),
                "verified": r["id"] in st.session_state.audit_scanned,
                "timestamp": now,
            })
        out = pd.DataFrame(results)
        st.download_button(
            "Download Audit Results (CSV)",
            data=out.to_csv(index=False).encode("utf-8"),
            file_name=f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        if st.button("End Audit Session"):
            st.session_state.audit_started = False
            st.session_state.audit_scanned = set()
            st.success("Audit session ended.")

elif page == "Export/Import":
    st.subheader("Export / Import")
    df = load_df()
    if not df.empty:
        st.download_button("Download CSV Export (All Items)", data=df.to_csv(index=False).encode("utf-8"), file_name="inventory_export.csv", mime="text/csv")
    else:
        st.info("No items to export yet.")

    st.markdown("---")
    st.subheader("Bulk Import from CSV")
    st.caption("CSV must have columns: make, model, part_number (optional), serial_number (optional), quantity, bin_location*. ID, code, and timestamps are auto-generated.")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            imp = pd.read_csv(up).fillna("")
            required = {"make","model","bin_location"}
            if not required.issubset(set(imp.columns)):
                missing = sorted(list(required - set(imp.columns)))
                st.error(f"Missing required columns: {missing}")
            else:
                added = 0
                for _, row in imp.iterrows():
                    item_id = str(uuid.uuid4())[:12]
                    payload = {
                        "id": item_id,
                        "make": str(row.get("make","")).strip(),
                        "model": str(row.get("model","")).strip(),
                        "part_number": (str(row.get("part_number","")).strip() or None),
                        "serial_number": (str(row.get("serial_number","")).strip() or None),
                        "quantity": int(row.get("quantity", 1) or 1),
                        "photo_url": None,
                        "code_type": "Barcode (Code128)",
                        "code_value": item_id,
                        "bin_location": str(row.get("bin_location","")).strip(),
                        "notes": (str(row.get("notes","")).strip() or None),
                        "created_at": datetime.utcnow().isoformat(timespec="seconds")
                    }
                    if payload["make"] and payload["model"] and payload["bin_location"]:
                        insert_item(payload)
                        added += 1
                st.success(f"Imported {added} items.")
        except Exception as e:
            st.error(f"Import failed: {e}")
