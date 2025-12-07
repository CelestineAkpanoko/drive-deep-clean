import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Google OAuth Scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://mail.google.com/'
]

# Credentials
CREDENTIALS_FILE = BASE_DIR / 'credentials.json'
TOKEN_FILE = BASE_DIR / 'token.json'

# Directories
KNOWN_FACES_DIR = BASE_DIR / 'known_faces'
KNOWN_FACES_DIR.mkdir(exist_ok=True)

DOWNLOADS_DIR = BASE_DIR / 'downloads'
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Settings
MIN_FILE_SIZE_MB = int(os.getenv('MIN_FILE_SIZE_MB', 5))
MIN_FILE_SIZE_BYTES = MIN_FILE_SIZE_MB * 1024 * 1024

print("✅ Config loaded successfully")