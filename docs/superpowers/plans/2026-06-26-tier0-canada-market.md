# Tier 0 — Canadian `.TO`/`.V` Market MVP — Implementation Plan (v3)

> **v3 (post review #2):** Fixed the daily-vs-realtime US-helper split (`is_us_stock_code` vs `_is_us_code`) + Canadian error label; unified Canada recognition to one base-validating regex across all entries (+ cross-entry consistency test); corrected the Pydantic class to `PortfolioAccountCreateRequest`; added a frontend visible-option test, PR-screenshot step (not committed), and stricter `ci_gate.sh` wording.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Canadian TSX (`.TO`) and TSX Venture (`.V`) common stocks as a first-class "suffix-only" market (`ca`) — detection, code-utils, Yahoo routing, offshore fundamentals, calendar, bilingual prompt, backend enums, **and web types/labels/filters** — mirroring the JP/KR (#1718) and TW (#1772) MVPs.

**Architecture:** Additive, thin-seam edits to the existing scattered market-detection/enum spots (no registry refactor). Canadian tickers are alphabetic, so every detector must place the `.TO`/`.V` check **before** the US branch: `detect_market`'s regex captures both suffixes, and `is_us_stock_code` captures `.V` (single-letter suffix) though not `.TO`. Stream U (upstream-bound); self-sufficient in the fork regardless of upstream acceptance.

**Tech Stack:** Python 3.11, SQLAlchemy, FastAPI, pytest; React/TypeScript (`apps/dsa-web`, Vite). Data via `YfinanceFetcher`. Calendar via `exchange-calendars` (`XTSE`).

## Global Constraints

- Follow `AGENTS.md`: minimal additive diff; commit messages in **English**, **no `Co-Authored-By` trailer**; update `docs/market-support.md` + `docs/CHANGELOG.md`.
- **Commits require explicit user authorization** (repo rule + harness). Before execution, obtain blanket authorization to commit each task on `feature/ca-market`; otherwise run each task through its "tests pass" step and **stop at the verified working tree**, leaving the commit to the user. The `Commit` steps below assume authorization was granted.
- `pytest -m "not network"` must pass (offline; mock fetchers). Web task additionally runs `npm run lint` + `npm run build`.
- New market key is exactly `"ca"`; exchange `"XTSE"`; timezone `"America/Toronto"`. Canada matcher regex: `^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$`.
- Do **not** add `ca` to the `{cn,hk,us}`-only feature gates (market-light, alerts, risk core-gate, agent market_tools, config_registry) — deferred to Tier 4, matching jp/kr/tw.
- Reference spec: `docs/superpowers/specs/2026-06-26-canada-cdr-support-design.md` (Tier 0). Branch `feature/ca-market` off `upstream/main`; exclude `docs/superpowers/**` from the upstream PR.

---

### Task 1: Detect `.TO`/`.V` as `ca` across all detection + code-utils entry points

**Files:**
- Modify: `src/market_context.py` (`detect_market`, before the US regex ~line 53)
- Modify: `src/core/trading_calendar.py` (`get_market_for_stock`, before `is_us_stock_code` ~line 122)
- Modify: `data_provider/base.py` (`normalize_stock_code` ~line 133)
- Modify: `src/services/stock_code_utils.py` (`is_code_like` ~line 101, `normalize_code` ~line 123)
- Test: `tests/test_ca_market_support.py` (new)

**Interfaces:**
- Produces: `detect_market(code) -> "ca"`, `get_market_for_stock(code) -> "ca"`, `normalize_stock_code` and `normalize_code` preserve `.TO`/`.V` uppercased, `is_code_like(".TO"/".V") -> True`. Later tasks rely on these.

- [ ] **Step 1: Write the failing test** — create `tests/test_ca_market_support.py`:

```python
# -*- coding: utf-8 -*-
"""Regression tests for Canada (TSX/TSX-V) suffix-only market support.

Mirrors tests/test_tw_market_support.py. Canadian common stocks use Yahoo Finance
suffix forms ``SYM.TO`` (TSX) and ``SYM.V`` (TSX Venture). The base is alphabetic
(optionally hyphenated, e.g. ``BAM-A.TO``); the ``.TO``/``.V`` check must precede
the US branch in every detector. Bare codes are unaffected.
"""

from unittest.mock import patch

import pandas as pd
from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager, normalize_stock_code
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE, get_market_for_stock
from src.market_context import detect_market, get_market_guidelines, get_market_role
from src.services.stock_code_utils import is_code_like, normalize_code


def test_normalize_and_detect_ca_suffix_codes() -> None:
    assert normalize_stock_code("td.to") == "TD.TO"
    assert normalize_stock_code("shop.to") == "SHOP.TO"
    assert normalize_stock_code("bam-a.to") == "BAM-A.TO"
    assert normalize_stock_code("abc.v") == "ABC.V"

    for code in ("TD.TO", "SHOP.TO", "ENB.TO", "BAM-A.TO", "ABC.V"):
        assert detect_market(code) == "ca", code
    assert detect_market("AAPL") == "us"
    assert detect_market("600519") == "cn"

    assert get_market_for_stock("TD.TO") == "ca"
    assert get_market_for_stock("ABC.V") == "ca"   # .V also collides with US single-letter suffix
    assert get_market_for_stock("AAPL") == "us"


def test_ca_code_utils_accept_and_preserve() -> None:
    assert is_code_like("TD.TO") is True
    assert is_code_like("BAM-A.TO") is True
    assert is_code_like("ABC.V") is True
    assert normalize_code("td.to") == "TD.TO"
    assert normalize_code("bam-a.to") == "BAM-A.TO"
    assert normalize_code("abc.v") == "ABC.V"
    # Invalid shapes are rejected.
    assert normalize_code("TD.TX") != "TD.TX"  # unknown suffix -> not preserved as ca
    assert is_code_like(".TO") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ca_market_support.py::test_normalize_and_detect_ca_suffix_codes tests/test_ca_market_support.py::test_ca_code_utils_accept_and_preserve -v`
Expected: FAIL (`detect_market("TD.TO")=="us"`; `is_code_like("TD.TO")` False; `normalize_code("td.to")` None).

- [ ] **Step 3: `src/market_context.py` — `detect_market`**

Immediately **before** the `# US stocks:` block, insert:

```python
    # Canada suffix-only Yahoo symbols (TSX `.TO`, TSX-V `.V`). Alphabetic base
    # (optionally hyphenated, e.g. BAM-A.TO); both suffixes are captured by the US
    # regex below, so this MUST precede it.
    if re.match(r'^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$', code):
        return "ca"
```

- [ ] **Step 4: `src/core/trading_calendar.py` — `get_market_for_stock`**

Immediately after `code = (code or "").strip().upper()` and **before** the `from data_provider import is_us_stock_code...` line, insert (ensure `import re` exists at the module top — add it if missing):

```python
    # Canada: TSX `.TO` / TSX-V `.V`. Use the SAME base-validating shape as
    # detect_market / _is_ca_market (not bare endswith), so all entries agree;
    # `.V` collides with the US single-letter-suffix check below, so this is first.
    if re.match(r'^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$', code):
        return "ca"
```

- [ ] **Step 5: `data_provider/base.py` — `normalize_stock_code`**

Inside `if '.' in code:`, after the `TW/TWO` branch and before the `HK` branch, insert (validate the base, not just the suffix — `re` is already imported in this module):

```python
        if suffix.upper() in ('TO', 'V') and re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,11}', base.upper()):
            return f"{base.upper()}.{suffix.upper()}"
```

- [ ] **Step 6: `src/services/stock_code_utils.py` — accept + preserve `.TO`/`.V`**

Add a module-level matcher near `_PRESERVE_SUFFIXES` (line ~39):

```python
import re  # if not already imported at module top
_CA_SUFFIX_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$')
```

In `is_code_like`, before the final `return False`, add:

```python
    if _CA_SUFFIX_PATTERN.match(text):
        return True
```

In `normalize_code`, before the final `return None`, add:

```python
    if _CA_SUFFIX_PATTERN.match(text):
        return text
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_ca_market_support.py::test_normalize_and_detect_ca_suffix_codes tests/test_ca_market_support.py::test_ca_code_utils_accept_and_preserve -v`
Expected: PASS

- [ ] **Step 8: Commit** (if authorized — see Global Constraints)

```bash
git add tests/test_ca_market_support.py src/market_context.py src/core/trading_calendar.py data_provider/base.py src/services/stock_code_utils.py
git commit -m "feat(ca): detect and normalize TSX .TO / TSX-V .V as ca market"
```

---

### Task 2: Register the Canadian trading calendar

**Files:** Modify `src/core/trading_calendar.py` (`MARKET_EXCHANGE` line 39, `MARKET_TIMEZONE` line 42). Test: `tests/test_ca_market_support.py`.

**Interfaces:** Produces `MARKET_EXCHANGE["ca"] == "XTSE"`, `MARKET_TIMEZONE["ca"] == "America/Toronto"`.

- [ ] **Step 1: Write the failing test** (append):

```python
def test_trading_calendar_registers_ca_exchange_and_timezone() -> None:
    assert MARKET_EXCHANGE["ca"] == "XTSE"
    assert MARKET_TIMEZONE["ca"] == "America/Toronto"
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_ca_market_support.py::test_trading_calendar_registers_ca_exchange_and_timezone -v` → FAIL (`KeyError: 'ca'`).
- [ ] **Step 3: Implement** — add `"ca": "XTSE"` to `MARKET_EXCHANGE` and `"ca": "America/Toronto"` to `MARKET_TIMEZONE`.
- [ ] **Step 4: Run to verify it passes** — same command → PASS.
- [ ] **Step 5: Commit** (if authorized):

```bash
git add src/core/trading_calendar.py tests/test_ca_market_support.py
git commit -m "feat(ca): register XTSE / America/Toronto trading calendar"
```

---

### Task 3: Canadian market role + guidelines (bilingual prompt)

**Files:** Modify `src/market_context.py` (`_MARKET_ROLES` line 64, `_MARKET_GUIDELINES` line 91). Test: `tests/test_ca_market_support.py`.

**Interfaces:** Consumes `detect_market -> "ca"`. Produces `get_market_role("TD.TO", "zh"/"en")` and `get_market_guidelines("TD.TO", "zh"/"en")`. **Both `zh` and `en` are required** — every other entry has both, and `get_market_guidelines(..., lang="en")` KeyErrors otherwise.

- [ ] **Step 1: Write the failing test** (append):

```python
def test_market_role_and_guidelines_for_ca_bilingual() -> None:
    assert get_market_role("TD.TO", "zh") == "加拿大股"
    assert get_market_role("TD.TO", "en") == "Canadian (TSX) stock"

    zh = get_market_guidelines("TD.TO", "zh")
    assert "加拿大" in zh and "加元" in zh
    assert "北向资金" in zh and "龙虎榜" in zh   # named in the A-share-exclusion clause

    en = get_market_guidelines("TD.TO", "en")
    assert "Canad" in en and ("CAD" in en or "Canadian dollar" in en)
```

(If `get_market_role`/`get_market_guidelines` take the language positionally or via `lang=`, match the existing signature used by the jp/kr/tw tests/callers.)

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_ca_market_support.py::test_market_role_and_guidelines_for_ca_bilingual -v` → FAIL (KeyError `'ca'`).

- [ ] **Step 3: Implement** — add to `_MARKET_ROLES`:

```python
    "ca": {
        "zh": "加拿大股",
        "en": "Canadian (TSX) stock",
    },
```

and to `_MARKET_GUIDELINES`:

```python
    "ca": {
        "zh": (
            "- 请按加拿大市场语境分析，关注加元（CAD）汇率、加拿大央行（BoC）政策、"
            "TSX/TSX-V 交易制度，以及资源、金融、科技板块结构；多伦多证券交易所无涨跌停"
            "限制、支持 T+0；不要套用 A 股涨跌停、北向资金、龙虎榜、融资融券等 A 股专属概念。"
        ),
        "en": (
            "- Analyze in the Canadian market context: watch the Canadian dollar (CAD), "
            "Bank of Canada (BoC) policy, TSX/TSX-V trading rules, and the resource / "
            "financial / technology sector mix. The TSX has no daily price limits and "
            "supports same-day trading; do NOT apply China A-share concepts (price-limit "
            "boards, northbound flows, dragon-tiger lists, margin financing)."
        ),
    },
```

- [ ] **Step 4: Run to verify it passes** — same command → PASS.
- [ ] **Step 5: Commit** (if authorized):

```bash
git add src/market_context.py tests/test_ca_market_support.py
git commit -m "feat(ca): add bilingual Canadian market role and guidelines"
```

---

### Task 4: Route Canadian symbols to Yahoo only; enable + prove offshore fundamentals

**Files:**
- Modify: `data_provider/base.py` — add `_is_ca_market` (next to `_is_tw_market` ~line 197); `_market_tag` (~line 250, ca **first**); offshore quote gates at ~line 1269-1270 and ~line 1700-1708; `YfinanceFetcher` capability (line 632); offshore fundamental gate (line 2971)
- Modify: `data_provider/yfinance_fetcher.py` — add `_is_ca_suffix_stock`; use in `_convert_stock_code` (~line 144) and the offshore-eligibility check (~line 798)
- Test: `tests/test_ca_market_support.py`

**Interfaces:**
- Consumes: detection (Task 1). Produces: `_market_tag("TD.TO") == "ca"`; `YfinanceFetcher._convert_stock_code("TD.TO") == "TD.TO"`; `DataFetcherManager.get_daily_data("TD.TO")` resolves only via `YfinanceFetcher`; `ca` fundamentals use `_build_offshore_fundamental_context`.

- [ ] **Step 1: Write the failing tests** (append):

```python
class _FakeFetcher(BaseFetcher):
    def __init__(self, name: str, should_fail: bool = False):
        self.name = name
        self.priority = 0 if name != "YfinanceFetcher" else 4
        self.calls = []
        self.should_fail = should_fail

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        if self.should_fail:
            raise DataFetchError(f"{self.name} should not be called for {stock_code}")
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-06-23")],
                "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                "volume": [100], "amount": [100.0], "pct_chg": [0.0],
            }
        )


