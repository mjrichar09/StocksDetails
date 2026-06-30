"""E*Trade OAuth and positions — stateless server wrapper around pyetrade."""

import uuid
from datetime import datetime
import pyetrade
from dotenv import load_dotenv
import os

load_dotenv()

CONSUMER_KEY = os.getenv("ETRADE_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("ETRADE_CONSUMER_SECRET")

# In-memory store: session_id → ETradeOAuth object.
# Works for a single-process server; swap for Redis in a multi-worker deployment.
_sessions: dict[str, pyetrade.ETradeOAuth] = {}


def start_oauth() -> tuple[str, str]:
    """Begin OAuth flow. Returns (session_id, auth_url)."""
    oauth = pyetrade.ETradeOAuth(CONSUMER_KEY, CONSUMER_SECRET)
    auth_url = oauth.get_request_token()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = oauth
    return session_id, auth_url


def complete_oauth(session_id: str, verifier: str) -> dict:
    """Exchange verifier for access tokens. Consumes the session."""
    oauth = _sessions.pop(session_id, None)
    if oauth is None:
        raise ValueError("Unknown or expired OAuth session")
    tokens = oauth.get_access_token(verifier)
    return tokens  # {"oauth_token": ..., "oauth_token_secret": ...}


def get_positions(oauth_token: str, oauth_token_secret: str, env: str = "live") -> list[dict]:
    """Fetch all positions across all accounts for a user."""
    use_sandbox = env != "live"
    api = pyetrade.ETradeAccounts(
        CONSUMER_KEY, CONSUMER_SECRET,
        oauth_token, oauth_token_secret,
        dev=use_sandbox,
    )

    accounts_resp = api.list_accounts(resp_format="json")
    accounts = accounts_resp["AccountListResponse"]["Accounts"]["Account"]

    positions = []
    for account in accounts:
        key = account["accountIdKey"]
        name = account.get("accountName") or account.get("accountDesc", "Account")

        resp = api.get_account_portfolio(
            key, resp_format="json", totals_required=True, view="COMPLETE"
        )
        if "PortfolioResponse" not in resp:
            continue

        port = resp["PortfolioResponse"]
        for ap in port.get("AccountPortfolio", []):
            for pos in ap.get("Position", []):
                symbol = (
                    pos.get("symbolDescription")
                    or pos.get("Product", {}).get("symbol", "?")
                )
                positions.append({
                    "source":        "etrade",
                    "account":       name,
                    "symbol":        symbol,
                    "description":   pos.get("Product", {}).get("securityType"),
                    "quantity":      pos.get("quantity", 0),
                    "last_price":    pos.get("Quick", {}).get("lastTrade") or pos.get("pricePaid", 0),
                    "market_value":  pos.get("marketValue", 0),
                    "cost_basis":    pos.get("totalCost", 0),
                    "gain_loss":     pos.get("totalGain", 0),
                    "gain_loss_pct": pos.get("totalGainPct", 0),
                })

    return positions


def get_transactions(oauth_token: str, oauth_token_secret: str, env: str = "live") -> list[dict]:
    """Fetch up to 2 years of transaction history across all accounts."""
    use_sandbox = env != "live"
    api = pyetrade.ETradeAccounts(
        CONSUMER_KEY, CONSUMER_SECRET,
        oauth_token, oauth_token_secret,
        dev=use_sandbox,
    )

    accounts_resp = api.list_accounts(resp_format="json")
    accounts = accounts_resp["AccountListResponse"]["Accounts"]["Account"]

    transactions = []
    for account in accounts:
        key = account["accountIdKey"]
        name = account.get("accountName") or account.get("accountDesc", "Account")

        resp = api.list_transactions(key, resp_format="json", count=250)
        if not resp or "TransactionListResponse" not in resp:
            continue

        txn_list = resp["TransactionListResponse"].get("Transaction", [])
        if isinstance(txn_list, dict):
            txn_list = [txn_list]

        for txn in txn_list:
            brokerage = txn.get("brokerage") or {}
            product = brokerage.get("product") or {}

            ts = txn.get("transactionDate")
            txn_date = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else None

            transactions.append({
                "account":          name,
                "transaction_id":   str(txn.get("transactionId", "")),
                "transaction_date": txn_date,
                "transaction_type": (txn.get("transactionType") or "").lower(),
                "symbol":           product.get("symbol") or "",
                "description":      txn.get("description") or "",
                "quantity":         brokerage.get("quantity"),
                "price":            brokerage.get("price"),
                "amount":           txn.get("amount"),
            })

    return transactions
