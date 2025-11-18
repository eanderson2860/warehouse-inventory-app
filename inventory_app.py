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

# ----------------------------
# Database init
# ----------------------------
try:
    init_db()
except Exception as e:
    st.error(f"Database initialization failed: {e}")
    st.stop()


# ----------------------------
# Auth / Roles
# ----------------------------
def require_login():
    """Simple in-app role login based on Streamlit secrets."""
    if "role" not in st.session_state:
        st.session_state["role"] = None
    if "user_name" not in st.session_state:
        st.session_state["user_name"] = None

    roles_conf = st.secrets.get("roles", None)

    # If no roles configured, default to Admin with full access
    if roles_conf is None:
        if st.session_state["role"] is None:
            st.info("Roles are not configured in secrets. Running as Admin with full access.")
            st.session_state["role"] = "Admin"
            st.session_state["user_name"] = "Admin"
        return

    # Already logged in
    if st.session_state["role"] is not None:
        with st.sidebar:
            st.write(f"Logged in as: **{st.session_state['user_name']}** ({st.session_state['role']})")
            if st.button("Log out"):
                st.session_state["role"] = None
                st.session_state["user_name"] = None
                st.rerun()
        return

    # Login form
    st.subheader("User Login")
    name = st.text_input("Your name")
    role = st.selectbox("Role", ["Admin", "Sales", "Picker"])
    password = st.text_input("Role password", type="password")

    if st.button("Login"):
        ok = False
        if role == "Admin" and password == roles_conf.get("admin_password", ""):
            ok = True
        elif role == "Sales" and password == roles_conf.get("sales_password", ""):
            ok = True
        elif role == "Picker" and password == roles_conf.get("picker_password", ""):
            ok = True

        if not ok:
            st.error("Invalid role or password.")
        else:
            st.session_state["role"] = role
            st.session_state["user_name"] = name.strip() or role
            st.rerun()

    st.stop()  # Don't render rest of app until logged in


require_login()
role = st.session_state.get("role", "Admin")
user_name = st.session_state.get("user_name", "Admin")

# ----------------------------
# Data loading / helpers
# ----------------------------
@st.cache_data(show_spinner=False)
def load_df():
    eng = get_engine()
    with eng.connect() as conn:
        df = pd.read_sql("SELECT * FROM items ORDER BY created_at DESC", conn)
    return df


def refresh_data():
    load_df.clear()


def get_active_df():
    """Return only items not marked sold (for active inventory views)."""
    df = load_df()
    if "sold" in df.columns:
        return df[~df["sold"].fillna(False)]
    return df


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


