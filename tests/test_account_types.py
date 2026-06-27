# -*- coding: utf-8 -*-
"""Regression tests for portfolio account-type labels."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


def test_canadian_account_types_and_normalization() -> None:
    from src.portfolio.account_types import (
        CA_ACCOUNT_TYPES,
        account_types_for_market,
        is_known_account_type,
        normalize_account_type,
    )

    assert account_types_for_market("ca") == CA_ACCOUNT_TYPES
    assert account_types_for_market(" CA ") == CA_ACCOUNT_TYPES
    assert account_types_for_market("us") == []
    assert "non_registered_margin" in CA_ACCOUNT_TYPES
    assert is_known_account_type("RRSP") is True
    assert is_known_account_type("totally_custom") is False
    assert normalize_account_type("  RRSP ") == "rrsp"
    assert normalize_account_type("Custom_Thing") == "custom_thing"
    assert normalize_account_type("") is None
    assert normalize_account_type(None) is None


def test_portfolio_account_has_account_type_column() -> None:
    from src.storage import PortfolioAccount

    assert "account_type" in PortfolioAccount.__table__.columns


def test_account_type_backfill_is_idempotent_on_legacy_database() -> None:
    from src.config import Config
    from src.storage import DatabaseManager

    previous_database_path = os.environ.get("DATABASE_PATH")
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "legacy.db")
    try:
        connection = sqlite3.connect(db_path)
        connection.execute(
            "CREATE TABLE portfolio_accounts ("
            "id INTEGER PRIMARY KEY, owner_id TEXT, name TEXT NOT NULL, broker TEXT, "
            "market TEXT NOT NULL DEFAULT 'cn', base_currency TEXT NOT NULL DEFAULT 'CNY', "
            "is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME, updated_at DATETIME)"
        )
        connection.commit()
        connection.close()

        os.environ["DATABASE_PATH"] = db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        DatabaseManager.get_instance()

        DatabaseManager.reset_instance()
        Config.reset_instance()
        DatabaseManager.get_instance()

        connection = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(portfolio_accounts)")
            if row[1] == "account_type"
        ]
        connection.close()
        assert columns == ["account_type"]
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if previous_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous_database_path
        tmp.cleanup()


class AccountTypeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from src.config import Config
        from src.storage import DatabaseManager

        self._previous_database_path = os.environ.get("DATABASE_PATH")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp.name, "portfolio.db")
        Config.reset_instance()
        DatabaseManager.reset_instance()
        DatabaseManager.get_instance()

    def tearDown(self) -> None:
        from src.config import Config
        from src.storage import DatabaseManager

        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._previous_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._previous_database_path
        self._tmp.cleanup()

    def test_create_update_clear_and_preserve_account_type(self) -> None:
        from src.services.portfolio_service import PortfolioService

        service = PortfolioService()
        created = service.create_account(
            name="RRSP",
            broker="WS",
            market="ca",
            base_currency="CAD",
            account_type="  RRSP ",
        )
        account_id = created["id"]
        self.assertEqual(created["account_type"], "rrsp")

        updated = service.update_account(account_id, account_type="TFSA")
        self.assertEqual(updated["account_type"], "tfsa")

        cleared = service.update_account(account_id, account_type=None)
        self.assertIsNone(cleared["account_type"])

        service.update_account(account_id, account_type="FHSA")
        preserved = service.update_account(account_id, name="Renamed")
        self.assertEqual(preserved["account_type"], "fhsa")
        listed = next(item for item in service.list_accounts() if item["id"] == account_id)
        self.assertEqual(listed["account_type"], "fhsa")


def _account_item_payload(account_type=None):
    return {
        "id": 7,
        "owner_id": None,
        "name": "Account",
        "broker": None,
        "market": "ca",
        "base_currency": "CAD",
        "account_type": account_type,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }


def test_portfolio_api_schema_accepts_free_string_account_type() -> None:
    from api.v1.schemas.portfolio import (
        PortfolioAccountCreateRequest,
        PortfolioAccountItem,
        PortfolioAccountUpdateRequest,
    )

    request = PortfolioAccountCreateRequest(
        name="Custom",
        market="ca",
        base_currency="CAD",
        account_type="custom_thing",
    )
    assert request.account_type == "custom_thing"
    assert "account_type" in PortfolioAccountItem.model_fields
    assert "account_type" not in PortfolioAccountUpdateRequest(name="x").model_fields_set
    assert "account_type" in PortfolioAccountUpdateRequest(account_type=None).model_fields_set


def test_update_endpoint_distinguishes_omitted_from_explicit_null() -> None:
    from api.v1.endpoints.portfolio import update_account
    from api.v1.schemas.portfolio import PortfolioAccountUpdateRequest

    with patch("api.v1.endpoints.portfolio.PortfolioService") as service_class:
        service = service_class.return_value
        service.update_account.return_value = _account_item_payload("rrsp")
        update_account(7, PortfolioAccountUpdateRequest(name="Renamed"))
        assert "account_type" not in service.update_account.call_args.kwargs

        service.update_account.reset_mock()
        service.update_account.return_value = _account_item_payload(None)
        result = update_account(7, PortfolioAccountUpdateRequest(account_type=None))
        assert service.update_account.call_args.kwargs["account_type"] is None
        assert result.account_type is None