def test_yfinance_keeps_ca_suffix_codes() -> None:
    fetcher = YfinanceFetcher()
    assert fetcher._convert_stock_code("TD.TO") == "TD.TO"
    assert fetcher._convert_stock_code("ABC.V") == "ABC.V"


def test_market_tag_classifies_ca() -> None:
    from data_provider.base import _market_tag
    assert _market_tag("TD.TO") == "ca"
    assert _market_tag("ABC.V") == "ca"
    assert _market_tag("AAPL") == "us"


import pytest


@pytest.mark.parametrize("code,is_ca", [
    ("TD.TO", True), ("BAM-A.TO", True), ("ABC.V", True), ("XIU.TO", True),
    (".TO", False), ("FOO..TO", False), ("TOOLONGSYMBOLX.TO", False),
    ("TD.TX", False), ("AAPL", False), ("600519", False),
])
def test_ca_symbol_recognition_consistent_across_entries(code, is_ca) -> None:
    """Every detector/normalizer agrees on what is a Canadian symbol (no base-vs-suffix drift)."""
    from data_provider.base import _is_ca_market
    assert (detect_market(code) == "ca") is is_ca
    assert (get_market_for_stock(code) == "ca") is is_ca
    assert _is_ca_market(code) is is_ca
    assert YfinanceFetcher._is_ca_suffix_stock(code) is is_ca
    if is_ca:
        from src.services.stock_code_utils import is_code_like, normalize_code
        assert is_code_like(code) is True
        assert normalize_code(code) == code
        assert normalize_stock_code(code) == code


