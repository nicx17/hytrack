import imaplib
import email
import re
import json
import requests
import smtplib
import os
import logging
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

# ===================== SETUP =====================

# Load environment variables from .env file
load_dotenv()

# Set up logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tracker.log"),
        logging.StreamHandler()
    ]
)

# ===================== CONFIG =====================

# Load configuration from environment variables
IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

ACTIVE_IDS_FILE = "active_ids.json"
WAYBILL_REGEX = r"\b\d{11}\b"

# ===================== FUNCTIONS =====================

def load_active_ids():
    """Loads the active waybill IDs from a JSON file."""
    try:
        with open(ACTIVE_IDS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.info(f"'{ACTIVE_IDS_FILE}' not found. Starting with an empty list.")
        return {}
    except json.JSONDecodeError:
        logging.error(f"Could not decode JSON from '{ACTIVE_IDS_FILE}'. Starting fresh.")
        return {}

def save_active_ids(data):
    """Saves the active waybill IDs to a JSON file."""
    with open(ACTIVE_IDS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def fetch_waybills_from_email():
    """Connects to IMAP and extracts waybill numbers from UNREAD emails."""
    waybills = set()
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        mail.select("INBOX")
        status, messages = mail.search(None, 'UNSEEN')
        if status != "OK":
            logging.error("Failed to search for emails.")
            return waybills

        email_ids = messages[0].split()
        if not email_ids:
            logging.info("No new unread emails found.")
            mail.logout()
            return waybills
        
        logging.info(f"Found {len(email_ids)} new email(s) to process.")

        for num in email_ids:
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            content = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() in ["text/plain", "text/html"]:
                        try:
                            content += part.get_payload(decode=True).decode(errors="ignore")
                        except:
                            continue
            else:
                try:
                    content = msg.get_payload(decode=True).decode(errors="ignore")
                except:
                    pass

            found = re.findall(WAYBILL_REGEX, content)
            for wb in found:
                waybills.add(wb)
            
            mail.store(num, '+FLAGS', '\\Seen')

        mail.logout()
    except imaplib.IMAP4.error as e:
        logging.error(f"IMAP connection failed: {e}")
    return waybills

def fetch_latest_event(waybill):
    """Scrapes the Blue Dart website for the latest tracking event for a waybill."""
    url = f"https://www.bluedart.com/trackdartresultthirdparty?trackFor=0&trackNo={waybill}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # MODIFICATION: Added timeout and status check for robustness
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        scan_table = soup.find("div", id=f"SCAN{waybill}").find("table")
        first_event_row = scan_table.find("tbody").find_all("tr")[0]
        cols = first_event_row.find_all("td")
        return {
            "Location": cols[0].text.strip(),
            "Details": cols[1].text.strip(),
            "Date": cols[2].text.strip(),
            "Time": cols[3].text.strip()
        }
    # MODIFICATION: More specific error handling
    except requests.exceptions.RequestException as e:
        logging.warning(f"Network error fetching waybill {waybill}: {e}")
    except (AttributeError, IndexError):
        logging.warning(f"Failed to parse HTML for {waybill}. Website structure may have changed.")
    return None

def send_html_email(subject, html_content):
    """Sends a formatted HTML email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        logging.info(f"Email alert sent successfully to {RECIPIENT_EMAIL}")
    except smtplib.SMTPException as e:
        logging.error(f"Failed to send email: {e}")

def build_html_message(waybill, event):
    """Builds the HTML content for the notification email."""
    return f"""
    <html>
    <head>
        <style>
            .container {{
                font-family: Arial, sans-serif;
                max-width: 500px;
                margin: auto;
                padding: 20px;
                border: 1px solid #ddd;
                border-radius: 8px;
                background-color: #f9f9f9;
                color: #333;
            }}
            h2 {{
                color: #2E86C1;
            }}
            .info {{
                margin: 10px 0;
                padding: 10px;
                background-color: #fff;
                border-left: 4px solid #2E86C1;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            }}
            .label {{
                font-weight: bold;
                display: inline-block;
                width: 80px;
            }}
            .track-link {{
                display: inline-block;
                margin-top: 20px;
                padding: 10px 15px;
                background-color: #000000;
                color: white;
                text-decoration: none;
                border-radius: 5px;
            }}
            .footer {{
                margin-top: 30px;
                font-size: 0.9em;
                color: #777;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📦 New Bluedart Tracking Update</h2>
            <div class="info"><span class="label">Location:</span> {event['Location']}</div>
            <div class="info"><span class="label">Status:</span> {event['Details']}</div>
            <div class="info"><span class="label">Date:</span> {event['Date']}</div>
            <div class="info"><span class="label">Time:</span> {event['Time']}</div>

            <a href="https://www.bluedart.com/trackdartresultthirdparty?trackFor=0&trackNo={waybill}" class="track-link">
                🔍 Track Your Package
            </a>

            <div class="footer">
                Thank you for using HyTrack
            </div>
        </div>
    </body>
    </html>
    """ 

# ===================== MAIN EXECUTION =====================

def main():
    """Main function to orchestrate the tracking process."""
    logging.info("--- Starting Blue Dart Tracking Script ---")

    # Step 1: Load current active IDs
    active_ids = load_active_ids()

    # Step 2: Check emails for new IDs
    new_waybills = fetch_waybills_from_email()
    for wb in new_waybills:
        if wb not in active_ids:
            active_ids[wb] = {"last_event": None, "delivered": False}
            logging.info(f"Added new tracking ID: {wb}")

    # Step 3: Track each active (non-delivered) ID
    # Create a copy of items to safely modify dict while iterating
    for waybill, info in list(active_ids.items()):
        if info.get("delivered", False):
            continue

        event = fetch_latest_event(waybill)
        if not event:
            logging.warning(f"Could not fetch event for {waybill}, will retry next time.")
            continue

        if "Delivered" in event["Details"]:
            logging.info(f"Package {waybill} has been delivered. Deactivating tracking.")
            active_ids[waybill]["delivered"] = True
            active_ids[waybill]["last_event"] = event # Save the final delivery event
            # Optional: Send one final "Delivered" notification
            html_msg = build_html_message(waybill, event)
            send_html_email(f"✅ DELIVERED: Waybill {waybill}", html_msg)
            continue
        
        if event != info.get("last_event"):
            logging.info(f"New update found for {waybill}: {event['Details']}")
            active_ids[waybill]["last_event"] = event
            html_msg = build_html_message(waybill, event)
            send_html_email(f"📦 Update for Waybill {waybill}", html_msg)
        else:
            logging.info(f"No new update for {waybill}. Current status: {event['Details']}")

    # Step 4: Save updated active IDs
    save_active_ids(active_ids)
    logging.info("--- Script run finished ---")

if __name__ == "__main__":
    main()