def create_single_label_pdf(item: dict) -> bytes:
    """
    Create a 4" x 6" label PDF for a single item.
    Includes make/model, PN, SN, bin, qty, category, notes, and code.
    """
    # 4" wide x 6" tall
    label_width = 4 * inch
    label_height = 6 * inch

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(label_width, label_height))

    margin_x = 0.3 * inch
    margin_y = 0.3 * inch

    x = margin_x
    y = label_height - margin_y

    make = (item.get("make") or "").strip()
    model = (item.get("model") or "").strip()
    part_number = item.get("part_number") or ""
    serial_number = item.get("serial_number") or ""
    bin_location = item.get("bin_location") or ""
    quantity = item.get("quantity", 1)
    category = (item.get("category") or "").strip()
    notes = (item.get("notes") or "").strip()

    # ---------- TITLE LINE ----------
    title_line = f"{make} {model}".strip()
    if title_line:
        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, y, title_line[:40])
        y -= 0.4 * inch

    # ---------- KEY FIELDS (INCLUDING CATEGORY) ----------
    c.setFont("Helvetica-Bold", 12)
    info_lines = [
        f"PN: {part_number or '-'}",
        f"SN: {serial_number or '-'}",
        f"Bin: {bin_location or '-'}",
        f"Qty: {quantity}",
        f"Cat: {category or '-'}",
    ]

    for line in info_lines:
        c.drawString(x, y, line[:50])
        y -= 0.3 * inch

    # ---------- NOTES BLOCK (WRAPPED) ----------
    if notes:
        y -= 0.1 * inch
        c.setFont("Helvetica", 10)
        c.drawString(x, y, "Notes:")
        y -= 0.25 * inch

        c.setFont("Helvetica", 9)
        words = notes.split()
        line = ""
        wrapped_lines = []
        char_limit = 60  # rough width control; tweak if needed

        for w in words:
            candidate = f"{line} {w}".strip()
            if len(candidate) > char_limit:
                wrapped_lines.append(line)
                line = w
            else:
                line = candidate
        if line:
            wrapped_lines.append(line)

        # Limit number of note lines so we leave room for the barcode
        for nl in wrapped_lines[:4]:
            c.drawString(x + 0.15 * inch, y, nl[:80])
            y -= 0.22 * inch

    # Leave some space between text and barcode
    y -= 0.15 * inch

    # ---------- BARCODE / QR BLOCK AT BOTTOM ----------
    code_value = item.get("code_value", "")
    code_type = item.get("code_type", "Barcode (Code128)")

    try:
        if code_type == "Barcode (Code128)":
            img_bytes = generate_barcode_image_bytes(code_value)
        else:
            img_bytes = generate_qr_image_bytes(code_value)

        img = Image.open(io.BytesIO(img_bytes))
        img_w, img_h = img.size

        # Use most of the width, about 1.75" tall for the code
        code_box_w = label_width - 2 * margin_x
        code_box_h = 1.75 * inch

        scale = min(code_box_w / img_w, code_box_h / img_h)
        disp_w = img_w * scale
        disp_h = img_h * scale

        code_x = (label_width - disp_w) / 2  # center horizontally
        code_y = margin_y + 0.4 * inch       # leave a bit of bottom margin

        c.drawImage(
            ImageReader(img),
            code_x,
            code_y,
            width=disp_w,
            height=disp_h,
            preserveAspectRatio=True,
            mask="auto",
        )

        # Human-readable ID text just under the barcode
        c.setFont("Helvetica", 10)
        c.drawCentredString(
            label_width / 2,
            margin_y,
            f"ID: {code_value}",
        )
    except Exception:
        # Fallback: just print the ID text at the bottom
        c.setFont("Helvetica", 10)
        c.drawString(margin_x, margin_y, f"ID: {code_value}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


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


# ----------------------------
# Sidebar navigation
# ----------------------------
with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Go to",
        [
            "Receive Inventory",
            "Inventory List & Search",
            "Scan to Pick",
            "Perform Inventory Audit",
            "Picker Queue",
            "Sold Archive",
            "Export/Import",
        ],
    )
    st.caption("Streamlit Cloud + Postgres. Set secrets in the deployment settings.")


