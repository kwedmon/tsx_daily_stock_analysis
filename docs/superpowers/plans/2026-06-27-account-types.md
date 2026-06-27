# Stream F · Tier 1a — Account Types (label-only) — Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 (post-review):** fixed test wiring (`DatabaseManager` singleton + `reset_instance()` + `DATABASE_PATH` env, not a non-existent `Database` class); made the update contract clear-capable via `model_fields_set` (explicit `null` clears, omitted preserves); column backfill follows the `_ensure_llm_usage_telemetry_columns` precedent and does **not** bump `schema_migrations` (spec corrected); web **edit** is explicitly **out of scope** (no account-edit flow exists today) — this plan does create + grouping + display; added service/API tests, `strip()`/empty→None normalization, and a grouping-helper test.

**Goal:** Add a generic, nullable `account_type` label to portfolio accounts, surfacing Canadian options (RRSP/TFSA/FHSA/…) when `market = ca`. Create + display + group accounts by type, fully functional through model/repo/service/API; the web offers a create-time picker and grouped display. **No tax logic.**

**Architecture:** Thin, additive change down the account chain: `account_types` module → nullable DB column (idempotent SQLite `ALTER TABLE`, mirroring `_ensure_llm_usage_telemetry_columns`, no version bump) → repo/service create+update (clear-capable) → API schema (advisory free-string, not a `Literal`) → web create picker + grouped selector. Fork-only (Stream F) on top of merged Tier 0 `ca`.

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, pytest; React/TS (`apps/dsa-web`, vitest).

## Global Constraints

- Branch `feature/account-types` (off `feature/ca-market`; has Tier 0 code + spec). Commits English, no `Co-Authored-By`, **only with explicit user authorization** (else stop at "tests pass").
- `account_type`: nullable, **advisory free-string** (no `Literal`), `VARCHAR(32)`; normalized `strip().lower()`, empty → `None`. CA known set: `rrsp, tfsa, fhsa, rrif, resp, lira, rdsp, non_registered_cash, non_registered_margin`.
- **Deferred (user-confirmed 2026-06-27):** web **account-edit UI** + web **custom-value input** are a follow-up work item (recorded in spec + CHANGELOG). The web has no account-edit flow today; `account_type` is fully editable via the API meanwhile. This plan does web **create + grouped display only**.
- **Test DB pattern (canonical, mirror `tests/test_portfolio_service.py`):** set `os.environ["DATABASE_PATH"]` to a temp file, `Config.reset_instance()`, `DatabaseManager.reset_instance()`, `DatabaseManager.get_instance()`, `PortfolioService()`; teardown resets both singletons and pops env. Run in `dsa-test` image: `docker run --rm -v $PWD:/app -w /app --entrypoint python dsa-test -m pytest <path> -v`.
- Reference: `docs/superpowers/specs/2026-06-26-canada-cdr-support-design.md` (§ Tier 1 account type).

---

### Task 1: `account_types` module (options + normalization)

**Files:** Create `src/portfolio/__init__.py` (if missing), `src/portfolio/account_types.py`; Test `tests/test_account_types.py`.

**Interfaces:** `CA_ACCOUNT_TYPES: list[str]`; `account_types_for_market(market) -> list[str]`; `is_known_account_type(value) -> bool`; `normalize_account_type(value: str | None) -> str | None`.

- [ ] **Step 1: Write the failing test** — `tests/test_account_types.py`:

```python
# -*- coding: utf-8 -*-
from src.portfolio.account_types import (
    CA_ACCOUNT_TYPES, account_types_for_market, is_known_account_type, normalize_account_type,
)


def test_canadian_account_types_listed_for_ca():
    opts = account_types_for_market("ca")
    assert opts == CA_ACCOUNT_TYPES
    for x in ("rrsp", "tfsa", "fhsa", "non_registered_margin"):
        assert x in opts


def test_non_ca_markets_have_no_predefined_types():
    assert account_types_for_market("us") == []
    assert account_types_for_market("") == []


def test_is_known_is_case_insensitive_and_advisory():
    assert is_known_account_type("RRSP") is True
    assert is_known_account_type("totally_custom") is False


def test_normalize_account_type_strips_lowercases_and_empties_to_none():
    assert normalize_account_type("  RRSP ") == "rrsp"
    assert normalize_account_type("") is None
    assert normalize_account_type("   ") is None
    assert normalize_account_type(None) is None
    assert normalize_account_type("Custom_Thing") == "custom_thing"
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `src/portfolio/account_types.py`:

```python
# -*- coding: utf-8 -*-
"""Account-type option sets + normalization (label-only; no tax logic)."""
from typing import Dict, List, Optional

