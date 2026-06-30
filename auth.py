"""
E*Trade OAuth 1.0a authentication.

Flow:
  1. Fetches a request token from E*Trade
  2. Opens the authorization URL in your browser
  3. You paste back the verifier code E*Trade gives you
  4. Exchanges it for an access token and saves it to tokens.json
"""

import json
import webbrowser
from pathlib import Path

import pyetrade
from dotenv import load_dotenv
import os

load_dotenv()

CONSUMER_KEY = os.getenv("ETRADE_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("ETRADE_CONSUMER_SECRET")
ETRADE_ENV = os.getenv("ETRADE_ENV", "sandbox")  # "sandbox" or "live"
TOKENS_FILE = Path("tokens.json")


def login() -> dict:
    """Run the OAuth flow and return access tokens."""
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        raise ValueError(
            "Missing credentials. Copy .env.example to .env and fill in your keys."
        )

    use_sandbox = ETRADE_ENV != "live"

    oauth = pyetrade.ETradeOAuth(CONSUMER_KEY, CONSUMER_SECRET)
    auth_url = oauth.get_request_token()

    print(f"\nOpening E*Trade authorization page...")
    print(f"If it doesn't open automatically, go to:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    verifier = input("Paste the verifier code from E*Trade here: ").strip()

    tokens = oauth.get_access_token(verifier)

    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    print(f"\nAuthenticated successfully. Tokens saved to {TOKENS_FILE}.")
    return tokens


def load_tokens() -> dict | None:
    """Load saved tokens from disk, or return None if not found."""
    if TOKENS_FILE.exists():
        return json.loads(TOKENS_FILE.read_text())
    return None


def get_accounts_api():
    """Return an authenticated ETradeAccounts API client."""
    tokens = load_tokens()
    if not tokens:
        print("No saved tokens found — running login flow.")
        tokens = login()

    use_sandbox = ETRADE_ENV != "live"
    return pyetrade.ETradeAccounts(
        CONSUMER_KEY,
        CONSUMER_SECRET,
        tokens["oauth_token"],
        tokens["oauth_token_secret"],
        dev=use_sandbox,
    )


if __name__ == "__main__":
    login()