def test_data_fetcher_manager_routes_ca_daily_only_to_yfinance() -> None:
    efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
    akshare = _FakeFetcher("AkshareFetcher", should_fail=True)
    yfinance = _FakeFetcher("YfinanceFetcher")
    manager = DataFetcherManager(fetchers=[efinance, akshare, yfinance])
    with patch("data_provider.base.record_provider_run_started"), patch("data_provider.base.record_provider_run"):
        ca_df, ca_source = manager.get_daily_data("TD.TO")
    assert ca_source == "YfinanceFetcher"
    assert not ca_df.empty
    assert efinance.calls == [] and akshare.calls == []
    assert yfinance.calls == ["TD.TO"]


def test_ca_fundamentals_use_offshore_path() -> None:
    """`ca` fundamentals must take the offshore branch (yfinance), not the A-share path."""
    manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
    with patch.object(manager, "_build_offshore_fundamental_context", return_value={"market": "ca", "ok": True}) as off:
        result = manager.get_fundamental_context("TD.TO")
    off.assert_called_once()
    assert off.call_args.kwargs.get("market", off.call_args.args[1] if len(off.call_args.args) > 1 else None) == "ca"
    assert result == {"market": "ca", "ok": True}
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_ca_market_support.py -k "ca_suffix or market_tag or routes_ca or offshore_path or consistent" -v`
Expected: FAIL (`_market_tag("TD.TO")=="cn"` or `"us"`; A-share fetchers attempted; offshore not called for ca).

- [ ] **Step 3: Add `_is_ca_market` in `data_provider/base.py`** (next to `_is_tw_market`):

```python
_CA_SUFFIX_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$')