CA_ACCOUNT_TYPES: List[str] = [
    "rrsp", "tfsa", "fhsa", "rrif", "resp", "lira", "rdsp",
    "non_registered_cash", "non_registered_margin",
]

_ACCOUNT_TYPES_BY_MARKET: Dict[str, List[str]] = {"ca": CA_ACCOUNT_TYPES}


def account_types_for_market(market: str) -> List[str]:
    return list(_ACCOUNT_TYPES_BY_MARKET.get((market or "").strip().lower(), []))


def is_known_account_type(value: str) -> bool:
    v = (value or "").strip().lower()
    return any(v in types for types in _ACCOUNT_TYPES_BY_MARKET.values())


def normalize_account_type(value: Optional[str]) -> Optional[str]:
    """Strip + lowercase; empty/whitespace -> None. Advisory: any non-empty value kept."""
    if value is None:
        return None
    v = value.strip().lower()
    return v or None
```

(Create empty `src/portfolio/__init__.py` if the package is new.)

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** (if authorized): `git add src/portfolio tests/test_account_types.py && git commit -m "feat(account-type): account_types module (options + normalization)"`

---

### Task 2: DB column + idempotent migration (no version bump)

**Files:** Modify `src/storage.py` (`PortfolioAccount` model after `base_currency`; `_PORTFOLIO_ACCOUNT_COLUMN_SQL` map; `_ensure_portfolio_account_type_column` mirroring `_ensure_llm_usage_telemetry_columns`; call it in the init sequence next to that method). Test `tests/test_account_types.py`.

**Migration note (#4):** column backfills in this codebase do **not** write `schema_migrations` — `_ensure_schema_migration_record` only records the single `CURRENT_SCHEMA_VERSION` create-all baseline, and `_ensure_llm_usage_telemetry_columns` adds columns without bumping it. `account_type` follows that precedent: idempotent (skipped when the column exists), no version bump. Do not invent a new version record.

- [ ] **Step 1: Write the failing test** (append):

```python
import os, sqlite3, tempfile


def test_portfolio_account_has_account_type_column():
    from src.storage import PortfolioAccount
    assert "account_type" in PortfolioAccount.__table__.columns


def test_account_type_backfilled_on_legacy_db():
    """Idempotent ALTER TABLE adds account_type to a pre-existing DB lacking it."""
    from src.config import Config
    from src.storage import DatabaseManager
    tmp = tempfile.TemporaryDirectory()
    try:
        db_path = os.path.join(tmp.name, "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE portfolio_accounts ("
            "id INTEGER PRIMARY KEY, owner_id TEXT, name TEXT NOT NULL, broker TEXT, "
            "market TEXT NOT NULL DEFAULT 'cn', base_currency TEXT NOT NULL DEFAULT 'CNY', "
            "is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)"
        )
        conn.commit(); conn.close()

        os.environ["DATABASE_PATH"] = db_path
        Config.reset_instance(); DatabaseManager.reset_instance()
        DatabaseManager.get_instance()  # init runs the column backfill

        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(portfolio_accounts)")}
        conn.close()
        assert "account_type" in cols

        # Idempotency: re-initialize the SAME db; the backfill must skip (no duplicate ALTER).
        DatabaseManager.reset_instance()
        DatabaseManager.get_instance()  # must not raise "duplicate column name"
        conn = sqlite3.connect(db_path)
        n = sum(1 for r in conn.execute("PRAGMA table_info(portfolio_accounts)") if r[1] == "account_type")
        conn.close()
        assert n == 1
    finally:
        DatabaseManager.reset_instance(); Config.reset_instance()
        os.environ.pop("DATABASE_PATH", None); tmp.cleanup()
```

- [ ] **Step 2: Run → FAIL** (column missing).
- [ ] **Step 3: Implement** — model column after `base_currency`:

```python
    account_type = Column(String(32), nullable=True)  # advisory label, e.g. ca: rrsp/tfsa
