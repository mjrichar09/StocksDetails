"""Parse Fidelity portfolio CSV exports."""

import csv
import io
import re


def _parse_number(val: str) -> float | None:
    if not val:
        return None
    cleaned = val.strip().replace("$", "").replace(",", "").replace("%", "")
    if cleaned in ("--", "n/a", "N/A", ""):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_fidelity_csv(content: bytes) -> list[dict]:
    """
    Parse a Fidelity portfolio export CSV.

    Fidelity includes a preamble and footer outside the data block; this
    function locates the header row dynamically so it handles format variations.
    """
    text = content.decode("utf-8-sig")  # strip BOM if present
    lines = text.splitlines()

    # Find the header row (contains "Symbol" and "Quantity")
    header_idx = None
    for i, line in enumerate(lines):
        if "Symbol" in line and "Quantity" in line:
            header_idx = i
            break

    if header_idx is None:
        return []

    csv_block = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_block))

    def get(row, key):
        return row.get(key) or ""

    positions = []
    for row in reader:
        symbol = get(row, "Symbol").strip().strip('"')

        # Skip blank rows, cash rows, and Fidelity summary lines
        if not symbol or symbol.startswith("**") or symbol == "Pending Activity":
            continue
        # Skip rows that are clearly totals/footers
        if re.match(r"^(Total|Account Total)", symbol, re.IGNORECASE):
            continue

        positions.append({
            "account_name":        get(row, "Account Name").strip().strip('"') or None,
            "symbol":              symbol,
            "description":         get(row, "Description").strip() or None,
            "quantity":            _parse_number(get(row, "Quantity")),
            "last_price":          _parse_number(get(row, "Last Price")),
            "last_price_change":   _parse_number(get(row, "Last Price Change")),
            "current_value":       _parse_number(get(row, "Current Value")),
            "cost_basis_total":    _parse_number(get(row, "Cost Basis Total")),
            "total_gain_loss":     _parse_number(get(row, "Total Gain/Loss Dollar")),
            "total_gain_loss_pct": _parse_number(get(row, "Total Gain/Loss Percent")),
        })

    return positions


def _find_header(lines: list[str], *required_cols: str) -> int | None:
    """Return index of the first line containing all required_cols."""
    for i, line in enumerate(lines):
        if all(col in line for col in required_cols):
            return i
    return None


def parse_fidelity_realized_gains(content: bytes) -> list[dict]:
    """
    Parse a Fidelity Realized Gains/Losses CSV export.
    Expected columns: Symbol, Quantity, Open Date, Close Date, Proceeds, Cost Basis, Gain/Loss
    """
    text = content.decode("utf-8-sig")
    lines = text.splitlines()

    header_idx = _find_header(lines, "Symbol", "Proceeds")
    if header_idx is None:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))

    def get(row, key):
        return row.get(key) or ""

    rows = []
    for row in reader:
        symbol = get(row, "Symbol").strip().strip('"')
        if not symbol or symbol.startswith("**") or re.match(r"^(Total|Grand Total)", symbol, re.IGNORECASE):
            continue

        rows.append({
            "symbol":        symbol,
            "description":   get(row, "Description").strip() or get(row, "Security Description").strip() or None,
            "quantity":      _parse_number(get(row, "Quantity")),
            "date_acquired": get(row, "Open Date").strip() or get(row, "Date Acquired").strip() or None,
            "date_sold":     get(row, "Close Date").strip() or get(row, "Date Sold").strip() or None,
            "proceeds":      _parse_number(get(row, "Proceeds")),
            "cost_basis":    _parse_number(get(row, "Cost Basis")),
            "realized_gain": _parse_number(get(row, "Gain/Loss")) or _parse_number(get(row, "Realized Gain/Loss")),
        })

    return rows


def parse_fidelity_dividends(content: bytes) -> list[dict]:
    """
    Parse a Fidelity activity history CSV filtered to dividend/income entries.
    Expected columns: Run Date, Symbol, Security Description, Amount ($), Action
    """
    text = content.decode("utf-8-sig")
    lines = text.splitlines()

    header_idx = _find_header(lines, "Run Date", "Amount")
    if header_idx is None:
        header_idx = _find_header(lines, "Date", "Amount")
    if header_idx is None:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))

    def get(row, key):
        return row.get(key) or ""

    INCOME_TYPES = {"dividend", "div reinvest", "interest", "capital gain", "return of capital"}

    rows = []
    for row in reader:
        action = get(row, "Action").strip().lower()
        # If Action column exists, only keep income-type rows
        if action and not any(t in action for t in INCOME_TYPES):
            continue

        raw_date = get(row, "Run Date").strip() or get(row, "Date").strip()
        try:
            from datetime import datetime as dt
            run_date = dt.strptime(raw_date, "%m/%d/%Y").strftime("%Y-%m-%d") if raw_date else None
        except ValueError:
            run_date = raw_date or None

        amount = _parse_number(get(row, "Amount ($)")) or _parse_number(get(row, "Amount"))
        if amount is None:
            continue

        symbol = get(row, "Symbol").strip().strip('"') or None
        rows.append({
            "run_date":        run_date,
            "symbol":          symbol,
            "description":     get(row, "Security Description").strip() or get(row, "Description").strip() or None,
            "amount":          amount,
            "transaction_type": action or "dividend",
        })

    return rows
