import streamlit as st
import pandas as pd
import requests
import os
from dotenv import load_dotenv
import logging
import json
import unicodedata
import re
from urllib.parse import quote_plus
import streamlit.components.v1 as components

logging.basicConfig(level=logging.INFO)
st.title("📱 WhatsApp Message Automation for MIS Report")

# --- File upload and input controls ---
excel_file = st.file_uploader("Upload Excel file with MIS and Message Format", type=["xlsx"])
override_number = st.text_input("Specify test/customer number for all messages (optional)")

# --- Snapshot inputs ---
snapshot_location = st.text_input("Snapshot Location", value="c:\\snapshots")
snapshot_prefix = st.text_input("Snapshot Prefix", value="snapshot_")
snapshot_extension = st.text_input("Snapshot File Extension (include dot, e.g., .png)", value=".png")

# --- Initialize session state for messages ---
if "messages" not in st.session_state:
    st.session_state["messages"] = []

if excel_file:
    xls = pd.ExcelFile(excel_file)
    sheet_names = xls.sheet_names

    def choose_default(sheet_options, preferred_names):
        lower_map = {s.lower(): s for s in sheet_options}
        for name in preferred_names:
            if name.lower() in lower_map:
                return lower_map[name.lower()]
        return sheet_options[0]

    mis_default = choose_default(sheet_names, ["MIS", "mis", "MIS Report", "Sheet1", "Sheet 1", "Sheet"])
    msg_default = choose_default(sheet_names, ["Format", "Message", "Message Format", "Format"])

    mis_sheet = st.selectbox("Select MIS Report sheet", sheet_names, index=sheet_names.index(mis_default))
    msg_sheet = st.selectbox("Select WhatsApp Message Format sheet", sheet_names, index=sheet_names.index(msg_default))

    # --- Load MIS and message format data ---
    mis_df = pd.read_excel(xls, sheet_name=mis_sheet, dtype=str)
    msg_df = pd.read_excel(xls, sheet_name=msg_sheet)

    # Clean number/contact columns
    for col in mis_df.columns:
        if any(key in col.lower() for key in ["number", "contact", "phone", "mobile", "id"]):
            mis_df[col] = mis_df[col].astype(str).str.strip().replace("nan", "").replace("None", "")

    # --- Pagination control ---
    total_rows = len(mis_df)
    page_size = 10
    total_pages = (total_rows + page_size - 1) // page_size

    page_number = st.selectbox(
        "Select Page (10 rows per page)",
        options=list(range(1, total_pages + 1)),
        format_func=lambda x: f"Page {x} ({(x-1)*page_size+1}–{min(x*page_size, total_rows)})"
    )

    start_idx = (page_number - 1) * page_size
    end_idx = min(start_idx + page_size, total_rows)
    page_df = mis_df.iloc[start_idx:end_idx]

    st.write(f"### Showing rows {start_idx+1} to {end_idx} of {total_rows}:")
    st.dataframe(page_df)

    st.write("### Preview of Message Content:")
    st.dataframe(msg_df)

    # --- Template handling ---
    if 'Format' not in msg_df.columns:
        st.error("Message Format sheet must contain a 'Format' column.")
        st.stop()

    default_prompt_template = str(msg_df['Format'].iloc[0])
    prompt_template = st.text_area("Edit or confirm message template:", default_prompt_template)

    # --- Safe template rendering ---
    class SafeDict(dict):
        def __missing__(self, key):
            return ''

    def render_message(template, values):
        safe_values = {k: (str(v) if v is not None else '') for k, v in values.items()}
        try:
            return template.format_map(SafeDict(safe_values))
        except Exception as e:
            logging.error(f"Template render error: {e}")
            msg = template
            for k, v in safe_values.items():
                msg = msg.replace(f"{{{k}}}", v)
            return msg

    # --- Clean message text ---
    def clean_message_text(text: str) -> str:
        if text is None:
            return ''
        t = unicodedata.normalize('NFC', str(text))
        t = t.replace('\u00A0', ' ')
        replacements = {
            '\u2018': "'", '\u2019': "'", '\u201C': '"', '\u201D': '"',
            '\u2013': '-', '\u2014': '-', '\u2026': '...'
        }
        for k, v in replacements.items():
            t = t.replace(k, v)
        t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+", '', t)
        t = re.sub(r' +', ' ', t)
        return t.strip()

    # --- Generate messages button ---
    if st.button(f"Generate Messages for Page {page_number}"):
        load_dotenv()
        api_base_url = os.getenv("API_BASE_URL")
        whatsapp_web_base_url = os.getenv("WHATSAPP_WEB_BASE_URL", "https://web.whatsapp.com/send")

        if not api_base_url:
            st.error("Missing environment variable: API_BASE_URL")
            st.stop()

        st.session_state["messages"] = []  # Reset messages for current page

        for idx, row in page_df.iterrows():
            row_dict = row.to_dict()
            request_number = row_dict.get('request_number') or row_dict.get('REQUEST NUMBER')
            customer_number = override_number or row_dict.get('customer_number') or row_dict.get('CUSTOMER CONTACT NO')
            if not customer_number:
                continue

            # Optional API fetch
            api_vals = {}
            if request_number:
                api_url = f"{api_base_url}?document_id={request_number}"
                try:
                    api_resp = requests.get(api_url, timeout=10)
                    if api_resp.status_code == 200:
                        api_vals = api_resp.json().get('data', {})
                except Exception:
                    pass

            loan_amount = row_dict.get('loan_amount') or row_dict.get('LOAN AMOUNT') or api_vals.get('loan_amount') or 'N/A'
            property_address = row_dict.get('property_address') or row_dict.get('PROPERTY ADDRESS') or api_vals.get('property_address') or 'N/A'
            customer_name = row_dict.get('customer_name') or row_dict.get('CUSTOMER NAME') or 'Customer'

            values = {
                "customer_name": customer_name,
                "loan_amount": loan_amount,
                "property_address": property_address,
                "request_number": request_number,
                "application_no": row_dict.get('APPLICATION NO', ''),
                "status": row_dict.get('STATUS', '')
            }

            msg = render_message(prompt_template, values)
            msg = clean_message_text(msg)

            # Snapshot path
            snapshot_path = ""
            if request_number:
                ext = snapshot_extension.strip() or ""
                snapshot_path = os.path.join(snapshot_location, f"{snapshot_prefix}{request_number}{ext}")

            st.session_state["messages"].append({
                "customer_number": customer_number,
                "message": msg,
                "request_number": request_number,
                "snapshot_path": snapshot_path
            })

    # --- Display generated messages from session state ---
    if st.session_state["messages"]:
        st.write(f"### Generated Messages (Page {page_number}):")
        for i, m in enumerate(st.session_state["messages"], start=1):
            st.write(f"{i}. **To:** {m['customer_number']}")
            st.write(m['message'])

            phone = str(m['customer_number']).strip()
            text = quote_plus(m['message'])
            wa_url = f"{os.getenv('WHATSAPP_WEB_BASE_URL','https://web.whatsapp.com/send')}?phone={phone}&text={text}"

            req_no = str(m.get("request_number", "")).strip()
            if req_no:
                st.markdown(f"**Request Number:** `{req_no}` | [Open WhatsApp Web]({wa_url})", unsafe_allow_html=True)

            # Snapshot path with one-click copy using st.components.v1.html
            snapshot_path = m.get("snapshot_path", "")
            if snapshot_path:
                escaped_path = snapshot_path.replace("\\", "\\\\")
                components.html(f"""
                <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                    <code>{snapshot_path}</code>
                    <button onclick="navigator.clipboard.writeText('{escaped_path}')">📋 Copy</button>
                </div>
                """, height=40)


        # --- Export to CSV ---
        from io import StringIO
        import csv
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(["phone", "message", "request_number", "snapshot_path"])
        for m in st.session_state["messages"]:
            writer.writerow([m["customer_number"], m["message"], m.get("request_number",""), m.get("snapshot_path","")])
        csv_data = buf.getvalue()
        st.download_button(
            "Download messages as CSV (for automation)",
            csv_data,
            file_name=f"messages_page_{page_number}.csv",
            mime="text/csv"
        )
