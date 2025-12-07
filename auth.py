import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from config import SCOPES, CREDENTIALS_FILE, TOKEN_FILE, PROJECT_NAME


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
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"⚠️  Refresh failed: {e}")
                print("   Will request new authorization...")
                creds = None
        
        if not creds:  # Need new authorization
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"❌ Credentials file not found at {CREDENTIALS_FILE}\n"
                    "Please download from Google Cloud Console."
                )
            
            print("🔐 Starting OAuth flow...")
            print("📢 A browser window will open. Please:")
            print("   1. Sign in with your Google account")
            print("   2. Click 'Continue' on the unverified app warning")
            print("   3. Verify these 2 permissions:")
            print("      ✓ Google Drive access")
            print("      ✓ Gmail access")
            print("   4. Click 'Allow'\n")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            
            # Force consent screen even if previously approved
            creds = flow.run_local_server(
                port=0, 
                open_browser=True,
                authorization_prompt_message='',
                success_message='✅ Authentication successful! You can close this window.',
                prompt='consent'
            )
        
        print("💾 Saving credentials...")
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        
        # Verify scopes were granted
        print("\n🔍 Verifying granted scopes...")
        if creds.scopes:
            print("✅ Token has these scopes:")
            for scope in creds.scopes:
                scope_name = scope.split('/')[-1]
                if scope_name == 'drive':
                    print(f"   ✓ {scope_name}")
                else:
                    print(f"   ✓ mail")
            
            # Check for required scopes
            has_drive = any('drive' in s for s in creds.scopes)
            has_gmail = any('mail.google.com' in s for s in creds.scopes)
            
            if not has_drive:
                print("\n⚠️  WARNING: Drive scope missing!")
            if not has_gmail:
                print("\n⚠️  WARNING: Gmail scope missing!")
        else:
            print("⚠️  Could not verify scopes in token")
    
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
        service = get_drive_service()
        
        results = service.files().list(
            pageSize=5, 
            fields="files(id, name, mimeType, size)"
        ).execute()
        files = results.get('files', [])
        
        print("✅ Drive API Connected!")
        if files:
            print(f"   Found {len(files)} sample files:")
            for file in files:
                size = int(file.get('size', 0)) if file.get('size') else 0
                size_mb = size / (1024 * 1024)
                print(f"     • {file['name']} ({size_mb:.2f} MB)")
        else:
            print("   No files found (empty Drive)")
        return True
    except Exception as e:
        print(f"❌ Drive API Error: {e}")
        return False


def test_gmail_connection():
    """Test Gmail API connection."""
    print("\n📧 Testing Gmail API connection...")
    try:
        service = get_gmail_service()
        
        profile = service.users().getProfile(userId='me').execute()
        
        print("✅ Gmail API Connected!")
        print(f"   Email: {profile['emailAddress']}")
        print(f"   Total messages: {profile.get('messagesTotal', 0):,}")
        print(f"   Threads: {profile.get('threadsTotal', 0):,}")
        
        # Get storage info
        storage_mb = profile.get('emailUsedQuota', 0)
        if storage_mb:
            storage_mb = int(storage_mb) / (1024 * 1024)
            print(f"   Storage used: {storage_mb:.2f} MB")
        
        return True
    except Exception as e:
        print(f"❌ Gmail API Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print(f"🔐 {PROJECT_NAME} - Authentication Test")
    print("=" * 60)
    
    try:
        # Test both APIs
        drive_ok = test_drive_connection()
        gmail_ok = test_gmail_connection()
        
        print("\n" + "=" * 60)
        
        if drive_ok and gmail_ok:
            print("🎉 All authentication tests passed!")
            print(f"✅ Token saved to: {TOKEN_FILE}")
            print("\n👉 Next steps:")
            print("   1. Find Drive duplicates:")
            print("      python cli.py drive-duplicates")
            print("")
            print("   2. Clean up Gmail:")
            print("      python cli.py gmail-clean")
            print("")
            print("   3. Launch web UI:")
            print("      streamlit run streamlit_app.py")
        else:
            print("⚠️  Some tests failed. Please check errors above.")
            print("\n🔧 Troubleshooting:")
            if not drive_ok:
                print("   • Drive API: Enable in Google Cloud Console")
            if not gmail_ok:
                print("   • Gmail API: Enable in Google Cloud Console")
            print("   • Delete token.json and run auth.py again")
        
        print("=" * 60)
        
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ Authentication Error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()