def _is_ca_market(code: str) -> bool:
    """Canada Yahoo Finance suffix codes: TSX `.TO` / TSX-V `.V`.

    Validates the base (not just the suffix), so this agrees with detect_market /
    stock_code_utils: `.TO`, `FOO..TO`, and over-long bases are rejected everywhere.
    """
    return bool(_CA_SUFFIX_RE.match((code or "").strip().upper()))
```

- [ ] **Step 4: `_market_tag` — classify `ca` first**

In `_market_tag`, add as the **first** check (before `_is_us_market`):

```python
    if _is_ca_market(code):
        return "ca"
```

- [ ] **Step 5: Offshore quote gates** (two blocks, **different US helpers**)

The two blocks import different US helpers: the daily-data block (~line 1251) imports `is_us_stock_code`; the realtime block (~line 1700) imports `_is_us_code`. Use the matching name in each, compute `is_ca` first, and guard `is_us` so `.V` is not swallowed.

**Daily-data block (~lines 1264-1277):** change the detection lines and the no-source error label:

```python
        is_ca = _is_ca_market(stock_code)
        is_us = is_us_index or ((not is_ca) and is_us_stock_code(stock_code))
        is_hk = (not is_us) and (not is_ca) and _is_hk_market(stock_code)
        is_jp = (not is_us) and (not is_hk) and (not is_ca) and _is_jp_market(stock_code)
        is_kr = (not is_us) and (not is_hk) and (not is_ca) and _is_kr_market(stock_code)
        is_tw = (not is_us) and (not is_hk) and (not is_ca) and _is_tw_market(stock_code)
        market = "us" if is_us else "hk" if is_hk else "jp" if is_jp else "kr" if is_kr else "tw" if is_tw else "ca" if is_ca else "cn"