```

Module-level near `_LLM_USAGE_TELEMETRY_COLUMN_SQL`:

```python
_PORTFOLIO_ACCOUNT_COLUMN_SQL = {"account_type": "VARCHAR(32)"}
```

Add `_ensure_portfolio_account_type_column` — copy the body of `_ensure_llm_usage_telemetry_columns` **verbatim**, changing only the table to `PortfolioAccount.__tablename__`, the column map to `_PORTFOLIO_ACCOUNT_COLUMN_SQL`, and the log prefix to `[portfolio]`. Call it in the init sequence right after `self._ensure_llm_usage_telemetry_columns()`:

```python
            self._ensure_portfolio_account_type_column()
```

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** (if authorized): `git add src/storage.py tests/test_account_types.py && git commit -m "feat(account-type): nullable account_type column + idempotent backfill"`

---

### Task 3: Repo + service create/update (clear-capable) + serialization

**Files:** Modify `src/repositories/portfolio_repo.py` (`create_account` add `account_type` param; `update_account(account_id, fields)` is already a generic dict merge — verify it sets `account_type` incl. `None`). Modify `src/services/portfolio_service.py` (`create_account` ~line 92 add+normalize `account_type`; `update_account` ~line 119 accept a clear-capable `account_type`; include `account_type` wherever an account is serialized to a dict/Item). Test `tests/test_account_types.py`.

**Clear-capable update:** the service `update_account` must distinguish "set to a value", "clear to None", and "leave unchanged". Use a sentinel so `None` means *clear*:

```python
_UNSET = object()
def update_account(self, account_id, *, ..., account_type=_UNSET):
    fields = {}
    ...
    if account_type is not _UNSET:
        fields["account_type"] = normalize_account_type(account_type)  # None clears
    return self.repo.update_account(account_id, fields)
```

- [ ] **Step 1: Write the failing test** (append) — mirror `tests/test_portfolio_service.py` setUp (env `DATABASE_PATH` + reset_instance + `PortfolioService()`):

```python
import unittest


class AccountTypeServiceTests(unittest.TestCase):
    def setUp(self):
        from src.config import Config
        from src.storage import DatabaseManager
        from src.services.portfolio_service import PortfolioService
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "p.db")
        Config.reset_instance(); DatabaseManager.reset_instance()
        DatabaseManager.get_instance()
        self.service = PortfolioService()

    def tearDown(self):
        from src.config import Config
        from src.storage import DatabaseManager
        DatabaseManager.reset_instance(); Config.reset_instance()
        os.environ.pop("DATABASE_PATH", None); self._tmp.cleanup()

    def _acct(self, aid):
        # PortfolioService returns dicts via _account_to_dict; there is no get_account().
        return next(a for a in self.service.list_accounts(include_inactive=True) if a["id"] == aid)

    def test_create_update_clear_and_preserve_account_type(self):
        acc = self.service.create_account(name="RRSP", broker="WS", market="ca",
                                          base_currency="CAD", account_type="  RRSP ")
        aid = acc["id"]                                   # create_account returns a dict
        assert self._acct(aid)["account_type"] == "rrsp"  # created + normalized
        self.service.update_account(aid, account_type="tfsa")          # update to another type
        assert self._acct(aid)["account_type"] == "tfsa"
        self.service.update_account(aid, account_type=None)            # explicit clear
        assert self._acct(aid)["account_type"] is None
        self.service.update_account(aid, account_type="fhsa")
        self.service.update_account(aid, name="renamed")              # omitted -> preserved
        assert self._acct(aid)["account_type"] == "fhsa"
```

(`PortfolioService.create_account`/`list_accounts`/`update_account` return/accept dicts — confirm exact kwarg names against `tests/test_portfolio_service.py`. The serialization point to extend is `PortfolioService._account_to_dict` — add `"account_type": row.account_type` there in Step 3.)

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the repo param, the service create normalization, the sentinel-based clear-capable `update_account`, and `account_type` in the account serialization (the dict/Item the service returns). Use `normalize_account_type` from Task 1.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** (if authorized): `git add src/repositories/portfolio_repo.py src/services/portfolio_service.py tests/test_account_types.py && git commit -m "feat(account-type): clear-capable account_type through repo + service"`

---

### Task 4: API schema + endpoints (presence-aware update)

**Files:** Modify `api/v1/schemas/portfolio.py` (`PortfolioAccountCreateRequest`, `PortfolioAccountUpdateRequest`, `PortfolioAccountItem`: add `account_type: Optional[str] = Field(default=None, max_length=32)`). Modify `api/v1/endpoints/portfolio.py` (`create_account` forwards normalized `account_type`; the **update** endpoint forwards it **only when present** via `model_fields_set`, allowing an explicit `None` to clear). Test `tests/test_account_types.py`.

**Presence-aware update (#2):**
```python
# in the update endpoint:
kwargs = {}
if "account_type" in request.model_fields_set:
    kwargs["account_type"] = request.account_type   # may be None -> clears
