# Canada Market + CDR + Account-Type Support — Design

- **Date:** 2026-06-26
- **Repo:** `kwedmon/tsx_daily_stock_analysis` (fork of `ZhuLinsen/daily_stock_analysis`)
- **Status:** Approved direction; revised after four code-review rounds (v5). Reviewer confirms ready for implementation plan. Pending plan.
- **Deployment context:** Original app already deployed via Docker on host `tkcloud` (Tailscale), WebUI at `http://tkcloud:8200`, DeepSeek `deepseek-v4-pro`, Telegram push-only.

> **v2 changes (post-review #1):** (1) Corrected CDR FX semantics — CDR currency is CAD and uses the *generic* `currency → base_currency` conversion; the only thing to avoid is treating CDR as a USD asset. (2) Added a **Security Context resolver** contract; `detect_market` stays string-only. (3) Tier 3 redirection specified per data-type (price vs fundamentals vs news vs persistence vs prompt) with cache/attribution rules. (4) CDR ratio is store/display only — not used in portfolio cost/return this round. Plus: exhaustive market-enum checklist, account-grouping clarification, missing-FX incompleteness handling, seed versioning, expanded tests.
>
> **v3 changes (post-review #2):** (1) Fixed the **missing-CDR-mapping** contract — `fundamental_symbol = None` / `resolution_status = cdr_unmapped`; fundamentals return explicit `unavailable_mapping`, adapter never receives `.NE` (the prior `fundamental = .NE` fallback would re-enter the offshore yfinance path now that `ca` is gated there). (2) Made the **missing-FX** contract concrete — discriminate by `_convert_amount` `reason` (`fallback_1_to_1` = not converted), exclude from totals, additive API fields. (3) Locked persistence: no portfolio columns (resolve on read), single `FundamentalSnapshot.source_symbol` column for attribution. (4) Resolver purity — returns `resolution_status`/`reason`, caller logs. (5) Seed `version`/`generated_at` file-level, `effective_from` per-entry.
>
> **v4 changes (post-review #3):** Completed the **missing-FX valuation-completeness contract** (§ Tier 1) — it now spans the data model and *all* conversion paths, not just positions. Use a `base_valuation_available` **flag** (mirroring existing `price_available`) instead of nullable columns; cover cash/equity/realized/fees/taxes (all ~12 `_convert_amount` sites), generalize to `excluded_valuation_count` + component-typed `valuation_errors`, and define cross-account portfolio aggregation for incomplete accounts. Clarified Analysis-History attribution lives in its existing JSON payload (no new column). Fixed seed metadata wording in §3 and the section title to v3+.
>
> **v5 changes (post-review #4):** Extended the missing-FX contract to **downstream risk** — `portfolio_risk_service.py` converts exposure at `:286`/`:342`/`:488` and discards `reason`; it must now skip `base_valuation_available=false` positions and exclude its own `fallback_1_to_1` conversions, so the account snapshot and risk concentration share the same valuable-position set (regression test added). Clarified persistence: `base_valuation_available` is a `NOT NULL DEFAULT true` column; `base_valuation_reason` lives in the API/snapshot JSON only (no column). Reworded §7 "compatible defaults".

## 1. Motivation

Add Canadian-market coverage for a Canadian investor:

1. **TSX / TSX Venture common stocks** (`.TO` / `.V`) — currently mis-detected as US.
2. **CDRs** (Canadian Depositary Receipts, `.NE` on Cboe Canada) — CAD-priced, CAD-hedged wrappers over US companies; issued by CIBC (~100+ names).
3. **Portfolio** correctness for a Canadian household: CAD + USD positions in one account, plus Canadian **account types** (RRSP / TFSA / FHSA / …).

## 2. Goals / Non-Goals

**Goals**
- Recognize and analyze `.TO`, `.V`, and `.NE` symbols through the existing single-stock analysis, history, and report pipeline.
- For CDRs: use the CDR's CAD market price for quote/portfolio value, but source **fundamentals, valuation, financials, and news from the underlying US stock**.
- Portfolio: complete the CAD/USD multi-currency valuation that JP/KR/TW MVPs deferred; add an `account_type` label.
- Keep the generic part (Canadian market MVP) **contributable upstream**; keep Canada-niche parts (CDR, account types) isolated on the fork as a **thin seam** (new files + minimal additive edits) so upstream stays mergeable.

**Non-Goals (this spec)**
- No tax-aware analysis from account type — `account_type` is a **label only** this round.
- No CDR ratio in portfolio P&L; no underlying-USD→CDR-CAD target-price translation (involves hedge mechanics) — deferred.
- No real-time data guarantees; Yahoo delays/missing fields accepted (same disclaimer as JP/KR/TW).
- No market-registry refactor (conflicts with upstream's additive pattern + minimal-diff rules).
- No interactive Telegram bot (separately dropped).

## 3. Key Decisions (locked, v5)

1. **Instrument identity via a resolver, not `detect_market`.** `detect_market(symbol) -> str` stays backward-compatible (returns `"ca"` for `.TO`/`.V`/`.NE`). A new **`resolve_security_context(symbol) -> SecurityContext`** carries the per-data-type identity (see §5). All CDR-aware behavior reads the context — no scattered `.NE` parsing.
2. **CDR FX:** a CDR's `trading_currency`/`position.currency` is **always `CAD`**. Valuation uses the existing generic `currency → account.base_currency` path (`portfolio_service._convert_amount`, see `portfolio_service.py:~1003`). **No CDR FX special-case.** The only rule: never tag a CDR as USD. (CAD-base account → no-op; USD/CNY-base account → CAD converts normally.)
3. **CDR data routing (per data-type):** price/technical/history → CDR `.NE`; fundamentals/valuation/financials → underlying US; news/sentiment → underlying symbol + name; persistence/report identity → `.NE` as primary key with recorded source symbol; prompt → Canadian-wrapper context **plus** US-underlying-company context (not a wholesale switch to the US prompt).
4. **CDR ratio:** store + display only this round. Portfolio cost/current/return computed directly from CDR share count × CAD price. Ratio is for underlying-metric mapping and explanation only; target-price translation deferred.
5. **CDR mapping source:** checked-in versioned seed — **file-level** `version`/`generated_at`/`source`, **per-entry** `underlying` + `ratio` + `effective_from` — plus a `scripts/` refresh generator from CIBC. Deterministic, offline-runnable, matches `stock_index_seeds`.
6. **Account type:** generic nullable `account_type` field; Canadian options surfaced when `market = ca`; label/grouping only (group **accounts** by type — one type per account).
7. **Maintainability posture:** contribute the common part upstream, personalize on the fork; thin seam throughout. Sequencing easy → hard (Tier 0 → Tier 4), with the Security Context resolver as the foundation that CDR (Tier 2/3) depends on.

## 4. Codebase Grounding (verified)

- **Market detection:** `src/market_context.py:detect_market` returns a bare string; ordered regex with US fallback `^[A-Z]{1,5}(\.[A-Z]{1,2})?$` currently captures `TD.TO`, `SHOP.TO`, even `AAPL.NE` as `us`. New `.TO`/`.V`/`.NE` rules MUST precede it.
- **Portfolio valuation (`portfolio_service.py:~1003`):** converts `position.currency → account.base_currency` via `_convert_amount`, tracking an `fx_stale` flag; when price unavailable, base values are zeroed. Confirms the generic FX path already exists.
- **Pipeline entry points are separate:** fundamentals via `fetcher_manager.get_fundamental_context(code, …)` (`pipeline.py:~478`); news via `search_service.search_comprehensive_intel(stock_code=code, stock_name=stock_name, …)` (`pipeline.py:~558`). Both use the raw input `code`/`name`. Redirection must substitute per data-type.
- **Offshore fundamental gate (`data_provider/base.py:2971`):** `if market in {"us","hk","jp","kr","tw"}: _build_offshore_fundamental_context(...)` — `ca` absent; plain `.TO`/`.V` need `ca` added here (Tier 0) or fundamentals fall to the A-share path.
- **Fetcher capability (`data_provider/base.py:632`):** `YfinanceFetcher: {"cn","hk","us","jp","kr","tw"}` — add `ca`.
- **Migrations:** `Base.metadata.create_all` (new tables only) + hand-rolled `schema_migrations` + idempotent `ALTER TABLE`/`PRAGMA table_info` repair in `storage.py`. New columns follow this.
- **yfinance verified from deployment:** `AAPL.NE` → CAD/NEO ~40; `SHOP.TO`/`TD.TO` → CAD/TOR. `AAPL.NE` fundamentals carry the underlying business summary but **distorted** marketCap/PE (5.94T/41.6 vs real 4.17T/34.4) — fundamentals must come from the underlying ticker.

## 5. Security Context Resolver (foundation for CDR)

New module (e.g. `src/markets/security_context.py`), a pure function with no behavioral coupling:

```
SecurityContext:
  input_symbol:        e.g. "AAPL.NE"
  market:              "ca"
  instrument_type:     "equity" | "cdr" | "etf" | ...
  quote_symbol:        price/technical/history     → "AAPL.NE"
  fundamental_symbol:  fundamentals/valuation       → "AAPL"
  news_symbol:         news/sentiment ticker        → "AAPL"
  news_name:           news/sentiment display name  → underlying company name
  trading_currency:    "CAD"
  underlying_symbol:   "AAPL" (None for non-CDR)
  ratio:               CDR ratio (None for non-CDR)
  resolution_status:   "ok" | "cdr_unmapped" | ...
  reason:              human-readable status reason (for the caller to log)
  source:              provenance (seed version, etc.)
```

- **Purity:** the resolver is a pure function — it **does not log**. It sets `resolution_status`/`reason`; the **caller** logs. (Resolves the prior "pure function … and log" contradiction.)
- **Non-CDR (incl. plain `.TO`/`.V`, and all existing markets):** `quote = fundamental = news = input_symbol`; `instrument_type = equity/etf`; `trading_currency` from market; `resolution_status = ok`.
- **CDR (`.NE`), mapped:** `instrument_type = cdr`, `quote = .NE`, `fundamental = news = underlying`, `trading_currency = CAD`; `underlying`/`ratio` from the seed (§6 Tier 3); `resolution_status = ok`.
- **CDR (`.NE`), mapping missing:** `instrument_type = cdr`, `quote = .NE` (price/history/technical still work), **`fundamental_symbol = None` and `news_symbol = None`**, `resolution_status = cdr_unmapped`. The fundamental adapter must **never** receive `.NE`; the fundamental/valuation stage returns an explicit `unavailable_mapping`/`not_supported`. News may fall back to the `.NE` name or skip — explicit, not silent. (This corrects the prior "fundamental = quote = .NE" fallback, which would have re-entered the offshore yfinance path — `ca` is now in that gate — and refetched the distorted `.NE` PE/marketCap.)
- The pipeline reads the context at each stage instead of threading raw `code`. This is the single seam that prevents price/fundamentals/news/prompt drift.

## 6. Two Streams & Per-Tier Design

### Stream U — upstream-bound (generic): Tier 0 only
Built to `AGENTS.md`: minimal additive diff, `./scripts/ci_gate.sh` green, `pytest -m "not network"`, update `docs/market-support.md` + `docs/CHANGELOG.md`, PR template, no tool prefixes. Branch `feature/ca-market` off `upstream/main`; excludes `docs/superpowers/**`.

### Stream F — fork-only (thin seam): Tiers 1–4
New files preferred; existing-file edits 1–3 lines, additive. Stacked on Tier 0 locally; not blocked on upstream merge.

---

### Tier 0 — Canadian common stocks `.TO` / `.V` (Stream U)

**Detection:** add `.TO` (TSX) / `.V` (Venture) → `ca` before the US regex. Validate the base pattern against a real TSX symbol sample (units, classes, numeric/ETF, e.g. `ENB.TO`, `BAM.TO`, `XIU.TO`).

**Enum checklist — principle:** `jp/kr/tw` were added only to *offshore-equity* spots and deliberately left out of the `{cn,hk,us}`-only gates (market-light, alerts, risk). `ca` follows that precedent exactly.

*Add `ca` (wherever `jp/kr/tw` already appear):*
- `src/core/trading_calendar.py:39` `MARKET_EXCHANGE` → `ca:"XTSE"`; `:42` `MARKET_TIMEZONE` → `ca:"America/Toronto"`
- `data_provider/base.py:632` `YfinanceFetcher` caps; `:2971` offshore fundamental gate
- `src/services/portfolio_service.py` `VALID_MARKETS`
- `src/services/intelligence_service.py:31` `_ALLOWED_MARKETS`
- `src/core/pipeline.py:1471` and `src/market_phase_summary.py:145` offshore `{jp,kr,tw}` branches
- API Literals: `api/v1/schemas/portfolio.py` (×4), `api/v1/schemas/decision_signals.py:19`, `api/v1/schemas/intelligence.py:12`; Query descriptions `api/v1/endpoints/decision_signals.py:126,309`; error string `src/services/decision_signal_service.py:869`
- `src/market_context.py:20` docstring; `apps/dsa-web` market type/filter

*Leave `ca` OUT this tier (deferred features = Tier 4+, matching jp/kr/tw):* `analyzer.py:192`, `alert_worker.py:447`, `portfolio_risk_service.py:189`, `market_light_service.py:20` + `src/schemas/market_light.py:11`, `agent/tools/market_tools.py:53`, `core/config_registry.py:3337` — all `{cn,hk,us}`-only.

**Prompt:** Canadian market role/semantics in `market_context.py` (CAD, TSX rules; no A-share 涨跌停/北向/龙虎榜), TW-block style.
**Routing:** Canadian symbols via `YfinanceFetcher`; A-share-only blocks degrade `not_supported`.
**Tests:** detection (`.TO`/`.V`→ca; bare codes unaffected; `.NE` not yet ca here unless Tier 2 merged); enum/calendar; mocked offshore fundamental routing. Offline.
**Docs:** Canada section in `docs/market-support.md`; CHANGELOG.

### Tier 1 — Portfolio CAD/USD口径 + account type (Stream F)
**Multi-currency completion for `ca`:** ensure `ca` positions get `valuation_currency` and `market_value_base` via the generic `_convert_amount` (`USDCAD=X` auto-fetch already exists); CAD+USD positions in one account aggregate to `base_currency`. Confirm import/entry per-row currency (`币种/货币` already parsed).
**Missing-FX valuation-completeness contract.** A **general multi-currency correctness contract** (not Canada-specific), surfaced because Canadian CAD+USD accounts are the first real multi-currency use case. It spans the data model, *all* conversion paths, and aggregation.

- *Discriminator.* `_convert_amount` keeps its signature `(value, is_stale, reason)`, `reason ∈ {zero, identity, direct_rate, inverse_rate, fallback_1_to_1}`. `direct_rate`/`inverse_rate` + `is_stale=True` = converted but stale (usable). `fallback_1_to_1` = **not converted** (original-currency amount returned) — a failure. Every `_convert_amount` site must inspect `reason` (currently all ~12 sites discard it): positions (`portfolio_service.py:1005,1011`) **and** account-level cash/equity/realized/unrealized/fee/tax (`:498-534`, `:828-845`).
- *Representation — flag, not null (reasoned deviation from the review's null suggestion).* Mirror the existing `price_available`/`price_stale` pattern (`api/v1/schemas/portfolio.py:167-168`): keep base columns `float` and add a boolean flag, rather than nulling `market_value_base`/`unrealized_pnl_base`. Rationale: avoids a NOT NULL→nullable migration (`storage.py:592-593`), the `float(item[...])` coercion (`portfolio_repo.py:905`), and an API `float`→`Optional[float]` change that could break web clients. A flagged-unavailable base value is `0.0` and **excluded** from totals — unambiguous when paired with the flag.
- *Position level.* When the market-value **or** cost conversion is `fallback_1_to_1`, the position is flagged unavailable and `market_value_base`/`unrealized_pnl_base`/`unrealized_pnl_pct` are excluded from totals. Persistence: `base_valuation_available` is a new **`NOT NULL DEFAULT true`** column on `PortfolioPosition` (parallel to `market_value_base`); `base_valuation_reason` is **not** a column — it is surfaced in the API/valuation response and snapshot JSON only. Sync DB/repo/API/web for the flag (additive, compatible default; no nullability change to existing columns).
- *Account level (all components).* Positions **and** cash, equity, realized P&L, fees, taxes each exclude any `fallback_1_to_1` component from its subtotal. Response gains additive fields: `valuation_complete: bool`, `excluded_valuation_count: int` (positions + non-position components), `valuation_errors: [{component, symbol?, from_currency, reason}]`, `component ∈ {position, cash, equity, realized_pnl, fee, tax}`. Defaults: `complete=true`, `0`, `[]` — backward-compatible; single-currency / rate-available accounts unaffected.
- *Portfolio level (cross-account).* An incomplete account propagates `valuation_complete=false` upward. The portfolio total **never** 1:1-converts an account's partial/un-converted subtotal across to the portfolio base; it sums only convertible components and is flagged incomplete when any account is.
- *Downstream consumers (risk).* The contract covers **all `convert_amount()` callers, not just the in-class `_convert_amount` sites.** `portfolio_risk_service.py` independently converts exposure (`:286`, `:342`, `:488`) and discards `reason`; left as-is, a missing rate would 1:1-count a position into concentration/sector exposure that the account snapshot already excluded, producing inconsistent risk weights. Required: the risk service (a) **skips positions flagged `base_valuation_available=false`**, and (b) on its own `fallback_1_to_1` (e.g. base→CNY rate missing), excludes that exposure and surfaces `valuation_complete=false` / a coverage error. The account snapshot and risk concentration must use the **same valuable-position set**.
- *Implementation note.* Centralize the `reason` check in one helper (e.g. `convert_for_valuation() -> (value, available, reason)`) used at every site (valuation **and** risk), so the rule is uniform and the seam stays thin. Do **not** rely on the conflated `fx_stale` flag.
**Account type:** (detailed executable plan: `docs/superpowers/plans/2026-06-27-account-types.md`)
- `PortfolioAccount.account_type` — new nullable `String(32)`; idempotent `ALTER TABLE` column backfill mirroring `_ensure_llm_usage_telemetry_columns`. **No `schema_migrations` bump** — column backfills in this codebase do not write a version record (`CURRENT_SCHEMA_VERSION` is a create-all baseline); the earlier "bump" wording was incorrect.
- New module `src/portfolio/account_types.py` with the option set; Canadian set when `market=ca`: `rrsp, tfsa, fhsa, rrif, resp, lira, rdsp, non_registered_cash, non_registered_margin` (extensible). Advisory free-string (any non-empty value kept, normalized `strip().lower()`, empty→None) to avoid breaking other markets.
- API schema (Create/Update/Item): create forwards `account_type`; update is **presence-aware** (`model_fields_set`) so an explicit `null` clears and an omitted field preserves.
- `apps/dsa-web`: account **create** exposes the dropdown (when ca) + grouped selector (`<optgroup>` by type, untyped last) + card display. **Web account-edit UI scope is an OPEN DECISION** (pending user confirmation): either (a) keep design — add `portfolioApi.updateAccount()` + edit form + component test, or (b) user confirms deferral and this note + CHANGELOG record the follow-up work item. Backend update is fully editable via API regardless. Web custom-value input is likewise pending that decision. No tax logic.
**Tests:** USD-base account holding CAD+USD positions aggregates correctly; missing-FX marks incomplete (no silent mix); migration idempotency; account_type round-trip.

### Tier 2 — Security Context resolver + CDR `.NE` detection + CAD pricing (Stream F)
- Implement §5 resolver; `detect_market` adds `^[A-Z]{1,6}\.NE$` → `ca` (before US regex). CDR detected; `instrument_type=cdr`; underlying resolution inert until Tier 3 seed lands (degrade to price-only).
- Quote/price/market value use `.NE` CAD price. **Portfolio: CDR `position.currency = CAD`, no special-case** — the generic FX path handles CAD→base.
- **Persistence (locked, minimal):** resolve `is_cdr`/`underlying` **on read** via the resolver for portfolio display — **no new portfolio (`trade`/`position`) columns** for MVP (deterministic from symbol). The single persisted attribution column is `FundamentalSnapshot.source_symbol` (Tier 3). Add per-table columns only if a concrete read-path need appears.
- Prompt: add a "CAD-hedged depositary receipt" wrapper note (full underlying context arrives in Tier 3).
**Tests:** `.NE` → ca + `instrument_type=cdr`; **USD-base account holding a CDR converts CAD→USD correctly (not skipped, not treated as USD)**; price uses `.NE`.

### Tier 3 — CDR fundamentals/news → underlying (Stream F)
- **Seed:** `data/seeds/cdr_map.json` = **file-level** metadata `{version, generated_at, source}` + **per-entry** `{underlying, ratio, name, effective_from}` (`generated_at`/`version` belong to the file, not each entry; `effective_from` is per-entry so historical reports stay explainable). `scripts/refresh_cdr_map.py` from CIBC. Loader with cache.
- **Redirection (via SecurityContext):** fundamentals (`pipeline.py:478`) use `context.fundamental_symbol`; news (`pipeline.py:558`) use `context.news_symbol`/`news_name`; price/technical keep `context.quote_symbol`. If `fundamental_symbol is None` (`cdr_unmapped`), the fundamental stage short-circuits to `unavailable_mapping`/`not_supported` and **never** calls the adapter with `.NE`. Run analysis with the dual prompt context. Avoids distorted `.NE` marketCap/PE.
- **Cache & attribution (locked):** fundamental/news cache keys key on the *source* symbol (underlying). `FundamentalSnapshot` gets a new nullable **`source_symbol`** column (additive migration): `code` stays the report identity (`.NE`), `source_symbol` records the symbol actually fetched (`AAPL`). (Column chosen over payload-embedding for queryability; existing `source_chain` records data-source provenance and is complementary.) **Analysis History** records the source symbol inside its **existing JSON payload** (no new column) — so `FundamentalSnapshot.source_symbol` remains the *only* new persisted column.
- **Ratio:** stored/displayed only (per-CDR underlying-share exposure, ratio-change explanation); **not** applied to cost/return.
**Tests:** mapping load + versioning; `AAPL.NE` routes fundamentals→`AAPL`, news→`AAPL`/name, price stays `.NE`; cache isolation between `AAPL` and `AAPL.NE`; snapshot attribution records source; missing-mapping degrades to price-only `ca`; ratio-change handled by seed.

### Tier 4 — Autocomplete seeds + Canadian market review (Stream F)
- `scripts/stock_index_seeds/` Canadian + CDR seeds; web autocomplete放行.
- Canadian index/market review via `^GSPTSE`; extend the `{cn,hk,us}`-only market-light/region/alerts spots to `ca` here (the gates Tier 0 deliberately skipped). Lowest early value; may be split.

## 7. Cross-Cutting Concerns

- **Degradation:** unknown-market calendar fail-open; missing FX → mark incomplete (do not fold un-converted into base totals); missing CDR mapping → price-only `ca`, logged. Single data-source/notification failures never abort the main pipeline.
- **Backward compatibility:** all enum/schema changes additive; **new columns have compatible defaults** — `base_valuation_available` is `NOT NULL DEFAULT true`, `FundamentalSnapshot.source_symbol` is nullable; existing cn/hk/us/jp/kr/tw behavior unchanged; `detect_market` signature unchanged.
- **Security/secrets:** `.env` fork-local and gitignored; upstream branch excludes `docs/superpowers/**` and deployment specifics.

## 8. Git / Contribution Workflow

```
upstream/main
  └─ feature/ca-market        (Stream U)  → PR to ZhuLinsen/daily_stock_analysis
        └─ feature/security-context → feature/cdr, feature/account-types  (Stream F) → fork only
```
- Develop Stream F on top of Tier 0 locally; do not block on upstream merge. If upstream merges (possibly changed), rebase onto `upstream/main`; if not, Tier 0 stays in the fork.
- Small logical commits for clean rebases; `git fetch upstream && git rebase upstream/main` periodically. Push only on explicit request.

## 9. Risks / Open Items

- TSX symbol shape edge cases — validate regex against a real sample before finalizing Tier 0.
- CIBC list machine-readability — confirm a programmatic/downloadable source for `refresh_cdr_map.py`; fall back to a curated seed if only HTML.
- CDR ratio changes over time — seed carries `effective_from`/`version` so historical reports stay explainable.
- Upstream acceptance of Tier 0 uncertain — Tier 0 must stay self-sufficient in the fork regardless.

## 10. Testing Strategy

Per tier, mirror the TW PR: offline unit tests for detection/enums/calendar; mocked data routing; `pytest -m "not network"` must pass. Required additions:
- USD-base account holding a CDR → CAD→base conversion correct (not skipped, not treated as USD).
- **Missing-FX:** a `fallback_1_to_1` position is flagged `base_valuation_available=false`, zeroed, and excluded from totals; the account reports `valuation_complete=false` + `excluded_valuation_count ≥ 1`. Also assert a `fallback_1_to_1` **foreign-currency cash** balance is excluded (`component=cash`) and never 1:1-summed into a USD/CNY total, and that an incomplete account propagates incompleteness to the portfolio-level total.
- **Snapshot/risk consistency:** account snapshot and risk concentration/sector weights use the **same valuable-position set** — a `base_valuation_available=false` position is absent from both; a risk-service `fallback_1_to_1` (e.g. CAD→CNY rate missing) is excluded from exposure with `valuation_complete=false`/coverage error, never 1:1-counted.
- **CDR fundamentals adapter never receives `.NE`** — for both mapped (gets underlying) and unmapped (gets nothing; stage returns `unavailable_mapping`) CDRs.
- CDR vs underlying fundamental/news **cache isolation**; `FundamentalSnapshot.source_symbol` records the fetched symbol while `code` stays `.NE`.
- Ratio change handled via seed `effective_from`; ratio absent from portfolio P&L.
- News/fundamentals route on the underlying symbol/name for mapped CDRs.

Network checks (live Yahoo, CIBC refresh) are observational, not gating.
