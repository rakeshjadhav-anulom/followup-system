import streamlit as st
import pandas as pd
import requests
import os
import openai
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
st.title("📱 WhatsApp Message Automation for MIS Report")

# --- File upload and input controls ---
excel_file = st.file_uploader("Upload Excel file with MIS and Message Format", type=["xlsx"])
num_rows = st.number_input("Number of rows to process", min_value=1, max_value=100, value=5)
override_number = st.text_input("Specify test/customer number for all messages (optional)")

# --- When Excel is uploaded ---
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

    # --- Generate button ---
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

        # --- Get message template ---
        if 'Format' not in msg_df.columns:
            st.error("Message Format sheet must contain a 'Format' column.")
            st.stop()

        default_prompt_template = str(msg_df['Format'].iloc[0])
        prompt_template = st.text_area("Edit or confirm message template:", default_prompt_template)

        # --- Helper: Generate message from template ---
        def prepare_message_with_openai(template, values):
            prompt = (
                f"{template}\n\n"
                f"Replace only the placeholders in curly braces with the provided values below.\n"
                f"Values: {values}\n"
                f"Return only the final message text."
            )
            try:
                client = openai.OpenAI(api_key=openai_api_key)
                response = client.chat.completions.create(
                    model=openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logging.error(f"OpenAI API error: {e}")
                st.error(f"OpenAI API error: {e}")
                return template

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

            # --- Fetch API data ---
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

            # --- Merge data ---
            loan_amount = api_data.get('loan_amount') or row_dict.get('loan_amount') or row_dict.get('LOAN AMOUNT', 'N/A')
            property_address = api_data.get('property_address') or row_dict.get('property_address') or row_dict.get('PROPERTY ADDRESS', 'N/A')

            values = {
                "customer_name": row_dict.get('customer_name') or row_dict.get('CUSTOMER NAME', 'Customer'),
                "loan_amount": loan_amount,
                "property_address": property_address,
                "request_number": request_number,
                "application_no": row_dict.get('APPLICATION NO', ''),
                "status": row_dict.get('STATUS', '')
            }

            msg = prepare_message_with_openai(prompt_template, values)
            messages.append({"customer_number": customer_number, "message": msg})

        # --- Display results ---
        st.write("### Generated Messages:")
        for m in messages:
            st.write(f"**To:** {m['customer_number']}")
            st.write(m['message'])
            phone = str(m['customer_number']).replace("+", "").strip()
            text = m['message'].replace("\n", "%0A").replace(" ", "%20")
            wa_url = f"{whatsapp_web_base_url}?phone={phone}&text={text}"
            st.markdown(f"[Send via WhatsApp Web]({wa_url})", unsafe_allow_html=True)
            st.write("---")
