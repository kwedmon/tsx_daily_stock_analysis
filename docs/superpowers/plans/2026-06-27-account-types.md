# Stream F · Tier 1a — Account Types (label-only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic, nullable `account_type` label to portfolio accounts, surfacing Canadian options (RRSP/TFSA/FHSA/…) when `market = ca`. Store + display + group accounts by type. **No tax logic this round.**

**Architecture:** Thin, additive change across the existing account create/update chain: new `account_types` module → DB column (idempotent SQLite `ALTER TABLE`, mirroring `_ensure_llm_usage_telemetry_columns`) → repo/service passthrough → API schema (advisory free-string, not a `Literal`) → web form select + display. Fork-only (Stream F); builds on the merged Tier 0 `ca` market.

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, pytest; React/TS (`apps/dsa-web`, vitest).

## Global Constraints

- Branch: `feature/account-types` (already created off `feature/ca-market`; has Tier 0 code + spec). Commit messages English, no `Co-Authored-By`.
- **Commits require explicit user authorization** — run each task to "tests pass" then commit only if authorized.
- `account_type` is **advisory / free-string** (nullable, no `Literal` enum) so other markets and custom values are never blocked. Canadian known set (lowercase snake): `rrsp, tfsa, fhsa, rrif, resp, lira, rdsp, non_registered_cash, non_registered_margin`.
- New column: `account_type VARCHAR(32)` NULL on `portfolio_accounts`. Additive, backward-compatible.
- Tests run in the `dsa-test` Docker image (`= daily-stock-analysis-server:latest` + pytest), mounting the repo at `/app` — host has no python deps:
  `docker run --rm -v $PWD:/app -w /app --entrypoint python dsa-test -m pytest <path> -v`
- Reference: `docs/superpowers/specs/2026-06-26-canada-cdr-support-design.md` (§ Tier 1 account type).

---

### Task 1: `account_types` module (option set + helpers)

**Files:**
- Create: `src/portfolio/__init__.py` (if missing), `src/portfolio/account_types.py`
- Test: `tests/test_account_types.py` (new)

**Interfaces:**
- Produces: `account_types_for_market(market: str) -> list[str]`; `is_known_account_type(value: str) -> bool`; constant `CA_ACCOUNT_TYPES: list[str]`.

- [ ] **Step 1: Write the failing test** — `tests/test_account_types.py`:

```python
# -*- coding: utf-8 -*-
from src.portfolio.account_types import (
    CA_ACCOUNT_TYPES,
    account_types_for_market,
    is_known_account_type,
)


def test_canadian_account_types_listed_for_ca():
    opts = account_types_for_market("ca")
    assert opts == CA_ACCOUNT_TYPES
    for expected in ("rrsp", "tfsa", "fhsa", "non_registered_margin"):
        assert expected in opts


def test_non_ca_markets_have_no_predefined_types():
    assert account_types_for_market("us") == []
    assert account_types_for_market("cn") == []
    assert account_types_for_market("") == []


def test_is_known_account_type_is_case_insensitive_and_advisory():
    assert is_known_account_type("RRSP") is True
    assert is_known_account_type("tfsa") is True
    assert is_known_account_type("totally_custom") is False
```

- [ ] **Step 2: Run to verify it fails** — `... -m pytest tests/test_account_types.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** — `src/portfolio/account_types.py`:

```python
# -*- coding: utf-8 -*-
"""Account-type option sets per market (label-only; no tax logic).

Advisory: the model/API accept any non-empty string, so other markets and custom
values are never blocked. This module only supplies suggested options + display.
"""
from typing import Dict, List

# Canadian registered / non-registered account types (lowercase snake_case keys).
CA_ACCOUNT_TYPES: List[str] = [
    "rrsp",
    "tfsa",
    "fhsa",
    "rrif",
    "resp",
    "lira",
    "rdsp",
    "non_registered_cash",
    "non_registered_margin",
]

