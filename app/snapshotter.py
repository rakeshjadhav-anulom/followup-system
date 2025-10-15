from playwright.sync_api import sync_playwright
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration from environment ---
BASE_URL = os.getenv("BASE_URL", "")
DOCUMENT_IDS_STR = os.getenv("DOCUMENT_IDS", "479169")  # Comma-separated string

# Convert DOCUMENT_IDS_STR to list of ints
DOCUMENT_IDS = [int(x.strip()) for x in DOCUMENT_IDS_STR.split(",") if x.strip().isdigit()]

# Path to store persistent session data
USER_DATA_DIR = os.getenv("USER_DATA_DIR", "playwright_session")  # folder to store login session

def capture_snapshots():
    with sync_playwright() as p:
        # Launch browser with persistent context to reuse login
        browser = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False  # False to see the browser, True for background
        )
        page = browser.new_page()

        for doc_id in DOCUMENT_IDS:
            # Remove AUTH_KEY if using session
            url = f"{BASE_URL}?document_id={doc_id}"
            print(f"Opening document {doc_id} at URL: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Wait for the Pending Details tab/link
                page.wait_for_selector("text=Pending Details", timeout=15000)
                page.click("text=Pending Details")
                time.sleep(2)

                # Save snapshot
                filename = f"snapshot_{doc_id}.png"
                page.screenshot(path=filename, full_page=True)
                print(f"✅ Saved snapshot: {filename}")

            except Exception as e:
                print(f"❌ Failed for document {doc_id}: {e}")

        browser.close()

if __name__ == "__main__":
    capture_snapshots()
