import streamlit as st
import pandas as pd
import requests
import os
import openai
from dotenv import load_dotenv
import logging
import json
import unicodedata
import re
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO)
st.title("📱 WhatsApp Message Automation for MIS Report")

# --- File upload and input controls ---
excel_file = st.file_uploader("Upload Excel file with MIS and Message Format", type=["xlsx"])
num_rows = st.number_input("Number of rows to process", min_value=1, max_value=100, value=5)
override_number = st.text_input("Specify test/customer number for all messages (optional)")


if excel_file:
    xls = pd.ExcelFile(excel_file)
    sheet_names = xls.sheet_names

    mis_sheet = st.selectbox("Select MIS Report sheet", sheet_names)
    msg_sheet = st.selectbox("Select WhatsApp Message Format sheet", sheet_names)

    mis_df = pd.read_excel(xls, sheet_name=mis_sheet)
    msg_df = pd.read_excel(xls, sheet_name=msg_sheet)

    st.write("### Preview of MIS Report:")
    st.dataframe(mis_df.head(num_rows))

    st.write("### Preview of Message Content:")
    st.dataframe(msg_df)

    if st.button("Generate Messages"):
        logging.info("Starting message generation...")
        load_dotenv()

        openai_api_key = os.getenv("OPENAI_API_KEY")
        api_base_url = os.getenv("API_BASE_URL")
        whatsapp_web_base_url = os.getenv("WHATSAPP_WEB_BASE_URL", "https://web.whatsapp.com/send")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

        if not api_base_url:
            st.error("Missing environment variable: API_BASE_URL")
            st.stop()
        if not openai_api_key:
            st.error("Missing environment variable: OPENAI_API_KEY")
            st.stop()

        openai.api_key = openai_api_key

        # --- Template handling ---
        if 'Format' not in msg_df.columns:
            st.error("Message Format sheet must contain a 'Format' column.")
            st.stop()

        default_prompt_template = str(msg_df['Format'].iloc[0])
        prompt_template = st.text_area("Edit or confirm message template:", default_prompt_template)
        use_openai_rewrite = st.checkbox("Use OpenAI to rewrite messages (costly)", value=False)

        # --- Deterministic local rendering ---
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

        def rewrite_message_with_openai(message_text):
            prompt = (
                "Rewrite the following message into a short, friendly, professional tone. "
                "Return only the rewritten message text without any extra commentary.\n\n"
                f"MESSAGE:\n{message_text}\n"
            )
            try:
                client = openai.OpenAI(api_key=openai_api_key)
                response = client.chat.completions.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logging.error(f"OpenAI rewrite error: {e}")
                return message_text

        # --- Deterministic API extractor: read only from api_data['data'] ---
        def extract_from_api(api_data):
            out = {'loan_amount': None, 'property_address': None}
            if not isinstance(api_data, dict):
                return out

            data_section = api_data.get('data', {}) if isinstance(api_data, dict) else {}

            # mortgagee.loan_amount
            mortgagee = data_section.get('mortgagee') if isinstance(data_section, dict) else None
            if isinstance(mortgagee, dict):
                out['loan_amount'] = mortgagee.get('loan_amount')

            # property list -> addresses
            prop = data_section.get('property') if isinstance(data_section, dict) else None
            prop_addrs = []
            if isinstance(prop, list) and len(prop) > 0:
                for p in prop:
                    if isinstance(p, dict):
                        addr = p.get('address') or p.get('PROPERTY ADDRESS') or p.get('prop_address')
                        if addr:
                            prop_addrs.append(str(addr).strip())

            if len(prop_addrs) == 0:
                out['property_address'] = None
            elif len(prop_addrs) == 1:
                out['property_address'] = prop_addrs[0]
            else:
                out['property_address'] = '; '.join([f"Property {i+1}: {a}" for i, a in enumerate(prop_addrs)])

            return out

        # --- Generate messages ---
        messages = []

        for idx, row in mis_df.head(num_rows).iterrows():
            logging.info(f"Processing row {idx+1}")
            row_dict = row.to_dict()

            request_number = row_dict.get('request_number') or row_dict.get('REQUEST NUMBER')
            customer_number = override_number or row_dict.get('customer_number') or row_dict.get('CUSTOMER CONTACT NO')

            if not customer_number:
                logging.warning(f"No customer number found for row {idx+1}, skipping.")
                continue

            # Fetch API data (if request_number present)
            api_data = {}
            if request_number:
                api_url = f"{api_base_url}?document_id={request_number}"
                try:
                    api_resp = requests.get(api_url, timeout=10)
                    if api_resp.status_code == 200:
                        api_data = api_resp.json()
                    else:
                        st.warning(f"API call failed for {request_number}: {api_resp.status_code}")
                except Exception as e:
                    st.warning(f"API call error for {request_number}: {e}")

            api_vals = extract_from_api(api_data) if api_data else {}

            # Merge according to rules: MIS preferred for customer fields; loan/property: MIS -> API['data']
            loan_amount_raw = row_dict.get('loan_amount') or row_dict.get('LOAN AMOUNT') or api_vals.get('loan_amount')
            if isinstance(loan_amount_raw, (int, float)):
                loan_amount = f"{int(loan_amount_raw):,}"
            else:
                loan_amount = str(loan_amount_raw) if loan_amount_raw is not None else 'N/A'

            property_address = row_dict.get('property_address') or row_dict.get('PROPERTY ADDRESS') or api_vals.get('property_address') or 'N/A'

            # Customer fields MUST come from MIS only
            customer_name = row_dict.get('customer_name') or row_dict.get('CUSTOMER NAME') or 'Customer'
            customer_contact = override_number or row_dict.get('customer_number') or row_dict.get('CUSTOMER CONTACT NO') or ''

            values = {
                "customer_name": customer_name,
                "loan_amount": loan_amount,
                "property_address": property_address,
                "request_number": request_number,
                "application_no": row_dict.get('APPLICATION NO', ''),
                "status": row_dict.get('STATUS', '')
            }

            msg = render_message(prompt_template, values)
            if use_openai_rewrite:
                msg = rewrite_message_with_openai(msg)

            # Normalize and clean the final message so fonts/rendering look consistent
            def clean_message_text(text: str) -> str:
                if text is None:
                    return ''
                # Normalize Unicode to NFC
                t = unicodedata.normalize('NFC', str(text))
                # Replace common non-breaking spaces with regular spaces
                t = t.replace('\u00A0', ' ')
                # Replace smart quotes/dashes with ASCII equivalents for consistent rendering
                replacements = {
                    '\u2018': "'", '\u2019': "'", '\u201C': '"', '\u201D': '"',
                    '\u2013': '-', '\u2014': '-', '\u2026': '...'
                }
                for k, v in replacements.items():
                    t = t.replace(k, v)
                # Remove control characters except newline and tab
                t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]+", '', t)
                # Collapse multiple spaces into one
                t = re.sub(r' +', ' ', t)
                # Trim
                t = t.strip()
                return t

            msg = clean_message_text(msg)

            messages.append({"customer_number": customer_contact, "message": msg})

        # Display results and provide send/export options
        st.write("### Generated Messages:")
        for i, m in enumerate(messages, start=1):
            st.write(f"{i}. **To:** {m['customer_number']}")
            st.write(m['message'])
            phone = str(m['customer_number']).replace("+", "").strip()
            # Properly URL-encode the message for the WhatsApp web link
            text = quote_plus(m['message'])
            wa_url = f"{whatsapp_web_base_url}?phone={phone}&text={text}"
            st.markdown(f"[Open WhatsApp Web]({wa_url})", unsafe_allow_html=True)
            st.write("---")

        # Export messages to CSV (useful for Selenium automation)
        try:
            from io import StringIO
            import csv
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(["phone", "message"])
            for m in messages:
                writer.writerow([m["customer_number"], m["message"]])
            csv_data = buf.getvalue()
            st.download_button("Download messages as CSV (for automation)", csv_data, file_name="messages.csv", mime="text/csv")
        except Exception:
            st.warning("Failed to prepare CSV export.")

        # Option: Send via WhatsApp Business Cloud API (requires env vars)
        send_via_cloud = st.checkbox("Send messages automatically via WhatsApp Business Cloud API", value=False)
        if send_via_cloud:
            wa_phone_id = os.getenv("WA_PHONE_NUMBER_ID")
            wa_token = os.getenv("WA_ACCESS_TOKEN")
            wa_api_base = os.getenv("WA_API_BASE", "https://graph.facebook.com/v15.0")
            if not wa_phone_id or not wa_token:
                st.error("Missing WA_PHONE_NUMBER_ID or WA_ACCESS_TOKEN in environment. Cannot send.")
            else:
                headers = {
                    "Authorization": f"Bearer {wa_token}",
                    "Content-Type": "application/json"
                }
                successes = 0
                failures = []
                for m in messages:
                    phone = str(m['customer_number']).replace("+", "").strip()
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": m['message']}
                    }
                    try:
                        resp = requests.post(f"{wa_api_base}/{wa_phone_id}/messages", headers=headers, json=payload, timeout=10)
                        if resp.status_code in (200,201):
                            successes += 1
                        else:
                            failures.append({"phone": phone, "status_code": resp.status_code, "body": resp.text})
                    except Exception as e:
                        failures.append({"phone": phone, "error": str(e)})

                st.success(f"Sent: {successes}; Failed: {len(failures)}")
                if failures:
                    st.json(failures)