```

and the error label (~line 1277):

```python
            market_label = "美股指数" if is_us_index else "美股" if is_us else "港股" if is_hk else "台股" if is_tw else "加拿大股" if is_ca else "A股"
```

**Realtime block (~lines 1700-1708):**

```python
        is_ca = _is_ca_market(stock_code)
        is_us = is_us_index or ((not is_ca) and _is_us_code(stock_code))
        is_hk = (not is_us) and (not is_ca) and _is_hk_market(stock_code)
        is_jp = (not is_us) and (not is_hk) and (not is_ca) and _is_jp_market(stock_code)
        is_kr = (not is_us) and (not is_hk) and (not is_ca) and _is_kr_market(stock_code)
        is_tw = (not is_us) and (not is_hk) and (not is_ca) and _is_tw_market(stock_code)
        if is_jp or is_kr or is_tw or is_ca:
            market_label = "日股" if is_jp else "韩股" if is_kr else "台股" if is_tw else "加股"
```

- [ ] **Step 6: Capability + offshore fundamental gate in `data_provider/base.py`**

- Line 632: `"YfinanceFetcher": {"cn", "hk", "us", "jp", "kr", "tw", "ca"}`.
- Line 2971: `if market in {"us", "hk", "jp", "kr", "tw", "ca"}:`.

- [ ] **Step 7: `data_provider/yfinance_fetcher.py` — suffix helper + passthrough**

Add next to `_is_tw_suffix_stock`:

```python
    @staticmethod
    def _is_ca_suffix_stock(stock_code: str) -> bool:
        """True for supported Canada suffix-only Yahoo symbols (TSX `.TO` / TSX-V `.V`).

        Validates the base (same shape as detect_market) so all entries agree.
        """
        import re
        return bool(re.match(r'^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$', (stock_code or "").strip().upper()))
