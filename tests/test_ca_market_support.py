# -*- coding: utf-8 -*-
"""Regression tests for Canada (TSX/TSX-V) suffix-only market support.

Mirrors tests/test_tw_market_support.py. Canadian common stocks use Yahoo Finance
suffix forms ``SYM.TO`` (TSX) and ``SYM.V`` (TSX Venture). The base is alphabetic
(optionally hyphenated, e.g. ``BAM-A.TO``); the ``.TO``/``.V`` check must precede
the US branch in every detector. Bare codes are unaffected.
"""

from unittest.mock import patch

import pandas as pd
import pytest
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


def test_trading_calendar_registers_ca_exchange_and_timezone() -> None:
    assert MARKET_EXCHANGE["ca"] == "XTSE"
    assert MARKET_TIMEZONE["ca"] == "America/Toronto"
