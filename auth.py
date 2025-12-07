import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from config import SCOPES, CREDENTIALS_FILE, TOKEN_FILE


def get_credentials():
    """Get valid user credentials from storage or run OAuth flow."""
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        print("📄 Found existing token, loading...")
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Token expired, refreshing...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"❌ Credentials file not found at {CREDENTIALS_FILE}\n"
                    "Please download from Google Cloud Console."
                )
            
            print("🔐 Starting OAuth flow...")
            print("📢 A browser window will open. Please:")
            print("   1. Sign in with your Google account")
            print("   2. Click 'Continue' on the unverified app warning")
            print("   3. Click 'Allow' to grant permissions\n")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            # Let it use any available port
            creds = flow.run_local_server(port=0, open_browser=True)
        
        print("💾 Saving credentials...")
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    
    return creds


def get_drive_service():
    """Build and return Google Drive service."""
    creds = get_credentials()
    return build('drive', 'v3', credentials=creds)


def get_gmail_service():
    """Build and return Gmail service."""
    creds = get_credentials()
    return build('gmail', 'v1', credentials=creds)


def test_drive_connection():
    """Test Drive API connection."""
    print("\n📁 Testing Drive API connection...")
    try:
        creds = get_credentials()
        service = build('drive', 'v3', credentials=creds)
        
        # Test by listing 5 files
        results = service.files().list(pageSize=5, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        print("✅ Drive API Connected!")
        print(f"   Found {len(files)} files:")
        for file in files:
            print(f"     - {file['name']}")
        return True
    except Exception as e:
        print(f"❌ Drive API Error: {e}")
        return False


def test_gmail_connection():
    """Test Gmail API connection."""
    print("\n📧 Testing Gmail API connection...")
    try:
        creds = get_credentials()
        service = build('gmail', 'v1', credentials=creds)
        
        # Test by getting profile
        profile = service.users().getProfile(userId='me').execute()
        
        print("✅ Gmail API Connected!")
        print(f"   Email: {profile['emailAddress']}")
        print(f"   Total messages: {profile['messagesTotal']}")
        return True
    except Exception as e:
        print(f"❌ Gmail API Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("🔐 Google API Authentication Test")
    print("=" * 60)
    
    try:
        drive_ok = test_drive_connection()
        gmail_ok = test_gmail_connection()
        
        print("\n" + "=" * 60)
        if drive_ok and gmail_ok:
            print("🎉 All authentication tests passed!")
            print(f"✅ Token saved to: {TOKEN_FILE}")
            print("\n👉 You can now run: python cli.py drive")
        else:
            print("⚠️  Some tests failed. Please check the errors above.")
        print("=" * 60)
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ Authentication Error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()