```

In `_convert_stock_code` (~line 144) add `or self._is_ca_suffix_stock(code)` to the passthrough condition; in the offshore-eligibility check (~line 798) add `or self._is_ca_suffix_stock(stock_code)`.

- [ ] **Step 8: Run to verify they pass**

Run: `pytest tests/test_ca_market_support.py -k "ca_suffix or market_tag or routes_ca or offshore_path or consistent" -v`
Expected: PASS

- [ ] **Step 9: Commit** (if authorized):

```bash
git add data_provider/base.py data_provider/yfinance_fetcher.py tests/test_ca_market_support.py
git commit -m "feat(ca): route .TO/.V to Yahoo; classify via _market_tag; enable offshore fundamentals"
```

---

### Task 5: Make `ca` first-class on backend write/API paths (+ Pydantic validation)

**Files:**
- Modify: `src/services/portfolio_service.py` (`VALID_MARKETS`), `src/services/intelligence_service.py:31` (`_ALLOWED_MARKETS`), `src/services/decision_signal_service.py:869` (error string)
- Modify: `src/core/pipeline.py:1471`, `src/market_phase_summary.py:145` (`{jp,kr,tw}` → add `ca`)
- Modify: `api/v1/schemas/portfolio.py` (×4 `Literal`), `api/v1/schemas/decision_signals.py:19`, `api/v1/schemas/intelligence.py:12`, `api/v1/endpoints/decision_signals.py:126,309`; `src/market_context.py:20` docstring
- Test: `tests/test_ca_market_support.py`

**Interfaces:** Produces `DecisionSignalService._normalize_market("ca") == "ca"`; `"ca" in VALID_MARKETS`/`_ALLOWED_MARKETS`; API portfolio account schema accepts `market="ca"`.

- [ ] **Step 1: Write the failing test** (append):

```python
def test_ca_is_first_class_on_write_paths() -> None:
    from src.services.decision_signal_service import DecisionSignalService
    from src.services.portfolio_service import VALID_MARKETS
    from src.services.intelligence_service import _ALLOWED_MARKETS

    assert get_market_for_stock("TD.TO") == "ca"
    assert DecisionSignalService._normalize_market("ca") == "ca"
    assert "ca" in VALID_MARKETS and "ca" in _ALLOWED_MARKETS


def test_ca_accepted_by_portfolio_api_schema() -> None:
    """Pydantic Literal must accept market='ca' (not just Python sets)."""
    from api.v1.schemas.portfolio import PortfolioAccountCreateRequest
    model = PortfolioAccountCreateRequest(name="RRSP", market="ca", base_currency="CAD")
    assert model.market == "ca"
