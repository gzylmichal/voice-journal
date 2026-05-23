#!/usr/bin/env python3
"""
Google Calendar OAuth Setup
============================
Run this ONCE on your Mac to authorise the voice journal to create
calendar events. It opens a browser, you click Allow, and it saves
a token file (gcal_token.json) that you then copy to the VPS.

Usage:
  1. pip install google-auth-oauthlib google-api-python-client
  2. Download your OAuth credentials from Google Cloud Console
     (see instructions below) and save as gcal_credentials.json
  3. python3 gcal_auth.py
  4. scp gcal_token.json YOUR_USER@YOUR_VPS_IP:/opt/voice-journal/
  5. sudo chown journal:journal /opt/voice-journal/gcal_token.json

Google Cloud Console setup (one-time, ~5 minutes):
  1. Go to console.cloud.google.com
  2. Create a new project (or use existing) — name it "voice-journal"
  3. Enable the Google Calendar API:
       APIs & Services → Enable APIs → search "Google Calendar API" → Enable
  4. Create OAuth credentials:
       APIs & Services → Credentials → Create Credentials → OAuth client ID
       Application type: Desktop app
       Name: voice-journal
       → Download JSON → save as gcal_credentials.json in this folder
  5. Configure OAuth consent screen (if prompted):
       User type: External
       App name: voice-journal
       Add your Gmail as a test user
"""

import json
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    print("Missing dependencies. Run:")
    print("  pip install google-auth-oauthlib google-api-python-client")
    exit(1)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = Path("gcal_credentials.json")
TOKEN_FILE = Path("gcal_token.json")


def main():
    if not CREDENTIALS_FILE.exists():
        print(f"ERROR: {CREDENTIALS_FILE} not found.")
        print("Download it from Google Cloud Console:")
        print("  APIs & Services → Credentials → your OAuth client → Download JSON")
        print(f"  Save it as {CREDENTIALS_FILE} in this directory")
        exit(1)

    creds = None

    # Check for existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If no valid creds, run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("Token refreshed.")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            # Opens browser for you to authorise
            creds = flow.run_local_server(port=0)
            print("Authorisation complete.")

        TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    print()
    print("=" * 55)
    print("  SUCCESS — token saved to gcal_token.json")
    print("=" * 55)
    print()
    print("Now copy it to the VPS:")
    print("  scp gcal_token.json YOUR_USER@YOUR_VPS_IP:/tmp/")
    print()
    print("Then on the VPS:")
    print("  sudo mv /tmp/gcal_token.json /opt/voice-journal/")
    print("  sudo chown journal:journal /opt/voice-journal/gcal_token.json")
    print("  sudo chmod 600 /opt/voice-journal/gcal_token.json")
    print()
    print("Then install the Python dependencies on the VPS:")
    print("  sudo /opt/voice-journal/venv/bin/pip install \\")
    print("    google-auth-oauthlib google-api-python-client")
    print()
    print("Test it:")
    print("  sudo systemctl start voice-journal-process")
    print("  cat /opt/voice-journal/voice_journal.log")


if __name__ == "__main__":
    main()