_ACCOUNT_TYPES_BY_MARKET: Dict[str, List[str]] = {
    "ca": CA_ACCOUNT_TYPES,
}


def account_types_for_market(market: str) -> List[str]:
    """Suggested account_type options for a market (empty list if none defined)."""
    return list(_ACCOUNT_TYPES_BY_MARKET.get((market or "").strip().lower(), []))


def is_known_account_type(value: str) -> bool:
    """True if value is a recognized account type for any market (advisory only)."""
    v = (value or "").strip().lower()
    return any(v in types for types in _ACCOUNT_TYPES_BY_MARKET.values())
```

(Create `src/portfolio/__init__.py` empty if the package does not exist.)

- [ ] **Step 4: Run to verify it passes** → PASS.
- [ ] **Step 5: Commit** (if authorized): `git add src/portfolio tests/test_account_types.py && git commit -m "feat(account-type): add account_types module with Canadian option set"`

---

### Task 2: DB column + idempotent migration

**Files:**
- Modify: `src/storage.py` — `PortfolioAccount` model (~line 498, after `base_currency`); add `_ensure_portfolio_account_type_column` mirroring `_ensure_llm_usage_telemetry_columns`; call it in the init sequence (next to `self._ensure_llm_usage_telemetry_columns()`).
- Test: `tests/test_account_types.py`

**Interfaces:**
- Produces: `PortfolioAccount.account_type` column; existing DBs gain the column on init.

- [ ] **Step 1: Write the failing test** (append):

```python
def test_portfolio_account_has_account_type_column():
    from src.storage import PortfolioAccount
    assert "account_type" in PortfolioAccount.__table__.columns


def test_account_type_column_backfilled_on_existing_db(tmp_path):
    """Idempotent ALTER TABLE adds account_type to a pre-existing DB without the column."""
    import sqlite3
    db_path = tmp_path / "legacy.db"
    # Simulate an old DB: portfolio_accounts without account_type.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE portfolio_accounts ("
        "id INTEGER PRIMARY KEY, owner_id TEXT, name TEXT NOT NULL, broker TEXT, "
        "market TEXT NOT NULL DEFAULT 'cn', base_currency TEXT NOT NULL DEFAULT 'CNY', "
        "is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)"
    )
    conn.commit(); conn.close()

    from src.storage import Database
    Database(f"sqlite:///{db_path}")  # init runs the column backfill

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(portfolio_accounts)")}
    conn.close()
    assert "account_type" in cols
```

(If `Database` constructor signature differs, use the project's actual init entry — check `src/storage.py` `class Database`.)

- [ ] **Step 2: Run to verify it fails** → FAIL (column missing).

- [ ] **Step 3: Implement** — in `src/storage.py`:

Add the column to `PortfolioAccount` after `base_currency`:

```python
    account_type = Column(String(32), nullable=True)  # advisory label, e.g. ca: rrsp/tfsa/fhsa
```

Add a module-level SQL map near `_LLM_USAGE_TELEMETRY_COLUMN_SQL`:

```python
_PORTFOLIO_ACCOUNT_COLUMN_SQL = {"account_type": "VARCHAR(32)"}
```

Add the migration method (mirror `_ensure_llm_usage_telemetry_columns` exactly, swapping the table/dict):

```python
    def _ensure_portfolio_account_type_column(self) -> None:
        """Add the nullable account_type column to existing SQLite portfolio_accounts."""
        if not self._is_sqlite_engine:
            return
        try:
            existing = {
                column["name"]
                for column in inspect(self._engine).get_columns(PortfolioAccount.__tablename__)
            }
        except Exception as exc:
            logger.warning(
                "[portfolio] failed to inspect account columns; skipping account_type backfill: %s",
                exc,
            )
            return
        max_retries = self._sqlite_write_retry_max
        for column, column_type in _PORTFOLIO_ACCOUNT_COLUMN_SQL.items():
            if column in existing:
                continue
            for attempt in range(max_retries + 1):
                try:
                    with self._engine.begin() as connection:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {PortfolioAccount.__tablename__} "
                            f"ADD COLUMN {column} {column_type}"
                        )
                    existing.add(column)
                    break
                except OperationalError as exc:
                    if self._is_sqlite_duplicate_column_error(exc, column):
                        existing.add(column)
                        break
                    if self._is_sqlite_locked_error(exc) and attempt < max_retries:
                        delay = self._sqlite_write_retry_base_delay * (2 ** attempt)
                        if delay > 0:
                            time.sleep(delay)
                        continue
                    raise
