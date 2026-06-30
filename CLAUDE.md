# StocksDetails

Portfolio tracker that imports holdings from E*Trade (via OAuth) and Fidelity (via CSV) and provides visualizations, analytics, and transaction history.

## Start the app

```bash
cd /workspaces/StocksDetails/backend
uvicorn main:app --reload --port 8000
```

Access at the Codespaces forwarded URL for port 8000 (make port Public in the Ports tab).

## Stack

- **Backend**: FastAPI (`backend/main.py`), Python 3.12
- **Frontend**: Single-page vanilla JS + Tailwind CSS + ApexCharts (`frontend/index.html`), served by FastAPI
- **Auth/DB**: Supabase (Postgres + Row Level Security + JWT auth)
- **Data**: pyetrade (E*Trade API), yfinance (price history/sector data), CSV parsing for Fidelity

## Environment variables (`.env`)

```
ETRADE_CONSUMER_KEY=
ETRADE_CONSUMER_SECRET=
SUPABASE_URL=
SUPABASE_SERVICE_KEY=   # service-role key, server-side only
```

The frontend hardcodes `SUPABASE_URL` and `SUPABASE_ANON_KEY` directly in `index.html` (lines ~179-180).

## Database (Supabase)

Run `schema.sql` in the Supabase SQL editor to create all tables. All tables have RLS — users only see their own rows.

| Table | Purpose |
|---|---|
| `etrade_connections` | OAuth tokens per user (one row, upserted) |
| `fidelity_positions` | CSV positions snapshot, replaced on each upload |
| `fidelity_realized_gains` | Realized gain/loss CSV, **merged** on upload (deduped on `user_id, symbol, date_sold, proceeds`) |
| `fidelity_dividends` | Dividend/income history CSV, **merged** on upload (deduped on `user_id, symbol, run_date, amount`) |

E*Trade transactions are fetched live from the API (not stored).

## Backend — key files

### `backend/main.py` — all API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Serves `frontend/index.html` |
| `GET /status` | ETrade + Fidelity connection status |
| `GET /auth/etrade/connect` | Start OAuth flow → returns `session_id` + `auth_url` |
| `POST /auth/etrade/verify` | Exchange verifier code for tokens, store in DB |
| `DELETE /auth/etrade/disconnect` | Delete stored tokens |
| `POST /fidelity/upload` | Upload positions CSV |
| `POST /fidelity/upload/realized-gains` | Upload realized gains CSV |
| `POST /fidelity/upload/dividends` | Upload dividends/income CSV |
| `GET /positions` | Combined ETrade + Fidelity positions |
| `GET /transactions` | ETrade live + Fidelity realized gains + dividends |
| `GET /analytics/performance?days=365` | Daily portfolio value via yfinance |
| `GET /analytics/sectors` | Holdings grouped by GICS sector via yfinance |
| `GET /analytics/sparkline?symbol=X` | 30-day price history for hover popup |
| `GET /analytics/exchange?symbol=X` | Resolves Google Finance URL with exchange suffix |

**Token expiry handling**: when ETrade returns 401, the backend auto-deletes the stale tokens and returns `{"error": "...", "reconnect": true}`. The frontend sees this flag, calls `loadStatus()`, and shows the "Connect E*Trade" button.

### `backend/etrade.py`

- `start_oauth()` / `complete_oauth(session_id, verifier)` — OAuth flow
- `get_positions(token, secret, env)` — all positions across all accounts
- `get_transactions(token, secret, env)` — up to 2 years of transaction history

### `backend/fidelity.py`

- `parse_fidelity_csv(content)` — positions export
- `parse_fidelity_realized_gains(content)` — gain/loss export
- `parse_fidelity_dividends(content)` — activity history filtered to income

All parsers use dynamic header detection (search for key column names) to handle Fidelity's preamble/footer rows. `None`-safe via `(row.get(key) or "")` pattern.

### `backend/db.py`

`get_supabase()` returns a service-role Supabase client. `verify_jwt(token)` validates user JWTs.

## Frontend — `frontend/index.html`

Single HTML file, all JS inline. Key globals:

| Global | Set by | Used by |
|---|---|---|
| `window._allPositions` | `loadPositions()` | filter reset |
| `window._positions` | `loadPositions()` / `setPosFilter()` | analytics, summary |
| `window._allTransactions` | `loadTransactions()` | filter reset |
| `window._transactions` | `loadTransactions()` / `setTxnFilter()` | analytics, summary |
| `_charts` | chart renderers | `destroyChart()` before re-render |
| `_sparklineCache` | `showSparkline()` | avoids repeat API calls |
| `_exchangeMap` | `openFinance()` | avoids repeat exchange lookups |

### Key JS functions

- `loadPositions()` / `loadTransactions()` — fetch from API, set globals, render
- `renderPosTable(positions)` / `renderTxnTable(txns)` — render table + summary bar
- `setPosFilter(account)` / `setTxnFilter(account)` — account filter, re-renders table
- `renderAnalytics()` — renders all 6 analytics charts (calls each renderer)
- `toggleSection(id)` — collapse/expand cards with CSS grid animation
- `openFinance(symbol)` — resolves exchange via `/analytics/exchange`, opens Google Finance
- `hoverSymbol(e, symbol)` / `showSparkline(e, symbol)` / `hideSparkline()` — 30-day sparkline popup on symbol hover (350ms delay, cached)

### Analytics charts (ApexCharts)

1. **Allocation** — donut, by broker or by symbol (toggle). Click slice → Google Finance.
2. **Winners & Losers** — horizontal bars, top/bottom 5 by gain %. Click bar → Google Finance. Hover → sparkline.
3. **Performance** — area chart, portfolio value vs cost basis over time (fetches `/analytics/performance`).
4. **Dividend Income** — monthly column chart from transaction history.
5. **Realized vs Unrealized** — horizontal bars: unrealized, realized, dividends.
6. **Concentration Risk** — horizontal bars by position size %, orange >15%, red >25%. Click bar → Google Finance. Hover → sparkline.

All analytics cards animate in with a staggered `slideUp` CSS animation.

## Fidelity CSV exports

| Type | Path in Fidelity |
|---|---|
| Positions | Accounts → Portfolio → Download → As Displayed (CSV) |
| Realized Gains | Accounts → Tax Forms & Information → Realized Gain/Loss → Export to Spreadsheet |
| Dividends | Accounts → Activity & Orders → History → set Type = Dividends → Download |

## E*Trade status

- Current keys in `.env` are **sandbox** credentials
- Production (live) access requires separate keys — apply at developer.etrade.com → My Applications → Request Production Access
- The app is designed for potential limited commercial use; ETrade production approval requires ToS/privacy policy URLs

## Schema migrations

When adding new constraints to existing tables, use a `DO` block — PostgreSQL does not support `ADD CONSTRAINT IF NOT EXISTS`:

```sql
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'constraint_name') then
    alter table my_table add constraint constraint_name unique (...);
  end if;
end $$;
```

## Planned features

See **[ToDo.md](./ToDo.md)** for the full backlog with implementation notes.

## Known issues / future work

- `analysis/` directory (`portfolio_history.py`, `portfolio_history.png`) is not committed — gitignore patterns may have line-ending issues
- ETrade live 401s on reconnect: the backend deletes tokens and flags `reconnect: true`, but the user must go through full OAuth again (ETrade tokens expire daily)
- Performance chart uses current quantity × historical price (approximation — doesn't account for trades made during the period)
- Sector data from yfinance can be slow (one HTTP call per symbol); no caching
