# StocksDetails — To Do

## 1. Data Quality / Correctness

- [ ] Verify ETrade cost basis mapping — the API returns it but confirm it's being passed through correctly in `etrade.py` `get_positions()`
- [ ] Fix performance chart accuracy — currently uses current quantity × historical price, which is wrong if trades occurred during the period. Proper fix: snapshot positions to DB on each load and reconstruct historical value from snapshots
- [ ] Short vs long-term gain split — determine hold period per realized gain (>1 year = long-term, lower tax rate) and surface it in the Transactions table and Realized vs Unrealized chart

## 2. Notes per Position

Allow users to attach a note/thesis to any holding. Show notes inline in the Positions table.

**Implementation:**
- New Supabase table: `position_notes (user_id, symbol, note, updated_at)` with RLS
- New endpoints: `PUT /notes/:symbol`, `GET /notes`
- Inline edit UI in the Positions table — click a note icon on any row to open a small textarea
- Pre-populate textarea with prompt suggestions, e.g.:
  - "Why do you own this?"
  - "What's your price target?"
  - "What would make you sell?"
  - "Any risks to watch?"

## 3. Target Allocation + Drift

Let users define a desired % allocation per symbol or sector, then show actual vs target.

**Implementation:**
- New Supabase table: `target_allocations (user_id, symbol, target_pct)` with RLS
- UI to set targets (editable inline in the Positions table or a dedicated modal)
- Update Concentration Risk chart to show a second "target" bar alongside actual, or a drift indicator (e.g. +3.2% over target in red, -1.5% under target in orange)
- Summary stat: "X positions outside target by >2%"

## 4. Price Alerts

Notify the user when a symbol crosses a price threshold they set.

**Implementation:**
- New Supabase table: `price_alerts (user_id, symbol, condition, target_price, triggered_at, active)` with RLS
- Conditions: above / below
- Check alerts on each `/positions` load — compare last_price to target, mark triggered if crossed
- Show a banner or toast on the app screen if any alerts are triggered
- UI to add/remove alerts from the Positions table row (small bell icon)
- Stretch: email notification via Supabase Edge Functions + SMTP

## 5. Analytics Depth

### Sector Breakdown Chart
- Backend endpoint `/analytics/sectors` already exists but has no chart
- Add a donut or horizontal bar chart to the Analytics section showing allocation by GICS sector
- Click a sector to filter the Positions table to that sector

### Tax Estimate
- Use realized gains already in the DB + short/long-term split (see item 1)
- Show estimated federal cap gains tax for the current year (use standard 0/15/20% long-term brackets)
- Display as a card in the Analytics section — not financial advice, just an estimate

### Dividend Calendar
- Show projected monthly dividend income based on current holdings + historical dividend frequency from yfinance
- Highlight months with no dividend income
- Show projected annual total

### Beta / Volatility
- Fetch beta from `yf.Ticker(symbol).info["beta"]` for each holding
- Compute weighted portfolio beta (sum of weight × beta)
- Add to Analytics: portfolio beta card + per-position beta column in Positions table (toggleable)

## 6. Dark / Light Mode Toggle

- Add a sun/moon toggle button in the header
- Store preference in `localStorage`
- CSS: define a `.light` class on `<body>` that overrides the dark color variables
- Toggle `body.classList.toggle('light')` on click

## 7. Last Refreshed Timestamp

- Show a small "Last updated: Jun 30, 2026 at 2:34 PM" label in the Positions and Transactions card headers
- Set it after each successful `loadPositions()` / `loadTransactions()` call
- Style: muted text next to the Refresh button

## 8. Loading Skeletons

Replace the plain "Loading…" text with animated skeleton placeholders.

**Implementation:**
- CSS: `.skeleton { background: linear-gradient(90deg, #1e293b 25%, #334155 50%, #1e293b 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; }` and `@keyframes shimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }`
- Positions: show 5–8 skeleton rows (3 columns wide) while loading
- Transactions: same
- Analytics charts: show a skeleton rectangle the same height as each chart container while fetching