# ----------------------------
# Pages
# ----------------------------
if page == "Receive Inventory":
    if role != "Admin":
        st.error("Only Admin can receive inventory.")
    else:
        st.subheader("Receive Inventory")

        if "just_added_item" not in st.session_state:
            st.session_state.just_added_item = None

        # ---------- FORM ----------
        with st.form("receive_form", clear_on_submit=True):
            cols = st.columns(2)

            with cols[0]:
                make = st.text_input("Make *")
                model = st.text_input("Model *")
                part_number = st.text_input("Part Number (optional)")
                serial_number = st.text_input("Serial Number (optional)")
                quantity = st.number_input("Quantity", min_value=1, step=1, value=1)
                bin_location = st.text_input(
                    "Bin Location *", placeholder="e.g., Aisle 1 / Bin B3"
                )

                category = st.selectbox(
                    "Category *",
                    [
                        "Crankshafts",
                        "Camshafts",
                        "Connecting Rods",
                        "Rocker Arms",
                        "Lifters",
                        "Gears",
                        "Counterweights",
                    ],
                    index=None,
                    placeholder="Select a category",
                )

            with cols[1]:
                code_type = st.selectbox(
                    "Code Type", ["Barcode (Code128)", "QR Code"], index=0
                )
                photo = st.file_uploader("Photo (JPG/PNG)", type=["jpg", "jpeg", "png"])
                notes = st.text_area("Notes (optional)")

                pcol1, pcol2, pcol3 = st.columns(3)
                with pcol1:
                    purchase_price = st.number_input(
                        "Purchase Price",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        value=0.0,
                    )
                with pcol2:
                    repair_cost = st.number_input(
                        "Repair Cost",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        value=0.0,
                    )
                with pcol3:
                    sale_price = st.number_input(
                        "Sale Price",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        value=0.0,
                    )

            submitted = st.form_submit_button("Add to Inventory")

        # ---------- HANDLE SUBMIT (outside form) ----------
        if submitted:
            if not make or not model or not bin_location or category is None:
                st.error("Make, Model, Bin Location, and Category are required.")
                st.session_state.just_added_item = None
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
                    "category": category,
                    "purchase_price": purchase_price if purchase_price > 0 else None,
                    "repair_cost": repair_cost if repair_cost > 0 else None,
                    "sale_price": sale_price if sale_price > 0 else None,
                    "sold": False,
                    "requested_by": None,
                    "request_status": None,
                    "created_at": datetime.utcnow().isoformat(timespec="seconds"),
                }
                insert_item(payload)
                # stash it so we can show label + barcode on this rerun
                st.session_state.just_added_item = payload

        # ---------- SHOW LABEL + BARCODE (outside form) ----------
        if st.session_state.just_added_item is not None:
            item = st.session_state.just_added_item
            st.success(f"Item added with ID: {item['id']}")

            # Print label button
            try:
                label_pdf = create_single_label_pdf(item)
                st.download_button(
                    label="Print Label",
                    data=label_pdf,
                    file_name=f"label_{item['id']}.pdf",
                    mime="application/pdf",
                    key=f"recv_label_{item['id']}",
                )
            except Exception as e:
                st.warning(f"Unable to generate label PDF: {e}")

            # Show barcode / QR image
            try:
                if item.get("code_type") == "Barcode (Code128)":
                    img_bytes = generate_barcode_image_bytes(item["code_value"])
                else:
                    img_bytes = generate_qr_image_bytes(item["code_value"])
                st.image(
                    img_bytes,
                    caption=f"{item.get('code_type')} for {item['id']}",
                    width=260,
                )
            except Exception:
                pass