```

Call it in the init sequence (next to the other `_ensure_*` calls, e.g. right after `self._ensure_llm_usage_telemetry_columns()`):

```python
            self._ensure_portfolio_account_type_column()
```

(Match the exact retry/error helpers used by `_ensure_llm_usage_telemetry_columns` — copy its body verbatim, only changing table + column map. If it imports `time`/`inspect`/`OperationalError`, those are already imported in `storage.py`.)

- [ ] **Step 4: Run to verify it passes** → PASS.
- [ ] **Step 5: Commit** (if authorized): `git add src/storage.py tests/test_account_types.py && git commit -m "feat(account-type): add nullable account_type column + idempotent migration"`

---

### Task 3: Repo + service create/update passthrough + Item mapping

**Files:**
- Modify: `src/repositories/portfolio_repo.py` — `create_account` (add `account_type` param); confirm `update_account(account_id, fields)` already merges arbitrary fields (it does — generic dict).
- Modify: `src/services/portfolio_service.py` — `create_account` (~line 92) and `update_account` (~line 119) pass `account_type` through; wherever `PortfolioAccount` → response/item dict is built, include `account_type`.
- Test: `tests/test_account_types.py`

**Interfaces:**
- Consumes: model column (Task 2). Produces: `service.create_account(..., account_type=...)` persists and round-trips.

- [ ] **Step 1: Write the failing test** (append) — use the project's service construction (mirror an existing portfolio service test, e.g. `tests/test_portfolio_*`):

```python
def test_create_account_persists_account_type(tmp_path):
    from src.storage import Database
    from src.repositories.portfolio_repo import PortfolioRepository
    db = Database(f"sqlite:///{tmp_path / 'p.db'}")
    repo = PortfolioRepository(db)
    acc = repo.create_account(name="RRSP", broker="WS", market="ca",
                              base_currency="CAD", account_type="rrsp")
    assert acc.account_type == "rrsp"
    fetched = repo.get_account(acc.id)
    assert fetched.account_type == "rrsp"