service.update_account(account_id, ..., **kwargs)
```

- [ ] **Step 1: Write the failing test** (append):

```python
def test_account_type_in_portfolio_api_schema():
    from api.v1.schemas.portfolio import PortfolioAccountCreateRequest, PortfolioAccountUpdateRequest, PortfolioAccountItem
    r = PortfolioAccountCreateRequest(name="TFSA", market="ca", base_currency="CAD", account_type="tfsa")
    assert r.account_type == "tfsa"
    # advisory free string accepted
    assert PortfolioAccountCreateRequest(name="X", market="ca", base_currency="CAD",
                                         account_type="custom").account_type == "custom"
    assert "account_type" in PortfolioAccountItem.model_fields
    # presence: omitting account_type is distinguishable from sending null
    assert "account_type" not in PortfolioAccountUpdateRequest(name="x").model_fields_set
    assert "account_type" in PortfolioAccountUpdateRequest(account_type=None).model_fields_set


class AccountTypeEndpointTests(unittest.TestCase):
    """End-to-end presence-aware update via PUT /accounts/{id} (mirror tests/test_portfolio_api.py)."""

    def setUp(self):
        from src.config import Config
        from src.storage import DatabaseManager
        from fastapi.testclient import TestClient
        from api.app import create_app
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "api.db")
        Config.reset_instance(); DatabaseManager.reset_instance()
        # static_dir: mirror tests/test_portfolio_api.py (it passes an empty-static dir).
        self.client = TestClient(create_app(static_dir=self._tmp.name))

    def tearDown(self):
        from src.config import Config
        from src.storage import DatabaseManager
        DatabaseManager.reset_instance(); Config.reset_instance()
        os.environ.pop("DATABASE_PATH", None); self._tmp.cleanup()

    def test_put_account_type_presence_aware(self):
        base = "/api/v1/portfolio/accounts"
        created = self.client.post(base, json={"name": "TFSA", "market": "ca",
                                               "base_currency": "CAD", "account_type": "tfsa"})
        assert created.status_code == 200, created.text
        aid = created.json()["id"]
        assert created.json()["account_type"] == "tfsa"
        assert self.client.put(f"{base}/{aid}", json={"account_type": "rrsp"}).json()["account_type"] == "rrsp"
        assert self.client.put(f"{base}/{aid}", json={"account_type": None}).json()["account_type"] is None
        self.client.put(f"{base}/{aid}", json={"account_type": "fhsa"})  # set, then change another field
        assert self.client.put(f"{base}/{aid}", json={"name": "renamed"}).json()["account_type"] == "fhsa"