```

(`PortfolioAccountCreateRequest` is the create model at `api/v1/schemas/portfolio.py:8`; `market` is its `Literal[...]` field. `PortfolioAccountUpdateRequest` at `:16` carries the same `Optional[Literal[...]]`.)

- [ ] **Step 2: Run to verify they fail** — `pytest tests/test_ca_market_support.py -k "first_class or portfolio_api_schema" -v` → FAIL (`_normalize_market("ca")` raises; Pydantic `ValidationError` for `"ca"`).

- [ ] **Step 3: Implement enum additions**

- `VALID_MARKETS` += `"ca"`; `_ALLOWED_MARKETS` += `"ca"`.
- decision_signal_service.py:869 string → `"market must be one of cn, hk, us, jp, kr, tw, ca"`.
- pipeline.py:1471 & market_phase_summary.py:145 → `{"jp", "kr", "tw", "ca"}`.
- Each API `Literal[...]` (`portfolio.py` ×4, `decision_signals.py:19`, `intelligence.py:12`) → append `"ca"`.
- decision_signals.py:126,309 Query descriptions → append `/ca`.
- market_context.py:20 docstring → mention `ca`.

- [ ] **Step 4: Run to verify they pass** — `pytest tests/test_ca_market_support.py -k "first_class or portfolio_api_schema" -v` → PASS.
- [ ] **Step 5: Run the full CA suite + gate** — `pytest tests/test_ca_market_support.py -v && pytest -m "not network" -q` → PASS.
- [ ] **Step 6: Commit** (if authorized):

```bash
git add src/services/portfolio_service.py src/services/intelligence_service.py src/services/decision_signal_service.py src/core/pipeline.py src/market_phase_summary.py api/v1/schemas/portfolio.py api/v1/schemas/decision_signals.py api/v1/schemas/intelligence.py api/v1/endpoints/decision_signals.py src/market_context.py tests/test_ca_market_support.py
git commit -m "feat(ca): make ca first-class on write/API/offshore paths"
```

---

### Task 6: Web — accept, filter, and label `ca` (apps/dsa-web)

**Files:**
- Modify: `apps/dsa-web/src/types/decisionSignals.ts:13` (`DecisionSignalMarket` union)
- Modify: `apps/dsa-web/src/types/portfolio.ts:13,27,184,204` (market unions ×4)
- Modify: `apps/dsa-web/src/utils/decisionSignalLabels.ts:12-18` (`MARKET_LABEL_KEYS` Record)
- Modify: `apps/dsa-web/src/pages/DecisionSignalsPage.tsx:66` (`MARKET_OPTIONS`)
- Modify: `apps/dsa-web/src/pages/PortfolioPage.tsx:115-116` (`DECISION_SIGNAL_MARKETS` set + `PortfolioAccountMarket`), `:1095` (market `<option>`)
- Modify: the i18n resources defining `decisionSignals.market.tw` (add `decisionSignals.market.ca`, zh "加拿大" / en "Canada")

**Interfaces:** Consumes backend `ca` (Task 5). `MARKET_LABEL_KEYS` is `Record<DecisionSignalMarket, UiTextKey>`, so adding `'ca'` to the union forces adding the `ca` key + i18n entry (TS exhaustiveness).

- [ ] **Step 1: Add `'ca'` to the unions** — `decisionSignals.ts:13` and each `portfolio.ts` union (`:13,:27,:184,:204`): `... | 'tw' | 'ca'`.
- [ ] **Step 2: Add the label key** — `decisionSignalLabels.ts` `MARKET_LABEL_KEYS`: `ca: 'decisionSignals.market.ca',`.
- [ ] **Step 3: Add the i18n strings** — locate the resource entries for `decisionSignals.market.tw` (zh + en) and add sibling `decisionSignals.market.ca` = "加拿大" (zh) / "Canada" (en).
- [ ] **Step 4: Add to filters/options** — `DecisionSignalsPage.tsx:66` `MARKET_OPTIONS` append `'ca'`; `PortfolioPage.tsx:115` `DECISION_SIGNAL_MARKETS` set append `'ca'`; `:116` `PortfolioAccountMarket` union append `| 'ca'`; after `:1095` add `<option value="ca">市场：加拿大（ca）</option>`.
- [ ] **Step 5: Add a frontend test** that Canada is a visible, selectable option (build proves types, not visible options). Mirror the nearest existing page/selector test in `apps/dsa-web/src` (or component test setup). Minimum assertions: the decision-signal market filter renders a `ca` option, and the portfolio account market selector includes `加拿大（ca）`. If the web project has no component test harness, add a small unit test over `MARKET_OPTIONS`/`DECISION_SIGNAL_MARKETS` asserting they contain `'ca'`, and over `getDecisionSignalMarketLabel('ca', t)` asserting it resolves (not the raw key).

- [ ] **Step 6: Lint + type-check + build + test** (TS exhaustiveness catches any missed Record/union site):

```bash
cd apps/dsa-web && npm ci && npm run lint && npm run build && npm test
```
Expected: PASS. If the build flags another closed union/Record referencing `DecisionSignalMarket` or `PortfolioAccountMarket`, add `'ca'` there too and rebuild.

- [ ] **Step 7: Capture visual evidence for the PR** — per `AGENTS.md`, UI changes require before/after screenshots in the PR description. Capture the decision-signal market filter (showing `ca`) and the portfolio account market selector (showing `加拿大（ca）`). **Save screenshots outside the repo** (PR description / attachment) — do **not** commit image files into the repo.

- [ ] **Step 8: Commit** (if authorized):

```bash
git add apps/dsa-web/src
git commit -m "feat(ca): accept, filter, and label ca market in web UI"
```

---

### Task 7: Documentation

**Files:** Modify `docs/market-support.md`, `docs/CHANGELOG.md`.

- [ ] **Step 1: Add a Canada section to `docs/market-support.md`** mirroring the Taiwan section: supported formats (`SYM.TO` TSX, `SYM.V` TSX-V; alphabetic/hyphenated base), constraints (Yahoo-only data; A-share-specific blocks degrade `not_supported`; no real-time guarantee), calendar (`ca: XTSE / America/Toronto`), non-commitments (no full fundamentals/market-breadth/Canadian market review yet; `^GSPTSE` review + autocomplete are follow-ups; CDR `.NE` is a separate follow-up), and a rollback note.
- [ ] **Step 2: Add a CHANGELOG line** under `[Unreleased]`:

```
- [新功能] 支持加拿大 TSX（`.TO`）/ TSX-V（`.V`）个股的 suffix-only 分析（市场识别、code-utils、Yahoo 数据路由、offshore 基本面、XTSE 交易日历、中英文 Prompt、后端枚举与 Web 类型/筛选/标签）。
```

- [ ] **Step 3: Verify the gate** — run `./scripts/ci_gate.sh` (the repo's default backend gate). Expected: PASS. If it fails, record the specific failure (command + output) and fix the cause — do not substitute a narrower command.
- [ ] **Step 4: Commit** (if authorized):

```bash
git add docs/market-support.md docs/CHANGELOG.md
git commit -m "docs(ca): document Canadian TSX/TSX-V market support"
```

---

## Self-Review

**Spec coverage (Tier 0):** detection before US branch ✓ (T1, incl. `stock_code_utils`); calendar ✓ (T2); bilingual prompt ✓ (T3); Yahoo routing + `_market_tag` + offshore quote/fundamental gates + capability + proof test ✓ (T4); backend enums + Pydantic validation ✓ (T5); **web types/filters/labels ✓ (T6, now included per spec)**; docs ✓ (T7). Deferred per spec (NOT here): `get_main_indices("ca")`/`^GSPTSE` market review and the `{cn,hk,us}`-only feature gates (Tier 4); CDR `.NE` (Tier 2).

**Placeholder scan:** no conditional "locate at execution" steps — the routing gate is fully specified (`_is_ca_market`, `_market_tag`, the two quote-gate blocks, capability, fundamental gate). Remaining "if the build flags another union" / "if model name differs" notes are TS-compiler-driven or naming confirmations tied to a runnable check, not deferred design.

**Type consistency:** market key `"ca"`, exchange `"XTSE"`, tz `"America/Toronto"`, helpers `_is_ca_market` (base) / `_is_ca_suffix_stock` (yfinance), regex `^[A-Z0-9][A-Z0-9\-]{0,11}\.(TO|V)$`, web union member `'ca'`, label key `decisionSignals.market.ca` — consistent across tasks. Test symbols (`TD.TO`, `SHOP.TO`, `ENB.TO`, `BAM-A.TO`, `ABC.V`) consistent.

**Process:** every `Commit` step is gated on explicit user authorization per repo rule.