```

(Adjust `PortfolioRepository`/`Database` construction to the project's actual constructors — check an existing `tests/test_portfolio_*.py` for the exact wiring.)

- [ ] **Step 2: Run to verify it fails** → FAIL (`create_account() got an unexpected keyword argument`).

- [ ] **Step 3: Implement**

`portfolio_repo.create_account`: add the param + set it on the row:

```python
    def create_account(
        self,
        *,
        name: str,
        broker: Optional[str],
        market: str,
        base_currency: str,
        owner_id: Optional[str] = None,
        account_type: Optional[str] = None,
    ) -> PortfolioAccount:
        with self.db.get_session() as session:
            row = PortfolioAccount(
                owner_id=owner_id,
                name=name,
                broker=broker,
                market=market,
                base_currency=base_currency,
                account_type=account_type,
                is_active=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row
```

`portfolio_service.create_account` (~line 92): add `account_type: Optional[str] = None` param and forward it to `repo.create_account(...)`. `update_account` (~line 119): include `account_type` in the updatable fields it forwards (it builds a `fields` dict — add `account_type` when provided). Wherever the service serializes an account to a dict/Item, add `"account_type": row.account_type`.

- [ ] **Step 4: Run to verify it passes** → PASS.
- [ ] **Step 5: Commit** (if authorized): `git add src/repositories/portfolio_repo.py src/services/portfolio_service.py tests/test_account_types.py && git commit -m "feat(account-type): thread account_type through repo + service"`

---

### Task 4: API schema + endpoint

**Files:**
- Modify: `api/v1/schemas/portfolio.py` — `PortfolioAccountCreateRequest` (~line 8), `PortfolioAccountUpdateRequest` (~line 16), `PortfolioAccountItem` (~line 25): add `account_type: Optional[str] = None` (free string, **not** a `Literal`).
- Modify: `api/v1/endpoints/portfolio.py` — `create_account` (~line 82) forwards `request.account_type` to `service.create_account(...)`; update endpoint forwards it too.
- Optional: add `GET` helper exposing `account_types_for_market` (only if a UI needs server-driven options; otherwise the web hardcodes the list — see Task 5). **YAGNI: skip unless Task 5 needs it.**
- Test: `tests/test_account_types.py`

**Interfaces:**
- Produces: API accepts/returns `account_type`.

- [ ] **Step 1: Write the failing test** (append):

```python
def test_account_type_in_portfolio_api_schema():
    from api.v1.schemas.portfolio import PortfolioAccountCreateRequest, PortfolioAccountItem
    req = PortfolioAccountCreateRequest(name="TFSA", market="ca",
                                        base_currency="CAD", account_type="tfsa")
    assert req.account_type == "tfsa"
    # Free string (advisory): a custom value is accepted, not rejected.
    req2 = PortfolioAccountCreateRequest(name="X", market="ca",
                                         base_currency="CAD", account_type="custom_thing")
    assert req2.account_type == "custom_thing"
    # Item carries it back.
    assert "account_type" in PortfolioAccountItem.model_fields
```

- [ ] **Step 2: Run to verify it fails** → FAIL (`account_type` not a field).

- [ ] **Step 3: Implement** — add `account_type: Optional[str] = Field(default=None, max_length=32)` to the three models; forward it in the create/update endpoints (`service.create_account(..., account_type=request.account_type)`).

- [ ] **Step 4: Run to verify it passes** → PASS.
- [ ] **Step 5: Run the backend gate** — `./scripts/ci_gate.sh` (or, in `dsa-test`: flake8 critical + `pytest -m "not network"`). Expected: PASS; on failure record the cause.
- [ ] **Step 6: Commit** (if authorized): `git add api/v1 tests/test_account_types.py && git commit -m "feat(account-type): accept/return account_type in portfolio API"`

---

### Task 5: Web — account-type select + display

**Files:**
- Modify: `apps/dsa-web/src/types/portfolio.ts` — add `accountType?: string` to the account item + create/update payload types.
- Modify: `apps/dsa-web/src/api/portfolio.ts` — map `account_type` ↔ `accountType` in `createAccount`/`updateAccount` payloads and the item parser (lines ~112-117, 171, 207).
- Create: `apps/dsa-web/src/utils/accountTypes.ts` — mirror `src/portfolio/account_types.py`: `CA_ACCOUNT_TYPES` + `accountTypesForMarket(market)` + a zh/en label map (or i18n keys).
- Modify: `apps/dsa-web/src/pages/PortfolioPage.tsx` — `accountForm` state (~line 180) gains `accountType`; the create form (~line 1088, near the market `<select>`) renders an account-type `<select>` **only when `accountForm.market === 'ca'`**, options from `accountTypesForMarket('ca')`; include `account_type` in the `createAccount` payload (~line 789) and update; display the account type on the account card.
- Test: `apps/dsa-web/src/utils/__tests__/accountTypes.test.ts` (new)

**Interfaces:**
- Consumes: Task 4 API. Build proves type completeness; the test proves the visible option list.

- [ ] **Step 1: Write the failing test** — `apps/dsa-web/src/utils/__tests__/accountTypes.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { CA_ACCOUNT_TYPES, accountTypesForMarket } from '../accountTypes';

describe('accountTypes', () => {
  it('returns the Canadian set for ca and nothing for others', () => {
    expect(accountTypesForMarket('ca')).toEqual(CA_ACCOUNT_TYPES);
    expect(accountTypesForMarket('us')).toEqual([]);
    expect(CA_ACCOUNT_TYPES).toContain('rrsp');
    expect(CA_ACCOUNT_TYPES).toContain('non_registered_margin');
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `cd apps/dsa-web && npx vitest run src/utils/__tests__/accountTypes.test.ts` → FAIL (module missing).

- [ ] **Step 3: Implement** — create `accountTypes.ts`:

```ts
export const CA_ACCOUNT_TYPES = [
  'rrsp', 'tfsa', 'fhsa', 'rrif', 'resp', 'lira', 'rdsp',
  'non_registered_cash', 'non_registered_margin',
] as const;

const BY_MARKET: Record<string, readonly string[]> = { ca: CA_ACCOUNT_TYPES };

export function accountTypesForMarket(market: string): string[] {
  return [...(BY_MARKET[(market || '').toLowerCase()] ?? [])];
}

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  rrsp: 'RRSP', tfsa: 'TFSA', fhsa: 'FHSA', rrif: 'RRIF', resp: 'RESP',
  lira: 'LIRA', rdsp: 'RDSP',
  non_registered_cash: '非注册现金 (Cash)',
  non_registered_margin: '非注册保证金 (Margin)',
};
```

Then wire `types/portfolio.ts`, `api/portfolio.ts` (account_type ↔ accountType), and `PortfolioPage.tsx` (state + conditional `<select>` shown when `market==='ca'` + payload + card display).

- [ ] **Step 4: Run to verify it passes** — vitest → PASS.
- [ ] **Step 5: Lint + build + test** — `cd apps/dsa-web && npm run lint && npm run build && npm test`. Expected: PASS (TS exhaustiveness catches any missed payload mapping).
- [ ] **Step 6: Capture a screenshot** of the account form showing the Canadian account-type dropdown for the PR (saved outside the repo, not committed).
- [ ] **Step 7: Commit** (if authorized): `git add apps/dsa-web/src && git commit -m "feat(account-type): account-type select + display in web UI"`

---

### Task 6: Docs

**Files:** Modify `docs/CHANGELOG.md` (`[Unreleased]`, flat `- [新功能] …`); add an "账户类型" note to `docs/market-support.md` Canada section (the deferred item is now done).

- [ ] **Step 1** — CHANGELOG line: `- [新功能] Portfolio 账户新增通用 account_type 标签字段（nullable，幂等迁移），market=ca 时提供加拿大账户类型选项（RRSP/TFSA/FHSA/RRIF/RESP/LIRA/RDSP/非注册现金/非注册保证金），纯标签不含税务逻辑；API（Create/Update/Item）与 Web 录入下拉同步。`
- [ ] **Step 2** — in `docs/market-support.md`, move "账户类型" out of the Canada "不承诺项"/后续 PR list into supported.
- [ ] **Step 3: Commit** (if authorized): `git add docs && git commit -m "docs(account-type): document account_type support"`

---

## Self-Review

**Spec coverage (§ Tier 1 account type):** generic nullable field ✓ (T2); Canadian options when ca ✓ (T1/T5); label/grouping only, no tax ✓ (out of scope by design); advisory free-string ✓ (T1/T4); migration via existing repair pattern ✓ (T2); API + web ✓ (T4/T5). The portfolio CAD/USD valuation口径 + missing-FX contract are a **separate** Tier-1b plan/branch (`feature/portfolio-cad-fx`) — not in this plan.

**Placeholder scan:** code shown for each step. The "adjust to actual constructor" notes (Database/PortfolioRepository wiring in T2/T3) are confirm-against-an-existing-test instructions, tied to a runnable test, not deferred design — confirm the wiring from any existing `tests/test_portfolio_*.py`.

**Type consistency:** `account_type` (snake) ↔ `accountType` (web camel); column `VARCHAR(32)` ⇄ Pydantic `max_length=32` ⇄ TS `string`; CA option keys identical in `account_types.py` and `accountTypes.ts` (`rrsp…non_registered_margin`).
