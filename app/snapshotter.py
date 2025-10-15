from playwright.sync_api import sync_playwright
from dotenv import dotenv_values
import os
import time

# --- Load exact .env values ---
config = dotenv_values(".env")
USERNAME = config.get("USER")
PASSWORD = config.get("PASSWORD")
BASE_URL = config.get("BASE_URL", "https://icici-mortgage.anulom.com/draft/index")
LOGIN_URL = config.get("LOGIN_URL", "https://icici-mortgage.anulom.com/users/sign_in")
DOCUMENT_IDS_STR = config.get("DOCUMENT_IDS", "479169")
USER_DATA_DIR = config.get("USER_DATA_DIR", "playwright_session")
CAPTURE_MODE = config.get("CAPTURE_MODE", "half").lower()  # "half" or "full"
FULL_PAGE = config.get("FULL_PAGE", "false").lower() == "true"

# Parse document IDs
DOCUMENT_IDS = [int(x.strip()) for x in DOCUMENT_IDS_STR.split(",") if x.strip().isdigit()]

def ensure_logged_in(page):
    """Login using values from .env, ensuring exact typing."""
    page.goto(BASE_URL, wait_until="domcontentloaded")
    
    # If redirected to login page
    if "sign_in" in page.url.lower():
        print("🔐 Not logged in — attempting login...")
        page.goto(LOGIN_URL)
        
        # Wait for inputs
        page.wait_for_selector("#user_email", timeout=15000)
        page.wait_for_selector("#user_password", timeout=15000)

        # Click and type (simulate user typing)
        page.click("#user_email")
        page.type("#user_email", USERNAME, delay=50)
        page.click("#user_password")
        page.type("#user_password", PASSWORD, delay=50)

        # Click LOGIN button
        page.click('input[name="commit"]')
    else:
        print("✅ Already logged in (session reused).")

def capture_snapshots():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False  # change to True if you want headless
        )
        page = browser.new_page()
        ensure_logged_in(page)

        print(f"📸 Capture mode: {CAPTURE_MODE.upper()} | Full Page: {FULL_PAGE}")
        print(f"🔑 Using session directory: {USER_DATA_DIR}")

        for doc_id in DOCUMENT_IDS:
            url = f"{BASE_URL}?document_id={doc_id}"
            print(f"Opening document {doc_id} at URL: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector("text=Pending Details", timeout=15000)
                page.click("text=Pending Details")
                time.sleep(2)

                filename = f"snapshot_{doc_id}.png"
                viewport = page.viewport_size

                if CAPTURE_MODE == "half":
                    if FULL_PAGE:
                        full_height = page.evaluate("document.body.scrollHeight")
                        clip_region = {
                            "x": 0,
                            "y": 0,
                            "width": viewport["width"] // 2,
                            "height": full_height
                        }
                        page.screenshot(path=filename, clip=clip_region)
                    else:
                        clip_region = {
                            "x": 0,
                            "y": 0,
                            "width": viewport["width"] // 2,
                            "height": viewport["height"]
                        }
                        page.screenshot(path=filename, clip=clip_region)
                else:
                    page.screenshot(path=filename, full_page=FULL_PAGE)

                print(f"✅ Saved snapshot: {filename}")

            except Exception as e:
                print(f"❌ Failed for document {doc_id}: {e}")

        browser.close()

if __name__ == "__main__":
    capture_snapshots()
