"""Lightweight client-side validation mirroring the server's documented constraints."""

from __future__ import annotations

import re

from .errors import MyStarsValidationError

STARS_MIN_QUANTITY = 50
STARS_MAX_QUANTITY = 1_000_000
PREMIUM_MONTHS = (3, 6, 12)
_USERNAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def canonical_username(value: str) -> str:
    """Strip a leading ``@`` and lowercase, the same way the server canonicalizes."""
    if not isinstance(value, str):
        raise MyStarsValidationError("recipient username must be a string")
    canon = value.strip().lstrip("@").lower()
    if not _USERNAME_RE.match(canon):
        raise MyStarsValidationError(
            f'invalid recipient username "{value}" — expected 1-32 chars of [a-z0-9_] (a leading @ is allowed)'
        )
    return canon


def assert_stars_quantity(quantity: int) -> None:
    """Validate a Stars quantity against the server's bounds.

    Args:
        quantity: The star count to check.

    Raises:
        MyStarsValidationError: If it is not an int in
            ``[STARS_MIN_QUANTITY, STARS_MAX_QUANTITY]`` (50–1,000,000).
    """
    if not isinstance(quantity, int) or quantity < STARS_MIN_QUANTITY or quantity > STARS_MAX_QUANTITY:
        raise MyStarsValidationError(
            f"stars quantity must be an integer in [{STARS_MIN_QUANTITY}, {STARS_MAX_QUANTITY}], got {quantity}"
        )


def assert_premium_months(months: int) -> None:
    """Validate a Premium duration against the allowed set.

    Args:
        months: The duration to check.

    Raises:
        MyStarsValidationError: If it is not one of ``PREMIUM_MONTHS`` (3, 6, or 12).
    """
    if months not in PREMIUM_MONTHS:
        raise MyStarsValidationError(f"premium months must be one of {PREMIUM_MONTHS}, got {months}")


def assert_order_type(type_: str) -> None:
    """Validate an order/product type.

    Args:
        type_: The type string to check.

    Raises:
        MyStarsValidationError: If it is not ``"stars"`` or ``"premium"``.
    """
    if type_ not in ("stars", "premium"):
        raise MyStarsValidationError(f'type must be "stars" or "premium", got {type_!r}')
