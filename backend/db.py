from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")  # service-role key — server side only
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(url, key)


def verify_jwt(token: str) -> str:
    """Verify a Supabase user JWT and return the user_id."""
    client = get_supabase()
    user = client.auth.get_user(token)
    return user.user.id
