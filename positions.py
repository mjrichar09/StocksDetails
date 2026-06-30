"""Fetch and display positions from all E*Trade accounts."""

from auth import get_accounts_api
import pyetrade
import json
from dotenv import load_dotenv
import os

load_dotenv()

CONSUMER_KEY = os.getenv("ETRADE_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("ETRADE_CONSUMER_SECRET")
ETRADE_ENV = os.getenv("ETRADE_ENV", "sandbox")


def get_api():
    tokens = json.loads(open("tokens.json").read())
    use_sandbox = ETRADE_ENV != "live"
    return pyetrade.ETradeAccounts(
        CONSUMER_KEY,
        CONSUMER_SECRET,
        tokens["oauth_token"],
        tokens["oauth_token_secret"],
        dev=use_sandbox,
    )


def print_positions():
    api = get_api()

    accounts_resp = api.list_accounts(resp_format="json")
    accounts = accounts_resp["AccountListResponse"]["Accounts"]["Account"]

    for account in accounts:
        key = account["accountIdKey"]
        name = account.get("accountName") or account.get("accountDesc", "Account")
        acct_num = account.get("accountId", "")
        print(f"\n{'='*50}")
        print(f"{name}  ({acct_num})")
        print(f"{'='*50}")

        portfolio_resp = api.get_account_portfolio(
            key, resp_format="json", totals_required=True, view="COMPLETE"
        )

        if "PortfolioResponse" not in portfolio_resp:
            print("  No positions found.")
            continue

        port = portfolio_resp["PortfolioResponse"]

        # Print totals if available
        totals = port.get("Totals")
        if totals:
            print(f"  Market Value:  ${totals.get('marketValue', 0):>12,.2f}")
            print(f"  Today's Gain:  ${totals.get('todaysGain', 0):>12,.2f}  "
                  f"({totals.get('todaysGainPct', 0):.2f}%)")
            print(f"  Total Gain:    ${totals.get('totalGain', 0):>12,.2f}  "
                  f"({totals.get('totalGainPct', 0):.2f}%)")

        print(f"\n  {'Symbol':<8} {'Qty':>8} {'Price':>10} {'Mkt Value':>12} "
              f"{'Cost Basis':>12} {'Gain/Loss':>12} {'Gain %':>8}")
        print(f"  {'-'*76}")

        positions = port.get("AccountPortfolio", [])
        for ap in positions:
            for pos in ap.get("Position", []):
                symbol = pos.get("symbolDescription") or pos.get("Product", {}).get("symbol", "?")
                qty = pos.get("quantity", 0)
                price = pos.get("Quick", {}).get("lastTrade", 0) or pos.get("pricePaid", 0)
                mkt_val = pos.get("marketValue", 0)
                cost = pos.get("totalCost", 0)
                gain = pos.get("totalGain", 0)
                gain_pct = pos.get("totalGainPct", 0)

                print(f"  {symbol:<8} {qty:>8,.2f} {price:>10,.2f} {mkt_val:>12,.2f} "
                      f"{cost:>12,.2f} {gain:>12,.2f} {gain_pct:>7.2f}%")


if __name__ == "__main__":
    print_positions()