elif page == "Inventory List & Search":
    if role not in ["Admin", "Sales"]:
        st.error("Only Admin and Sales can access the Inventory List.")
    else:
        st.subheader("Inventory")
        df = get_active_df()
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
                fdf = fdf[
                    fdf.apply(
                        lambda r: any(
                            ql in str(r[c]).lower()
                            for c in [
                                "make",
                                "model",
                                "part_number",
                                "serial_number",
                                "id",
                                "bin_location",
                                "notes",
                            ]
                        ),
                        axis=1,
                    )
                ]
            if make_f:
                fdf = fdf[fdf["make"].str.contains(make_f, case=False, na=False)]
            if model_f:
                fdf = fdf[fdf["model"].str.contains(model_f, case=False, na=False)]
            if part_f:
                fdf = fdf["part_number"].fillna("").str.contains(
                    part_f, case=False, na=False
                )
                fdf = df[fdf]

            from streamlit import column_config

            show_cols = [
                "id",
                "make",
                "model",
                "part_number",
                "serial_number",
                "bin_location",
                "quantity",
                "category",
                "created_at",
                "photo_url",
            ]
            for col in show_cols:
                if col not in fdf.columns:
                    fdf[col] = None

            rename = {"photo_url": "Photo"}
            img_col = column_config.ImageColumn("Photo", width="small")
            st.dataframe(
                fdf[show_cols].rename(columns=rename),
                use_container_width=True,
                column_config={"Photo": img_col},
            )

            st.markdown("---")
            left, mid, right = st.columns([2, 2, 2])
            with left:
                st.subheader("Preview / Edit")
                ids = fdf["id"].tolist()
                if ids:
                    sel_id = st.selectbox("Select Item ID", ids)
                    row = fdf[fdf["id"] == sel_id].iloc[0].to_dict()
                    if row.get("photo_url"):
                        try:
                            st.image(
                                row["photo_url"],
                                caption="Photo",
                                use_column_width=True,
                            )
                        except Exception:
                            pass
                    with st.form("edit_item"):
                        new_make = st.text_input("Make", row.get("make") or "")
                        new_model = st.text_input("Model", row.get("model") or "")
                        new_pn = st.text_input(
                            "Part Number (optional)", row.get("part_number") or ""
                        )
                        new_sn = st.text_input(
                            "Serial Number (optional)", row.get("serial_number") or ""
                        )
                        new_bin = st.text_input(
                            "Bin Location *", row.get("bin_location") or ""
                        )
                        new_qty = st.number_input(
                            "Quantity",
                            min_value=0,
                            value=int(row.get("quantity", 1) or 0),
                        )
                        new_notes = st.text_area("Notes", row.get("notes") or "")
                        new_category = st.selectbox(
                            "Category *",
                            [
                                "Crankshafts",
                                "Camshafts",
                                "Connecting Rods",
                                "Rocker Arms",
                                "Lifters",
                                "Gears",
                                "Counterweights",
                            ],
                            index=(
                                [
                                    "Crankshafts",
                                    "Camshafts",
                                    "Connecting Rods",
                                    "Rocker Arms",
                                    "Lifters",
                                    "Gears",
                                    "Counterweights",
                                ].index(row.get("category"))
                                if row.get("category")
                                in [
                                    "Crankshafts",
                                    "Camshafts",
                                    "Connecting Rods",
                                    "Rocker Arms",
                                    "Lifters",
                                    "Gears",
                                    "Counterweights",
                                ]
                                else 0
                            ),
                        )

                        # Pricing (Admin sees all, Sales only sees Sale Price)
                        if role == "Admin":
                            pcol1, pcol2, pcol3 = st.columns(3)
                            with pcol1:
                                new_purchase_price = st.number_input(
                                    "Purchase Price",
                                    min_value=0.0,
                                    step=0.01,
                                    format="%.2f",
                                    value=float(row.get("purchase_price") or 0.0),
                                )
                            with pcol2:
                                new_repair_cost = st.number_input(
                                    "Repair Cost",
                                    min_value=0.0,
                                    step=0.01,
                                    format="%.2f",
                                    value=float(row.get("repair_cost") or 0.0),
                                )
                            with pcol3:
                                new_sale_price = st.number_input(
                                    "Sale Price",
                                    min_value=0.0,
                                    step=0.01,
                                    format="%.2f",
                                    value=float(row.get("sale_price") or 0.0),
                                )
                        else:  # Sales
                            new_purchase_price = row.get("purchase_price")
                            new_repair_cost = row.get("repair_cost")
                            new_sale_price = st.number_input(
                                "Sale Price",
                                min_value=0.0,
                                step=0.01,
                                format="%.2f",
                                value=float(row.get("sale_price") or 0.0),
                            )

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
                                "category": new_category,
                                "sale_price": new_sale_price
                                if new_sale_price and new_sale_price > 0
                                else None,
                            }
                            if role == "Admin":
                                updates["purchase_price"] = (
                                    new_purchase_price
                                    if new_purchase_price and new_purchase_price > 0
                                    else None
                                )
                                updates["repair_cost"] = (
                                    new_repair_cost
                                    if new_repair_cost and new_repair_cost > 0
                                    else None
                                )
                            update_item(sel_id, updates)
                            st.success("Item updated.")

                    # Print label button for this item
                    try:
                        label_pdf = create_single_label_pdf(row)
                        st.download_button(
                            label="Print Label for Selected Item",
                            data=label_pdf,
                            file_name=f"label_{row['id']}.pdf",
                            mime="application/pdf",
                            key=f"inv_label_{row['id']}",
                        )
                    except Exception as e:
                        st.warning(f"Unable to generate label PDF: {e}")

                                       # Request pick (Admin or Sales)
                    if role in ["Admin", "Sales"]:
                        req_status = row.get("request_status")
                        # Make sure "sold" behaves like a True/False
                        sold_flag = bool(row.get("sold")) if row.get("sold") is not None else False

                        if not sold_flag and req_status != "pending":
                            if st.button("Request Pick"):
                                update_item(
                                    sel_id,
                                    {
                                        "requested_by": user_name,
                                        "request_status": "pending",
                                    },
                                )
                                st.success("Pick request created.")
                                st.rerun()

                        elif req_status == "pending":
                            st.info("Pick already requested for this item.")

                            # 🔹 Admin-only escape hatch to clear a stuck pick request
                            if role == "Admin":
                                if st.button("Clear Pick Request (Admin only)"):
                                    update_item(
                                        sel_id,
                                        {"request_status": None, "requested_by": None},
                                    )
                                    st.success("Pick request cleared; item can be picked again.")
                                    st.rerun()


            with mid:
                st.subheader("Adjust / Delete")
                ids2 = fdf["id"].tolist()
                if ids2:
                    sel2 = st.selectbox(
                        "Select Item to Adjust/Delete", ids2, key="sel2"
                    )
                    cur_qty = int(
                        fdf.loc[fdf["id"] == sel2, "quantity"].iloc[0] or 0
                    )
                    new_qty2 = st.number_input(
                        "New Quantity", min_value=0, step=1, value=cur_qty
                    )
                    if st.button("Update Quantity"):
                        update_quantity(sel2, int(new_qty2))
                        st.success("Quantity updated.")
                    if role == "Admin":
                        if st.button("Delete Item"):
                            st.warning(
                                "Are you sure you want to delete this item? This cannot be undone."
                            )
                            colA, colB = st.columns(2)
                            with colA:
                                if st.button("Yes, delete"):
                                    delete_item(sel2)
                                    st.success("Item deleted.")
                                    st.rerun()
                            with colB:
                                st.write("")
                    else:
                        st.caption("Only Admin can delete items.")

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