```

(Confirm the create/update response includes `account_type` — it does once `PortfolioAccountItem` carries it and `_account_to_dict` populates it. If `create_app` needs a different `static_dir`, mirror `tests/test_portfolio_api.py` exactly.)

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the three schema fields + both endpoints (create forwards normalized value; the `PUT` update is presence-aware: forward `account_type` to the service **only when** `"account_type" in request.model_fields_set`, value may be `None` to clear).
- [ ] **Step 4: Run → PASS** (both the schema test and the endpoint test).
- [ ] **Step 5: Backend gate** — `./scripts/ci_gate.sh` (or in `dsa-test`: flake8 critical + `pytest -m "not network"`). PASS; on failure record the cause.
- [ ] **Step 6: Commit** (if authorized): `git add api/v1 tests/test_account_types.py && git commit -m "feat(account-type): account_type in portfolio API (presence-aware update)"`

---

### Task 5: Web — create picker + grouped selector + display (no edit)

**Files:**
- Modify `apps/dsa-web/src/types/portfolio.ts` (add `accountType?: string` to item + create payload types).
- Modify `apps/dsa-web/src/api/portfolio.ts` (`createAccount`: map `accountType` → `account_type`; item parser: `account_type` → `accountType`). **No `updateAccount` added — edit is deferred.**
- Create `apps/dsa-web/src/utils/accountTypes.ts` (`CA_ACCOUNT_TYPES`, `accountTypesForMarket`, `ACCOUNT_TYPE_LABELS`, `groupAccountsByType(accounts)`).
- Create `apps/dsa-web/src/components/AccountTypeSelect.tsx` — a small presentational component `({ market, value, onChange })` that renders the labelled `<select>` (CA options + a blank "未指定") **only when `market === 'ca'`**, else `null`. (Extracted so it is unit-testable without rendering the whole `PortfolioPage`.)
- Modify `apps/dsa-web/src/pages/PortfolioPage.tsx`: `accountForm` state (~line 180) gains `accountType: ''`; the create form (~line 1088, after the market `<select>`) renders `<AccountTypeSelect market={accountForm.market} value={accountForm.accountType} onChange={(v) => setAccountForm((p) => ({ ...p, accountType: v }))} />`; include `accountType` in the `createAccount` payload (~line 789). **Display:** the account selector (~line 949) groups accounts via `<optgroup>` (label = `ACCOUNT_TYPE_LABELS[type]`, untyped under "未分类" last) using `groupAccountsByType` — this grouped selector IS the type display (no separate "card"; if an account card view is later added, reuse `ACCOUNT_TYPE_LABELS`).
- Tests: `apps/dsa-web/src/utils/__tests__/accountTypes.test.ts` and `apps/dsa-web/src/components/__tests__/AccountTypeSelect.test.tsx` (new).

- [ ] **Step 1: Write the failing test**:

```ts
import { describe, expect, it } from 'vitest';
import { CA_ACCOUNT_TYPES, accountTypesForMarket, groupAccountsByType } from '../accountTypes';

describe('accountTypes', () => {
  it('returns the Canadian set for ca and nothing for others', () => {
    expect(accountTypesForMarket('ca')).toEqual([...CA_ACCOUNT_TYPES]);
    expect(accountTypesForMarket('us')).toEqual([]);
    expect(CA_ACCOUNT_TYPES).toContain('non_registered_margin');
  });
  it('groups accounts by type, untyped last', () => {
    const groups = groupAccountsByType([
      { id: 1, name: 'A', accountType: 'rrsp' },
      { id: 2, name: 'B' },
      { id: 3, name: 'C', accountType: 'rrsp' },
    ] as any);
    expect(groups.find(g => g.key === 'rrsp')?.accounts.map(a => a.id)).toEqual([1, 3]);
    expect(groups[groups.length - 1].key).toBe('');           // untyped group last
    expect(groups[groups.length - 1].accounts.map(a => a.id)).toEqual([2]);
  });
});
```

- [ ] **Step 2: Run → FAIL** — `cd apps/dsa-web && npx vitest run src/utils/__tests__/accountTypes.test.ts`.
- [ ] **Step 3: Implement** `accountTypes.ts`:

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
  non_registered_cash: '非注册现金', non_registered_margin: '非注册保证金',
};

export interface AccountTypeGroup<T> { key: string; label: string; accounts: T[]; }
export function groupAccountsByType<T extends { accountType?: string }>(accounts: T[]): AccountTypeGroup<T>[] {
  const buckets = new Map<string, T[]>();
  for (const a of accounts) {
    const k = (a.accountType || '').toLowerCase();
    (buckets.get(k) ?? buckets.set(k, []).get(k)!).push(a);
  }
  // Order: known CA types first, then any custom/unknown types, then untyped ('') LAST.
  const known = (CA_ACCOUNT_TYPES as readonly string[]).filter(k => buckets.has(k));
  const custom = [...buckets.keys()].filter(k => k !== '' && !(CA_ACCOUNT_TYPES as readonly string[]).includes(k));
  const order = [...known, ...custom, ...(buckets.has('') ? [''] : [])];
  return order.map(k => ({ key: k, label: k ? (ACCOUNT_TYPE_LABELS[k] ?? k) : '未分类', accounts: buckets.get(k)! }));
}
```

