-- ============================================================
-- StocksDetails — Supabase migration
-- Run this in the Supabase SQL editor for your project.
-- ============================================================

-- E*Trade OAuth tokens, one row per user
create table if not exists etrade_connections (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid references auth.users(id) on delete cascade not null,
  oauth_token         text not null,
  oauth_token_secret  text not null,
  env                 text not null default 'live',  -- 'live' or 'sandbox'
  connected_at        timestamptz default now(),
  unique(user_id)
);

alter table etrade_connections enable row level security;

create policy "etrade: own rows only"
  on etrade_connections for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Fidelity positions uploaded via CSV (replaced on each upload)
create table if not exists fidelity_positions (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid references auth.users(id) on delete cascade not null,
  account_name        text,
  symbol              text not null,
  description         text,
  quantity            numeric,
  last_price          numeric,
  last_price_change   numeric,
  current_value       numeric,
  cost_basis_total    numeric,
  total_gain_loss     numeric,
  total_gain_loss_pct numeric,
  uploaded_at         timestamptz default now()
);

alter table fidelity_positions enable row level security;

create policy "fidelity: own rows only"
  on fidelity_positions for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Fidelity realized gains (from Fidelity's Gain/Loss CSV export)
create table if not exists fidelity_realized_gains (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid references auth.users(id) on delete cascade not null,
  symbol        text not null,
  description   text,
  quantity      numeric,
  date_acquired text,
  date_sold     text,
  proceeds      numeric,
  cost_basis    numeric,
  realized_gain numeric,
  uploaded_at   timestamptz default now(),
  unique (user_id, symbol, date_sold, proceeds)
);

alter table fidelity_realized_gains enable row level security;

create policy "fidelity_realized_gains: own rows only"
  on fidelity_realized_gains for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Fidelity dividends (from Fidelity's activity history CSV, filtered to income)
create table if not exists fidelity_dividends (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid references auth.users(id) on delete cascade not null,
  run_date         date,
  symbol           text,
  description      text,
  amount           numeric,
  transaction_type text,
  uploaded_at      timestamptz default now(),
  unique (user_id, symbol, run_date, amount)
);

alter table fidelity_dividends enable row level security;

create policy "fidelity_dividends: own rows only"
  on fidelity_dividends for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ============================================================
-- Migration: add dedup constraints to existing tables
-- Run this if the tables already exist without the constraints.
-- ============================================================
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'fidelity_realized_gains_dedup') then
    alter table fidelity_realized_gains
      add constraint fidelity_realized_gains_dedup
      unique (user_id, symbol, date_sold, proceeds);
  end if;
end $$;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'fidelity_dividends_dedup') then
    alter table fidelity_dividends
      add constraint fidelity_dividends_dedup
      unique (user_id, symbol, run_date, amount);
  end if;
end $$;
