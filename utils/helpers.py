# Utility functions for the followup-system

# Add reusable functions here, e.g., API calls, message formatting, etc.

def fetch_api_data(request_number):
    import requests
    api_url = f"https://icici-mortgage.anulom.com/api/v1/document/get_user_data?document_id={request_number}"
    try:
        api_resp = requests.get(api_url)
        if api_resp.status_code == 200:
            return api_resp.json()
        else:
            return {}
    except Exception:
        return {}

# Add more utilities as needed
