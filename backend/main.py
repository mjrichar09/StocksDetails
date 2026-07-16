"""StocksDetails API — FastAPI backend."""

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import re
import time

import yfinance as yf
import pandas as pd

from db import get_supabase, verify_jwt
from etrade import start_oauth, complete_oauth, get_positions as etrade_positions, get_transactions as etrade_transactions
from fidelity import parse_fidelity_csv, parse_fidelity_realized_gains, parse_fidelity_dividends

app = FastAPI(title="StocksDetails")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ─── Auth dependency ──────────────────────────────────────────────────────────

def current_user(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    try:
        return verify_jwt(authorization[7:])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ─── E*Trade OAuth ────────────────────────────────────────────────────────────

@app.get("/auth/etrade/connect")
def etrade_connect(user_id: str = Depends(current_user)):
    """Start E*Trade OAuth. Returns session_id + auth_url for the user to visit."""
    session_id, auth_url = start_oauth()
    return {"session_id": session_id, "auth_url": auth_url}


class VerifyBody(BaseModel):
    session_id: str
    verifier: str
    env: str = "live"  # "live" or "sandbox"


@app.post("/auth/etrade/verify")
def etrade_verify(body: VerifyBody, user_id: str = Depends(current_user)):
    """Complete OAuth: exchange verifier for tokens and persist them."""
    try:
        tokens = complete_oauth(body.session_id, body.verifier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    get_supabase().table("etrade_connections").upsert(
        {
            "user_id":             user_id,
            "oauth_token":         tokens["oauth_token"],
            "oauth_token_secret":  tokens["oauth_token_secret"],
            "env":                 body.env,
        },
        on_conflict="user_id",
    ).execute()

    _invalidate_user_cache(user_id)
    return {"status": "connected"}


@app.delete("/auth/etrade/disconnect")
def etrade_disconnect(user_id: str = Depends(current_user)):
    get_supabase().table("etrade_connections").delete().eq("user_id", user_id).execute()
    _invalidate_user_cache(user_id)
    return {"status": "disconnected"}


# ─── Fidelity CSV Upload ──────────────────────────────────────────────────────

@app.post("/fidelity/upload")
async def fidelity_upload(
    file: UploadFile = File(...),
    user_id: str = Depends(current_user),
):
    content = await file.read()
    positions = parse_fidelity_csv(content)
    if not positions:
        raise HTTPException(status_code=400, detail="No positions found — check CSV format")

    db = get_supabase()
    db.table("fidelity_positions").delete().eq("user_id", user_id).execute()
    db.table("fidelity_positions").insert(
        [{**p, "user_id": user_id} for p in positions]
    ).execute()

    _invalidate_user_cache(user_id)
    return {"status": "ok", "imported": len(positions)}


# ─── Positions ────────────────────────────────────────────────────────────────

@app.get("/positions")
def get_all_positions(user_id: str = Depends(current_user)):
    """Return combined positions from E*Trade and Fidelity for this user."""
    db = get_supabase()
    result = []

    # E*Trade
    conn = db.table("etrade_connections").select("*").eq("user_id", user_id).execute()
    if conn.data:
        c = conn.data[0]
        try:
            result.extend(etrade_positions(c["oauth_token"], c["oauth_token_secret"], c["env"]))
        except Exception as e:
            err_str = str(e)
            # Expired/revoked tokens return 401 — delete them so the UI shows reconnect
            if "401" in err_str or "unauthorized" in err_str.lower():
                db.table("etrade_connections").delete().eq("user_id", user_id).execute()
                result.append({"source": "etrade", "error": "Token expired — please reconnect", "reconnect": True})
            else:
                result.append({"source": "etrade", "error": err_str})

    # Fidelity
    rows = db.table("fidelity_positions").select("*").eq("user_id", user_id).execute()
    for r in rows.data:
        result.append({
            "source":        "fidelity",
            "account":       r.get("account_name"),
            "symbol":        r["symbol"],
            "description":   r.get("description"),
            "quantity":      r.get("quantity"),
            "last_price":    r.get("last_price"),
            "market_value":  r.get("current_value"),
            "cost_basis":    r.get("cost_basis_total"),
            "gain_loss":     r.get("total_gain_loss"),
            "gain_loss_pct": r.get("total_gain_loss_pct"),
        })

    return result


@app.get("/transactions")
def get_all_transactions(user_id: str = Depends(current_user)):
    """Return combined transaction history (ETrade + Fidelity realized gains + dividends)."""
    db = get_supabase()
    result = []

    # ETrade transactions (fetched live)
    conn = db.table("etrade_connections").select("*").eq("user_id", user_id).execute()
    if conn.data:
        c = conn.data[0]
        try:
            for t in etrade_transactions(c["oauth_token"], c["oauth_token_secret"], c["env"]):
                result.append({"source": "etrade", **t})
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "unauthorized" in err_str.lower():
                db.table("etrade_connections").delete().eq("user_id", user_id).execute()
                result.append({"source": "etrade", "error": "Token expired — please reconnect", "reconnect": True})
            else:
                result.append({"source": "etrade", "error": err_str})

    # Fidelity realized gains
    rg = db.table("fidelity_realized_gains").select("*").eq("user_id", user_id).execute()
    for r in rg.data:
        result.append({
            "source":           "fidelity",
            "transaction_type": "sell",
            "symbol":           r["symbol"],
            "description":      r.get("description"),
            "quantity":         r.get("quantity"),
            "transaction_date": r.get("date_sold"),
            "date_acquired":    r.get("date_acquired"),
            "amount":           r.get("proceeds"),
            "cost_basis":       r.get("cost_basis"),
            "realized_gain":    r.get("realized_gain"),
        })

    # Fidelity dividends
    div = db.table("fidelity_dividends").select("*").eq("user_id", user_id).execute()
    for r in div.data:
        result.append({
            "source":           "fidelity",
            "transaction_type": r.get("transaction_type", "dividend"),
            "symbol":           r.get("symbol"),
            "description":      r.get("description"),
            "transaction_date": str(r["run_date"]) if r.get("run_date") else None,
            "amount":           r.get("amount"),
        })

    return result


@app.post("/fidelity/upload/realized-gains")
async def fidelity_upload_realized_gains(
    file: UploadFile = File(...),
    user_id: str = Depends(current_user),
):
    content = await file.read()
    rows = parse_fidelity_realized_gains(content)
    if not rows:
        raise HTTPException(status_code=400, detail="No realized gains found — check CSV format")
    db = get_supabase()
    db.table("fidelity_realized_gains").upsert(
        [{**r, "user_id": user_id} for r in rows],
        on_conflict="user_id,symbol,date_sold,proceeds"
    ).execute()
    return {"status": "ok", "imported": len(rows)}


@app.post("/fidelity/upload/dividends")
async def fidelity_upload_dividends(
    file: UploadFile = File(...),
    user_id: str = Depends(current_user),
):
    content = await file.read()
    rows = parse_fidelity_dividends(content)
    if not rows:
        raise HTTPException(status_code=400, detail="No dividends found — check CSV format")
    db = get_supabase()
    db.table("fidelity_dividends").upsert(
        [{**r, "user_id": user_id} for r in rows],
        on_conflict="user_id,symbol,run_date,amount"
    ).execute()
    return {"status": "ok", "imported": len(rows)}


# ─── Analytics ────────────────────────────────────────────────────────────────

_CASH_RE = re.compile(r"^(SPAXX|FCASH|FDRXX|FZFXX|VMFXX|\*\*|\d+).*", re.IGNORECASE)

# Simple in-memory TTL cache for yfinance-backed endpoints (one process, personal use)
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: int, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _invalidate_user_cache(user_id: str):
    """Drop cached analytics for a user after their holdings change."""
    for k in list(_cache):
        if f":{user_id}" in k:
            del _cache[k]


def _gather_positions(user_id: str, db):
    """Return merged {symbol: {"quantity": float, "market_value": float, "cost_basis": float}} dict."""
    merged: dict[str, dict] = {}

    def add(symbol, quantity, market_value, cost_basis):
        if not symbol or _CASH_RE.match(symbol):
            return
        if symbol not in merged:
            merged[symbol] = {"quantity": 0.0, "market_value": 0.0, "cost_basis": 0.0}
        merged[symbol]["quantity"]    += float(quantity    or 0)
        merged[symbol]["market_value"] += float(market_value or 0)
        merged[symbol]["cost_basis"]  += float(cost_basis  or 0)

    # Fidelity
    rows = db.table("fidelity_positions").select("*").eq("user_id", user_id).execute()
    for r in rows.data:
        add(r["symbol"], r.get("quantity"), r.get("current_value"), r.get("cost_basis_total"))

    # ETrade
    conn = db.table("etrade_connections").select("*").eq("user_id", user_id).execute()
    if conn.data:
        c = conn.data[0]
        try:
            for p in etrade_positions(c["oauth_token"], c["oauth_token_secret"], c["env"]):
                add(p["symbol"], p.get("quantity"), p.get("market_value"), p.get("cost_basis"))
        except Exception:
            pass

    return merged


@app.get("/analytics/performance")
def analytics_performance(days: int = Query(365, ge=1, le=730), user_id: str = Depends(current_user)):
    """Portfolio value over time using yfinance historical prices."""
    return _cached(f"performance:{user_id}:{days}", 3600, lambda: _compute_performance(user_id, days))


def _compute_performance(user_id: str, days: int):
    try:
        db = get_supabase()
        positions = _gather_positions(user_id, db)
        if not positions:
            return {"dates": [], "portfolio_values": [], "cost_basis": 0.0}

        symbols = list(positions.keys())
        cost_basis = sum(v["cost_basis"] for v in positions.values())

        raw = yf.download(symbols, period=f"{days}d", interval="1d",
                          auto_adjust=True, progress=False)["Close"]
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(name=symbols[0])

        dates, values = [], []
        for date, row in raw.iterrows():
            total = sum(
                row[sym] * positions[sym]["quantity"]
                for sym in symbols
                if sym in row.index and not pd.isna(row[sym])
            )
            dates.append(str(date.date()))
            values.append(round(total, 2))

        return {"dates": dates, "portfolio_values": values, "cost_basis": round(cost_basis, 2)}
    except Exception:
        return {"dates": [], "portfolio_values": [], "cost_basis": 0.0}


@app.get("/analytics/sectors")
def analytics_sectors(user_id: str = Depends(current_user)):
    """Portfolio allocation by GICS sector via yfinance."""
    return _cached(f"sectors:{user_id}", 86400, lambda: _compute_sectors(user_id))


def _compute_sectors(user_id: str):
    try:
        db = get_supabase()
        positions = _gather_positions(user_id, db)
        if not positions:
            return []

        sector_data: dict[str, dict] = {}
        for symbol in list(positions.keys())[:20]:
            try:
                sector = yf.Ticker(symbol).info.get("sector") or "Other"
            except Exception:
                sector = "Other"
            mv = positions[symbol]["market_value"]
            if sector not in sector_data:
                sector_data[sector] = {"value": 0.0, "symbols": []}
            sector_data[sector]["value"]   += mv
            sector_data[sector]["symbols"].append(symbol)

        total = sum(v["value"] for v in sector_data.values()) or 1.0
        result = [
            {"sector": s, "value": round(v["value"], 2),
             "pct": round(v["value"] / total * 100, 1), "symbols": v["symbols"]}
            for s, v in sector_data.items()
        ]
        return sorted(result, key=lambda x: x["value"], reverse=True)
    except Exception:
        return []


@app.get("/analytics/sparkline")
def analytics_sparkline(symbol: str = Query(...), user_id: str = Depends(current_user)):
    """Return 30-day daily close prices for a symbol."""
    return _cached(f"sparkline:{symbol}", 3600, lambda: _compute_sparkline(symbol))


def _compute_sparkline(symbol: str):
    try:
        hist = yf.download(symbol, period="30d", interval="1d", auto_adjust=True, progress=False)["Close"]
        if hasattr(hist, "squeeze"):
            hist = hist.squeeze()
        if hist.empty:
            return {"symbol": symbol, "prices": [], "change_pct": 0, "current_price": None}
        prices = [round(float(p), 2) for p in hist.values if not pd.isna(p)]
        if len(prices) < 2:
            return {"symbol": symbol, "prices": prices, "change_pct": 0, "current_price": prices[-1] if prices else None}
        change_pct = round((prices[-1] - prices[0]) / prices[0] * 100, 2)
        return {"symbol": symbol, "prices": prices, "change_pct": change_pct, "current_price": prices[-1]}
    except Exception:
        return {"symbol": symbol, "prices": [], "change_pct": 0, "current_price": None}


# yfinance exchange code → Google Finance exchange suffix
_GF_EXCHANGE: dict[str, str] = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
    "NYQ": "NYSE",
    "PCX": "NYSEARCA",
    "ASE": "NYSEAMERICAN",
    "OBB": "OTCMKTS", "PNK": "OTCMKTS", "NIM": "OTCMKTS",
    "TSX": "TSX", "TOR": "TSX",
}


@app.get("/analytics/exchange")
def analytics_exchange(symbol: str = Query(...), user_id: str = Depends(current_user)):
    """Return the Google Finance URL for a symbol by resolving its exchange via yfinance."""
    return _cached(f"exchange:{symbol}", 86400, lambda: _compute_exchange(symbol))


def _compute_exchange(symbol: str):
    try:
        info = yf.Ticker(symbol).fast_info
        raw = getattr(info, "exchange", None) or ""
        exchange = _GF_EXCHANGE.get(raw, raw)
        if exchange:
            url = f"https://www.google.com/finance/quote/{symbol}:{exchange}"
        else:
            url = f"https://www.google.com/finance/quote/{symbol}"
        return {"symbol": symbol, "exchange": exchange, "url": url}
    except Exception:
        return {"symbol": symbol, "exchange": "", "url": f"https://www.google.com/finance/quote/{symbol}"}


@app.get("/status")
def connection_status(user_id: str = Depends(current_user)):
    """Return broker connection status for this user."""
    db = get_supabase()
    etrade = db.table("etrade_connections").select("env,connected_at").eq("user_id", user_id).execute()
    fidelity = db.table("fidelity_positions").select("uploaded_at").eq("user_id", user_id).limit(1).execute()

    return {
        "etrade": {
            "connected":    bool(etrade.data),
            "env":          etrade.data[0]["env"] if etrade.data else None,
            "connected_at": etrade.data[0]["connected_at"] if etrade.data else None,
        },
        "fidelity": {
            "connected":   bool(fidelity.data),
            "last_upload": fidelity.data[0]["uploaded_at"] if fidelity.data else None,
        },
    }