Then wire `types/portfolio.ts`, `api/portfolio.ts`, and `PortfolioPage.tsx` (state + conditional `<select>` when `market==='ca'` + payload + `<optgroup>` selector + card display).

- [ ] **Step 4: Run → PASS** (vitest, helper).
- [ ] **Step 4b: Component test for `AccountTypeSelect`** — `apps/dsa-web/src/components/__tests__/AccountTypeSelect.test.tsx` (mirror the render setup of an existing component test, e.g. `src/components/report/__tests__/AnalysisContextSummary.test.tsx`):

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AccountTypeSelect from '../AccountTypeSelect';

describe('AccountTypeSelect', () => {
  it('renders the CA options only when market is ca', () => {
    const { container, rerender } = render(
      <AccountTypeSelect market="ca" value="" onChange={vi.fn()} />,
    );
    expect(screen.getByRole('combobox')).toBeTruthy();
    expect(screen.getByRole('option', { name: /RRSP/ })).toBeTruthy();
    rerender(<AccountTypeSelect market="us" value="" onChange={vi.fn()} />);
    expect(container.querySelector('select')).toBeNull();   // hidden for non-ca
  });
});
```

(If the repo's component tests don't use `@testing-library/react`, mirror whatever render util `AnalysisContextSummary.test.tsx` uses.)

- [ ] **Step 5: Lint + build + test** — `cd apps/dsa-web && npm run lint && npm run build && npm test`. PASS (TS exhaustiveness catches missed payload/type mappings; component test proves the conditional dropdown).
- [ ] **Step 6: Screenshot** the create form's CA account-type dropdown + the grouped selector for the PR (saved outside the repo, not committed).
- [ ] **Step 7: Commit** (if authorized): `git add apps/dsa-web/src && git commit -m "feat(account-type): create picker + grouped selector + display"`

---

### Task 6: Docs + spec scope correction

**Files:** `docs/CHANGELOG.md`, `docs/market-support.md`, and the spec.

- [ ] **Step 1** — CHANGELOG `[Unreleased]`, two flat lines:
  - `- [新功能] Portfolio 账户新增通用 account_type 标签字段（nullable，幂等列回填，不 bump schema_migrations），market=ca 时提供加拿大账户类型（RRSP/TFSA/FHSA/RRIF/RESP/LIRA/RDSP/非注册现金/非注册保证金）；API 创建/更新（presence-aware，可显式清空）与 Web 创建下拉 + 按类型分组展示同步；纯标签不含税务逻辑。`
  - `- [文档] Web 账户编辑 UI 与自定义 account_type 输入作为后续 work item（当前 Web 无账户编辑流程；account_type 可经 API 编辑）。`
- [ ] **Step 2** — `docs/market-support.md` Canada section: move "账户类型" out of 后续 PR into supported.
- [ ] **Step 3** — `docs/superpowers/specs/2026-06-26-canada-cdr-support-design.md` Tier 1 account-type note: correct to "idempotent column backfill, **no** schema_migrations bump"; mark **web edit UI** and **web custom-value input** as deferred (backend update is presence-aware/clear-capable via API).
- [ ] **Step 4: Commit** (if authorized): `git add docs && git commit -m "docs(account-type): document support; correct spec scope (no edit UI, no version bump)"`

---

## Self-Review

**Spec coverage:** generic nullable field ✓(T2); CA options when ca ✓(T1/T5); label/grouping ✓(T5 optgroup); advisory free-string + normalization ✓(T1/T4); create + clear-capable update through repo/service/API ✓(T3/T4). **Descoped & reconciled in spec** (T6): web edit UI, web custom-value input, schema_migrations bump. Portfolio CAD/USD口径 + missing-FX is a separate `feature/portfolio-cad-fx` plan.

**Placeholder scan:** test wiring uses the verified `DatabaseManager`/`DATABASE_PATH`/`reset_instance` pattern. "Adjust to actual service signature" notes (T3) are confirm-against-`tests/test_portfolio_service.py`, tied to runnable tests.

**Type consistency:** `account_type` (snake, py/db/api) ↔ `accountType` (web camel); `VARCHAR(32)` ⇄ `max_length=32` ⇄ TS `string`; CA keys identical in `account_types.py` and `accountTypes.ts`; sentinel `_UNSET` (service) vs `model_fields_set` (API) both express "field omitted vs explicit null".
