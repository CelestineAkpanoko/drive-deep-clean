import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project metadata
PROJECT_NAME = "Google Storage Cleanup Suite"
VERSION = "1.0.0"

# Base directory
BASE_DIR = Path(__file__).parent

# Google OAuth Scopes - ONLY Drive and Gmail
SCOPES = [
    'https://www.googleapis.com/auth/drive',  # Full Drive access
    'https://mail.google.com/'                 # Full Gmail access
]

# Credentials
CREDENTIALS_FILE = BASE_DIR / 'credentials.json'
TOKEN_FILE = BASE_DIR / 'token.json'

# Directories
KNOWN_FACES_DIR = BASE_DIR / 'known_faces'
KNOWN_FACES_DIR.mkdir(exist_ok=True)

DOWNLOADS_DIR = BASE_DIR / 'downloads'
DOWNLOADS_DIR.mkdir(exist_ok=True)

TEMP_DIR = BASE_DIR / 'temp'
TEMP_DIR.mkdir(exist_ok=True)

DUPLICATES_DUMP_DIR = BASE_DIR / 'duplicates_dump'  # NEW: For dumping duplicates
DUPLICATES_DUMP_DIR.mkdir(exist_ok=True)

# Settings
MIN_FILE_SIZE_MB = int(os.getenv('MIN_FILE_SIZE_MB', 5))
MIN_FILE_SIZE_BYTES = MIN_FILE_SIZE_MB * 1024 * 1024

# Face recognition settings
FACE_RECOGNITION_TOLERANCE = float(os.getenv('FACE_RECOGNITION_TOLERANCE', 0.6))

# Duplicate detection settings
SIMILARITY_THRESHOLD = float(os.getenv('SIMILARITY_THRESHOLD', 0.95))  # For image similarity
BATCH_SIZE = int(os.getenv('BATCH_SIZE', 100))  # Files to process at once

# Gmail settings
GMAIL_BATCH_DELETE_SIZE = int(os.getenv('GMAIL_BATCH_DELETE_SIZE', 100))
GMAIL_CATEGORIES_TO_CLEAN = os.getenv(
    'GMAIL_CATEGORIES_TO_CLEAN', 
    'SPAM,CATEGORY_PROMOTIONS,CATEGORY_SOCIAL'
).split(',')

# Optional: OpenAI/Groq API keys (for advanced features)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# File types
IMAGE_MIMETYPES = [
    'image/jpeg', 'image/jpg', 'image/png', 
    'image/gif', 'image/bmp', 'image/webp', 'image/heic'
]

VIDEO_MIMETYPES = [
    'video/mp4', 'video/mpeg', 'video/quicktime',
    'video/x-msvideo', 'video/x-matroska', 'video/webm'
]

DOCUMENT_MIMETYPES = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]

print(f"✅ {PROJECT_NAME} v{VERSION} - Config loaded")