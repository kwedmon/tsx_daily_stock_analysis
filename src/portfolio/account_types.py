# -*- coding: utf-8 -*-
"""Account-type option sets and normalization (label-only; no tax logic)."""

from typing import Dict, List, Optional


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
    """Return suggested account types for a market."""
    return list(_ACCOUNT_TYPES_BY_MARKET.get((market or "").strip().lower(), []))


def is_known_account_type(value: str) -> bool:
    """Return whether a value is in any known market option set."""
    normalized = (value or "").strip().lower()
    return any(normalized in values for values in _ACCOUNT_TYPES_BY_MARKET.values())


def normalize_account_type(value: Optional[str]) -> Optional[str]:
    """Strip and lowercase a label, normalizing empty values to ``None``."""
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None