elif page == "Scan to Pick":
    if role not in ["Admin", "Picker"]:
        st.error("Only Admin and Picker can use Scan to Pick.")
    else:
        st.subheader("Scan to Pick")
        st.caption(
            "Click the box and scan the label. Most scanners send Enter, which submits the form."
        )
        df = get_active_df()

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
                st.error(f"No active (unsold) item found with ID: {code}")
            else:
                row = match.iloc[0].to_dict()
                st.success(
                    f"Found item ID {code}: {row['make']} {row['model']} (BIN {row.get('bin_location','')})"
                )
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.write("**Item Details**")
                    st.json(
                        {
                            k: row.get(k)
                            for k in [
                                "make",
                                "model",
                                "part_number",
                                "serial_number",
                                "bin_location",
                                "quantity",
                                "notes",
                                "created_at",
                            ]
                        }
                    )
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
                        new_pn = st.text_input(
                            "Part Number (optional)", row.get("part_number") or ""
                        )
                        new_sn = st.text_input(
                            "Serial Number (optional)", row.get("serial_number") or ""
                        )
                        new_bin = st.text_input(
                            "Bin Location *", row.get("bin_location") or ""
                        )
                        new_qty = st.number_input(
                            "Quantity",
                            min_value=0,
                            value=int(row.get("quantity", 1)),
                        )
                        new_notes = st.text_area("Notes", row.get("notes") or "")
                        ok = st.form_submit_button("Save changes")
                    if ok:
                        if not new_make or not new_model or not new_bin:
                            st.error(
                                "Make, Model, and Bin Location are required."
                            )
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
                        st.warning(
                            "Are you sure you want to remove this part? This cannot be undone."
                        )
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
    if role != "Admin":
        st.error("Only Admin can perform inventory audits.")
    else:
        st.subheader("Inventory Audit")
        st.caption(
            "Start an audit, then scan each item once. Use Download to save results."
        )
        df = get_active_df()

        if "audit_started" not in st.session_state:
            st.session_state.audit_started = False
        if "audit_scanned" not in st.session_state:
            st.session_state.audit_scanned = set()

        if not st.session_state.audit_started:
            if st.button("Start Audit Session"):
                st.session_state.audit_started = True
                st.session_state.audit_scanned = set()
        else:
            colx, coly = st.columns([2, 1])
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
                st.metric(
                    "Remaining",
                    max(0, len(df) - len(st.session_state.audit_scanned)),
                )

            verified_df = df[df["id"].isin(st.session_state.audit_scanned)].copy()
            missing_df = df[~df["id"].isin(st.session_state.audit_scanned)].copy()

            st.markdown("### ✅ Verified Items")
            st.dataframe(
                verified_df[
                    ["id", "make", "model", "bin_location", "quantity", "created_at"]
                ],
                use_container_width=True,
            )

            st.markdown("### ❌ Not Yet Verified")
            st.dataframe(
                missing_df[
                    ["id", "make", "model", "bin_location", "quantity", "created_at"]
                ],
                use_container_width=True,
            )

            st.markdown("---")
            results = []
            now = datetime.utcnow().isoformat(timespec="seconds")
            for _, r in df.iterrows():
                results.append(
                    {
                        "id": r["id"],
                        "make": r["make"],
                        "model": r["model"],
                        "bin_location": r.get("bin_location"),
                        "quantity": r.get("quantity"),
                        "verified": r["id"] in st.session_state.audit_scanned,
                        "timestamp": now,
                    }
                )
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

