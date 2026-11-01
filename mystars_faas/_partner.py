"""Request builders for the partner products (contract 2.1.0), shared by the sync and async resources.

Each builder validates its input client-side (raising :class:`MyStarsValidationError` before any
request) and returns the :class:`_Request` to send, so the two clients cannot drift apart.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Mapping, Sequence
from typing import Any

from ._transport import _Request
from ._validate import assert_payment_currency, assert_premium_months, assert_stars_quantity
from .errors import MyStarsValidationError

#: Recipients accepted per campaign create / append request.
MAX_RECIPIENTS_PER_REQUEST = 5000
#: Telegram user ids per attestation request.
ATTESTATION_BATCH_MAX = 1000
#: A giveaway's shortest run, in seconds.
GIVEAWAY_DURATION_MIN_SEC = 60
#: Idempotency-Key prefix reserved for recurring-series occurrences.
RESERVED_SERIES_KEY_PREFIX = "series:"
_IDEMPOTENCY_KEY_MAX = 255
_GIFT_ID_RE = re.compile(r"^\d+$")
_CONDITION_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_TELEGRAM_ID_RE = re.compile(r"^[1-9]\d{0,15}$")
_MAX_SAFE_INTEGER = 2**53 - 1


def seg(value: str) -> str:
    """Percent-encode an id for a path segment."""
    return urllib.parse.quote(str(value), safe="")


def with_replayed(data: Any, status: int, headers: Mapping[str, str]) -> dict[str, Any]:
    """The answer plus ``replayed`` — ``True`` when the server answered from an earlier request with the key."""
    replayed = status == 200 or headers.get("idempotent-replayed") == "true"
    return {**(data or {}), "replayed": replayed}


def checked_key(key: str) -> str:
    if not key.strip() or len(key) > _IDEMPOTENCY_KEY_MAX:
        raise MyStarsValidationError(f"idempotency_key must be 1..{_IDEMPOTENCY_KEY_MAX} characters")
    return key


def _positive_int(value: Any, name: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise MyStarsValidationError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return value


def _recipients(recipients: Any) -> list[str]:
    if not isinstance(recipients, (list, tuple)) or not recipients:
        raise MyStarsValidationError("recipients must be a non-empty list of Telegram usernames")
    if len(recipients) > MAX_RECIPIENTS_PER_REQUEST:
        raise MyStarsValidationError(
            f"recipients accepts at most {MAX_RECIPIENTS_PER_REQUEST} usernames per request — append the rest with add_recipients"
        )
    if not all(isinstance(r, str) for r in recipients):
        raise MyStarsValidationError("recipients must contain only strings")
    return list(recipients)


def _clean(values: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in values.items():
        if v is None:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else v
    return out


# ─── campaigns ────────────────────────────────────────────────────────────────


def campaign_create(
    *,
    product: str,
    payment_currency: str,
    recipients: Sequence[str],
    quantity: int | None,
    months: int | None,
    gift_id: str | None,
    comment: str | None,
    hide_name: bool | None,
    key: str,
) -> _Request:
    assert_payment_currency(payment_currency)
    body: dict[str, Any] = {"product": product}
    if product == "stars":
        assert_stars_quantity(quantity)  # type: ignore[arg-type]
        body["quantity"] = quantity
    elif product == "premium":
        assert_premium_months(months)  # type: ignore[arg-type]
        body["months"] = months
    elif product == "star_gift":
        if not isinstance(gift_id, str) or not _GIFT_ID_RE.match(gift_id):
            raise MyStarsValidationError("gift_id must be the star gift id as a string of digits (see gifts.list)")
        body["gift_id"] = gift_id
        if comment is not None:
            body["comment"] = comment
        if hide_name is not None:
            body["hide_name"] = hide_name
    else:
        raise MyStarsValidationError(f'product must be "stars", "premium" or "star_gift", got {product!r}')
    body["payment_currency"] = payment_currency
    body["recipients"] = _recipients(recipients)
    return _Request("POST", "/campaigns", json_body=body, idempotency_key=checked_key(key))


def campaign_add_recipients(campaign_id: str, recipients: Sequence[str], key: str) -> _Request:
    return _Request(
        "POST", f"/campaigns/{seg(campaign_id)}/recipients", json_body={"recipients": _recipients(recipients)},
        idempotency_key=checked_key(key),
    )


def campaign_action(campaign_id: str, name: str) -> _Request:
    # resume is not retried: a retry after a lost success reads as a conflict.
    return _Request("POST", f"/campaigns/{seg(campaign_id)}/{name}", idempotent=name != "resume")


def campaign_get(campaign_id: str, suffix: str = "") -> _Request:
    return _Request("GET", f"/campaigns/{seg(campaign_id)}{suffix}")


def campaigns_list(status: str | None, limit: int | None, cursor: str | None) -> _Request:
    return _Request("GET", "/campaigns", params=_clean({"status": status, "limit": limit, "cursor": cursor}))


def campaign_recipients(
    campaign_id: str, verdict: str | None, status: str | None, reason: str | None, limit: int | None, cursor: str | None
) -> _Request:
    return _Request(
        "GET", f"/campaigns/{seg(campaign_id)}/recipients",
        params=_clean({"verdict": verdict, "status": status, "reason": reason, "limit": limit, "cursor": cursor}),
    )


def capacity(type: str, recipients: int | None) -> _Request:
    return _Request("GET", "/capacity", params=_clean({"type": type, "recipients": recipients}))


def gifts_list(currency: str) -> _Request:
    if currency is None:
        raise MyStarsValidationError('currency is required ("ton" or "usdt_ton")')
    assert_payment_currency(currency)
    return _Request("GET", "/gifts", params={"currency": currency})


# ─── giveaways ────────────────────────────────────────────────────────────────


def _template(t: Mapping[str, Any], name: str = "giveaway") -> dict[str, Any]:
    if not isinstance(t, Mapping):
        raise MyStarsValidationError(f"{name} must be a mapping")
    if not isinstance(t.get("channel_id"), str) or not t.get("channel_id"):
        raise MyStarsValidationError(f"{name}.channel_id is required (a registered chat id)")
    if t.get("prize_type") not in ("stars", "premium", "gift"):
        raise MyStarsValidationError(f'{name}.prize_type must be "stars", "premium" or "gift"')
    _positive_int(t.get("prize_quantity_per_winner"), f"{name}.prize_quantity_per_winner")
    _positive_int(t.get("winner_count"), f"{name}.winner_count")
    _positive_int(t.get("duration_sec"), f"{name}.duration_sec", GIVEAWAY_DURATION_MIN_SEC)
    conditions = t.get("conditions")
    if conditions is not None and (not isinstance(conditions, (list, tuple)) or len(conditions) > 3):
        raise MyStarsValidationError(f"{name}.conditions holds at most 3 conditions")
    return {k: v for k, v in t.items() if v is not None}


def _not_reserved(key: str) -> str:
    if key.strip().startswith(RESERVED_SERIES_KEY_PREFIX):
        raise MyStarsValidationError(f'idempotency_key must not start with "{RESERVED_SERIES_KEY_PREFIX}" (reserved)')
    return checked_key(key)


def channels_register(chat: str, invite_link: str | None, key: str) -> _Request:
    if not isinstance(chat, str) or len(chat.strip()) < 2:
        raise MyStarsValidationError("chat must be an @username, a chat id or a link")
    body: dict[str, Any] = {"chat": chat}
    if invite_link is not None:
        body["invite_link"] = invite_link
    return _Request("POST", "/giveaways/channels", json_body=body, idempotency_key=checked_key(key))


def keyed_post(path: str, key: str, body: dict[str, Any] | None = None) -> _Request:
    return _Request("POST", path, json_body=body, idempotency_key=checked_key(key))


def delete(path: str) -> _Request:
    return _Request("DELETE", path, idempotent=True)


def giveaway_quote(
    prize_type: str, prize_quantity_per_winner: int, winner_count: int, currency: str | None, gift_id: str | None
) -> _Request:
    _positive_int(prize_quantity_per_winner, "prize_quantity_per_winner")
    _positive_int(winner_count, "winner_count")
    if currency is not None:
        assert_payment_currency(currency)
    return _Request(
        "GET", "/giveaways/quote",
        params=_clean({
            "prize_type": prize_type, "prize_quantity_per_winner": prize_quantity_per_winner,
            "winner_count": winner_count, "currency": currency, "gift_id": gift_id,
        }),
    )


def giveaway_create(template: Mapping[str, Any], key: str) -> _Request:
    k = _not_reserved(key)
    return _Request("POST", "/giveaways", json_body=_template(template), idempotency_key=k)


def giveaways_list(status: str | None, series_id: str | None, limit: int | None, cursor: str | None) -> _Request:
    return _Request("GET", "/giveaways", params=_clean({"status": status, "series_id": series_id, "limit": limit, "cursor": cursor}))


def giveaway_fund(giveaway_id: str, currency: str | None, key: str) -> _Request:
    if currency is not None:
        assert_payment_currency(currency)
    body = {} if currency is None else {"currency": currency}
    return keyed_post(f"/giveaways/{seg(giveaway_id)}/fund", key, body)


def giveaway_entrants(
    giveaway_id: str, status: str | None, filter_reason: str | None, condition_status: str | None, limit: int | None, cursor: str | None
) -> _Request:
    return _Request(
        "GET", f"/giveaways/{seg(giveaway_id)}/entrants",
        params=_clean({
            "status": status, "filter_reason": filter_reason, "condition_status": condition_status,
            "limit": limit, "cursor": cursor,
        }),
    )


def _telegram_id(value: Any) -> int | str:
    if isinstance(value, bool):
        raise MyStarsValidationError(f"not a Telegram user id: {value!r}")
    if isinstance(value, int) and 0 < value <= _MAX_SAFE_INTEGER:
        return value
    if isinstance(value, str) and _TELEGRAM_ID_RE.match(value):
        return value
    raise MyStarsValidationError(f"not a Telegram user id: {value!r}")


def giveaway_attest(giveaway_id: str, condition_key: str, telegram_user_ids: Sequence[int | str], satisfied: bool, key: str) -> _Request:
    if not isinstance(condition_key, str) or not _CONDITION_KEY_RE.match(condition_key):
        raise MyStarsValidationError("condition_key must match [a-z0-9_]{1,32}")
    if not isinstance(satisfied, bool):
        raise MyStarsValidationError("satisfied must be a bool")
    if not isinstance(telegram_user_ids, (list, tuple)) or not 1 <= len(telegram_user_ids) <= ATTESTATION_BATCH_MAX:
        raise MyStarsValidationError(f"telegram_user_ids must hold 1..{ATTESTATION_BATCH_MAX} ids")
    ids = [_telegram_id(v) for v in telegram_user_ids]
    body = {"condition_key": condition_key, "telegram_user_ids": ids, "satisfied": satisfied}
    return keyed_post(f"/giveaways/{seg(giveaway_id)}/attestations", key, body)


def giveaway_attestations(giveaway_id: str, condition_key: str | None, satisfied: bool | None, limit: int | None, cursor: str | None) -> _Request:
    return _Request(
        "GET", f"/giveaways/{seg(giveaway_id)}/attestations",
        params=_clean({"condition_key": condition_key, "satisfied": satisfied, "limit": limit, "cursor": cursor}),
    )


def series_create(
    *,
    template: Mapping[str, Any],
    interval: str,
    starts_at: str,
    every: int | None,
    count: int | None,
    until: str | None,
    currency: str | None,
    on_unfunded: str | None,
    key: str,
) -> _Request:
    k = _not_reserved(key)
    body: dict[str, Any] = {"template": _template(template, "template")}
    if interval not in ("day", "week", "month"):
        raise MyStarsValidationError('interval must be "day", "week" or "month"')
    body["interval"] = interval
    if every is not None:
        body["every"] = _positive_int(every, "every")
    body["starts_at"] = starts_at
    if (count is None) == (until is None):
        raise MyStarsValidationError("give exactly one of count and until")
    if count is not None:
        body["count"] = _positive_int(count, "count")
    if until is not None:
        body["until"] = until
    if currency is not None:
        assert_payment_currency(currency)
        body["currency"] = currency
    if on_unfunded is not None:
        body["on_unfunded"] = on_unfunded
    return _Request("POST", "/giveaways/series", json_body=body, idempotency_key=k)


def series_list(status: str | None, limit: int | None, cursor: str | None) -> _Request:
    return _Request("GET", "/giveaways/series", params=_clean({"status": status, "limit": limit, "cursor": cursor}))
