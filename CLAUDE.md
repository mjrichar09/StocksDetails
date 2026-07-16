# StocksDetails

Portfolio tracker that imports holdings from E*Trade (via OAuth) and Fidelity (via CSV) and provides visualizations, analytics, and transaction history.

## Start the app

Windows (local, venv at repo root — created 2026-07):

```powershell
cd C:\Users\markyjas\Repositories\StocksDetails\backend
..\.venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

Codespaces:

```bash
cd /workspaces/StocksDetails/backend
uvicorn main:app --reload --port 8000
```

Access at the Codespaces forwarded URL for port 8000 (make port Public in the Ports tab). **The AI chat feature only works locally** — it rides the machine's Claude Code login.

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
HYSA_APY=0.045          # optional — cash benchmark for /analytics/real-returns
BLS_API_KEY=            # optional — registered BLS v2 API (keyless v1 used otherwise)
```

**Never set `ANTHROPIC_API_KEY` here** — the chat feature uses Claude Code subscription auth, and a set key would silently switch it to pay-per-token API billing (`chat.py` scrubs it defensively).

The frontend hardcodes `SUPABASE_URL` and `SUPABASE_ANON_KEY` directly in `index.html` (lines ~179-180).

## Database (Supabase)

Run `schema.sql` in the Supabase SQL editor to create all tables. All tables have RLS — users only see their own rows.

| Table | Purpose |
|---|---|
| `etrade_connections` | OAuth tokens per user (one row, upserted) |
| `fidelity_positions` | CSV positions snapshot, replaced on each upload |
| `fidelity_realized_gains` | Realized gain/loss CSV, **merged** on upload (deduped on `user_id, symbol, date_sold, proceeds`) |
| `fidelity_dividends` | Dividend/income history CSV, **merged** on upload (deduped on `user_id, symbol, run_date, amount`) |
| `position_acquisitions` | Purchase date per (user, symbol) — `source` is `manual` or `etrade_inferred`; manual wins |
| `cpi_monthly` | Global BLS CPI series (no per-user rows; RLS with no policies = service-role only) |

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
| `GET /analytics/real-returns` | Per-holding annualized return vs CPI/SPY/HYSA; dateless holdings in `needs_date` |
| `GET /analytics/beta` | Weighted portfolio beta via yfinance |
| `GET/PUT /acquisitions[/{symbol}]` | Read/set purchase dates |
| `POST /acquisitions/infer` | Infer dates from E*Trade buy history (never overwrites manual) |
| `POST /chat` | AI portfolio chat (SSE stream; Claude Agent SDK, local-only) |

All yfinance-backed endpoints go through `_cached(key, ttl, fn)` (in-memory TTL cache in `main.py`), invalidated per-user via `_invalidate_user_cache` when holdings change.

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

### `backend/cpi.py`

BLS CPI fetch (series `CUUR0000SA0`) stored in `cpi_monthly`. `ensure_cpi(db)` refreshes at most ~monthly (throttled by `fetched_at` — CPI publishes ~6 weeks late); `cpi_at(series, date)` does nearest-earlier-month lookup. FRED fallback documented in the module docstring.

### `backend/chat.py`

Claude Agent SDK glue: `stream_chat(message, session_id, context)` yields `{"text": ...}` chunks then `{"done": True, "session_id"}`. Tool-less agent (`allowed_tools=[]`, `max_turns=1`), runs in a temp cwd, env scrubbed of `ANTHROPIC_API_KEY`. The portfolio snapshot is re-sent as system prompt every turn (kept per-session in `main.py`'s `_chat_sessions`), so resumed turns keep the original snapshot.

## Frontend — `frontend/index.html`

Single HTML file, all JS inline. **Two client-side tabs** (`setTab()`): **Dashboard** (broker cards, positions, transactions, the 6 quick charts) and **Evaluate** (Real Returns vs Benchmarks with inline needs-date entry, Realized vs Unrealized by Symbol, Sector donut, Dividend Yield on Cost, Portfolio Beta, Tax Estimate). Only the visible tab's charts render (ApexCharts sizes to 0 in hidden containers); `setTab` re-renders on switch. **Chat slide-over** (`toggleChat()`) is available from both tabs and streams `/chat` via `fetch` + `ReadableStream` (not `EventSource` — it can't send the Authorization header).

Key globals:

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

## Working preferences

- Claude commits and pushes automatically as work completes.
- **Doc-update cadence: batch, don't drip.** [ToDo.md](./ToDo.md) gets touched at feature completion or when a decision lands — not after every edit; CLAUDE.md only when a convention, structure, or preference actually changes. Code commits stay frequent — it's the *prose* that batches.
- Periodically archive: when ToDo.md's completed items outnumber the open ones, sweep the finished entries out (into the commit history / a status note) to keep it scannable.

## Working efficiently (session cost)

The whole transcript is re-sent every turn, so cost scales with session length and with heavy material kept in context. Without cutting rigor:

- Prefer targeted reads (Grep, or Read with offset/limit) over whole-file reads; don't re-read a file already in context, and don't re-read after an Edit just to confirm it (Edit fails loudly if it didn't apply).
- Don't take screenshots unless the user explicitly asks — verify programmatically instead (drive it headless and assert computed values / script output).
- Prefer Edit over re-emitting whole blocks; don't paste large code back into chat.
- Keep replies concise: briefly state what changed and the result, not a blow-by-blow of every step.
- `frontend/index.html` is one big inline-JS HTML file — reading the relevant region is fine; just don't read the whole file twice.

## Planned features

See **[ToDo.md](./ToDo.md)** for the full backlog with implementation notes.

## Known issues / future work

- AI chat is local-only (needs Claude Code logged in on the machine running the backend); chat sessions don't survive a server restart (`_chat_sessions` is in-memory)
- Real-returns uses one date per position — DCA'd positions get approximate annualized returns; E*Trade inference sees ~2yr/250 txns so the earliest visible buy may not be the true first lot
- `analysis/` directory (`portfolio_history.py`, `portfolio_history.png`) is not committed — gitignore patterns may have line-ending issues
- ETrade live 401s on reconnect: the backend deletes tokens and flags `reconnect: true`, but the user must go through full OAuth again (ETrade tokens expire daily)
- Performance chart uses current quantity × historical price (approximation — doesn't account for trades made during the period)
- Sector data from yfinance can be slow (one HTTP call per symbol); no caching
