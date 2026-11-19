import os

from dotenv import load_dotenv

load_dotenv()

KEITARO_URL = os.getenv("KEITARO_URL", "https://tlgk.host").rstrip("/")
KEITARO_API_KEY = os.getenv("KEITARO_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
DEFAULT_DOMAIN_ID = int(os.getenv("DEFAULT_DOMAIN_ID", "0") or 0)
DEFAULT_GROUP_ID = int(os.getenv("DEFAULT_GROUP_ID", "0") or 0)
DEFAULT_SOURCE_ID = int(os.getenv("DEFAULT_SOURCE_ID", "0") or 0)
CAMPAIGN_PREFIX = os.getenv("CAMPAIGN_PREFIX", "")
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "")