elif page == "Picker Queue":
    # Now Admin, Picker, and Sales can access this page
    if role not in ["Admin", "Picker", "Sales"]:
        st.error("Only Admin, Picker, and Sales can access the Picker Queue.")
    else:
        st.subheader("Picker Queue")

        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                    FROM items
                    WHERE request_status = 'pending'
                      AND (sold = FALSE OR sold IS NULL)
                    ORDER BY created_at
                    """
                )
            ).mappings().all()

        if not rows:
            st.info("No pending pick requests.")
        else:
            # ---- Summary at top ----
            total_waiting = len(rows)
            st.metric("Parts waiting to be picked", total_waiting)

            # Build a summary table for all pending picks
            summary_data = []
            for r in rows:
                summary_data.append(
                    {
                        "ID": r["id"],
                        "Make": r["make"],
                        "Model": r["model"],
                        "PN": r.get("part_number") or "",
                        "SN": r.get("serial_number") or "",
                        "Bin": r.get("bin_location") or "",
                        "Qty": r.get("quantity") or 0,
                        "Requested By": r.get("requested_by") or "",
                        "Requested At": r.get("created_at") or "",
                    }
                )

            summary_df = pd.DataFrame(summary_data)
            st.markdown("### All pending pick requests")
            st.dataframe(summary_df, use_container_width=True)

            st.markdown("---")

            # For Sales: read-only view of queue
            if role == "Sales":
                st.info(
                    "Sales has a read-only view of the picker queue. "
                    "Pickers (or Admin) handle scanning and marking items as sold."
                )
            else:
                # Admin / Picker can act on individual requests
                options = {
                    f"{r['make']} {r['model']} (PN: {r.get('part_number') or '-'}) "
                    f"- Bin {r.get('bin_location') or '-'} | Requested by: {r.get('requested_by') or '?'}": r
                    for r in rows
                }
                label = st.selectbox("Pick request to process", list(options.keys()))
                item = options[label]

                st.markdown("### Item details")
                st.write(f"Requested by: **{item.get('requested_by') or '-'}**")
                st.write(f"Make / Model: {item['make']} {item['model']}")
                st.write(f"PN: {item.get('part_number') or '-'}")
                st.write(f"SN: {item.get('serial_number') or '-'}")
                st.write(f"Bin: {item.get('bin_location') or '-'}")
                st.write(f"Notes: {item.get('notes') or '-'}")

                scan_code = st.text_input(
                    "Scan barcode to confirm item", key=f"scan_{item['id']}"
                )

                if scan_code:
                    if scan_code.strip() == item["code_value"]:
                        st.success("Barcode matches. You have the correct item.")
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("Mark as Sold"):
                                with eng.begin() as conn2:
                                    conn2.execute(
                                        text(
                                            """
                                            UPDATE items
                                            SET sold = TRUE,
                                                request_status = 'fulfilled'
                                            WHERE id = :id
                                            """
                                        ),
                                        {"id": item["id"]},
                                    )
                                refresh_data()
                                st.success(
                                    "Item marked as sold and removed from active inventory."
                                )
                                st.rerun()
                        with col2:
                            if st.button("Cancel Request / Return to stock"):
                                with eng.begin() as conn2:
                                    conn2.execute(
                                        text(
                                            """
                                            UPDATE items
                                            SET request_status = NULL,
                                                requested_by = NULL
                                            WHERE id = :id
                                            """
                                        ),
                                        {"id": item["id"]},
                                    )
                                refresh_data()
                                st.info(
                                    "Request canceled. Item remains in inventory."
                                )
                                st.rerun()
                    else:
                        st.error("Scanned code does not match this item.")

elif page == "Sold Archive":
    if role != "Admin":
        st.error("Only Admin can access Sold / Archived items.")
    else:
        st.subheader("Sold / Archived Items")

        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    """
                SELECT *
                FROM items
                WHERE sold = TRUE
                ORDER BY created_at DESC
                """
                )
            ).mappings().all()

        if not rows:
            st.info("No sold items.")
        else:
            options = {
                f"{r['make']} {r['model']} (PN: {r.get('part_number') or '-'}) - Bin {r.get('bin_location') or '-'}": r
                for r in rows
            }
            label = st.selectbox("Sold item", list(options.keys()))
            item = options[label]

            st.markdown("### Details")
            st.write(f"Make / Model: {item['make']} {item['model']}")
            st.write(f"PN: {item.get('part_number') or '-'}")
            st.write(f"SN: {item.get('serial_number') or '-'}")
            st.write(f"Bin: {item.get('bin_location') or '-'}")
            st.write(f"Notes: {item.get('notes') or '-'}")
            st.write(f"Requested by: {item.get('requested_by') or '-'}")
            st.write(f"Status: {item.get('request_status') or '-'}")

            if st.button("Return to Stock (Unmark Sold)"):
                with eng.begin() as conn:
                    conn.execute(
                        text(
                            """
                        UPDATE items
                        SET sold = FALSE,
                            request_status = NULL,
                            requested_by = NULL
                        WHERE id = :id
                        """
                        ),
                        {"id": item["id"]},
                    )
                refresh_data()
                st.success("Item returned to stock.")
                st.rerun()

elif page == "Export/Import":
    if role != "Admin":
        st.error("Only Admin can export / import full data.")
    else:
        st.subheader("Export / Import")
        df = load_df()
        if not df.empty:
            st.download_button(
                "Download CSV Export (All Items)",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name="inventory_export.csv",
                mime="text/csv",
            )
        else:
            st.info("No items to export yet.")

        st.markdown("---")
        st.subheader("Bulk Import from CSV")
        st.caption(
            "CSV must have columns: make, model, part_number (optional), serial_number (optional), quantity, bin_location*. "
            "ID, code, and timestamps are auto-generated."
        )
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up is not None:
            try:
                imp = pd.read_csv(up).fillna("")
                required = {"make", "model", "bin_location"}
                if not required.issubset(set(imp.columns)):
                    missing = sorted(list(required - set(imp.columns)))
                    st.error(f"Missing required columns: {missing}")
                else:
                    added = 0
                    for _, row in imp.iterrows():
                        item_id = str(uuid.uuid4())[:12]
                        payload = {
                            "id": item_id,
                            "make": str(row.get("make", "")).strip(),
                            "model": str(row.get("model", "")).strip(),
                            "part_number": (
                                str(row.get("part_number", "")).strip() or None
                            ),
                            "serial_number": (
                                str(row.get("serial_number", "")).strip() or None
                            ),
                            "quantity": int(row.get("quantity", 1) or 1),
                            "photo_url": None,
                            "code_type": "Barcode (Code128)",
                            "code_value": item_id,
                            "bin_location": str(row.get("bin_location", "")).strip(),
                            "notes": (
                                str(row.get("notes", "")).strip() or None
                            ),
                            "category": str(row.get("category", "")).strip()
                            or None,
                            "purchase_price": None,
                            "repair_cost": None,
                            "sale_price": None,
                            "sold": False,
                            "requested_by": None,
                            "request_status": None,
                            "created_at": datetime.utcnow().isoformat(
                                timespec="seconds"
                            ),
                        }
                        if (
                            payload["make"]
                            and payload["model"]
                            and payload["bin_location"]
                        ):
                            insert_item(payload)
                            added += 1
                    st.success(f"Imported {added} items.")
            except Exception as e:
                st.error(f"Import failed: {e}")
