"""Retail-markup behaviour — parity with the TS SDK's markup.test.ts.

The key regression guard: a ``usdt_ton`` quote with NO ``fee`` breakdown must be REFUSED, not
silently marked up on the fee-inclusive ``amount`` (which over-charges + mislabels "Goods").
Mirrors the TypeScript SDK markup tests and the same fix (markup.ts).
"""

from __future__ import annotations

import pytest

from mystars_faas import MyStarsValidationError, apply_retail_markup


def test_usdt_ton_without_fee_breakdown_is_refused():
    # /v1/pricing returns fee:null for usdt_ton on cold-FX / pre-023 rows. `amount` is
    # fee-inclusive, so marking it up would mark up the processing fee + mislabel goods.
    with pytest.raises(MyStarsValidationError):
        apply_retail_markup(
            {"amount": "5.56", "currency": "usdt_ton", "fee": None}, margin_pct=20
        )


def test_usdt_ton_with_fee_breakdown_computes():
    q = apply_retail_markup(
        {
            "amount": "5.56",
            "currency": "usdt_ton",
            "fee": {"subtotal": "5.00", "processing_fee": "0.56"},
        },
        margin_pct=20,
    )
    assert q.currency == "usdt_ton"
    assert q.goods == "5.00"
    # +20% on the 5.00 goods → 6.00 retail goods; the 0.56 fee is passed through separately.
    assert q.subtotal == "6.00"
    assert q.processing_fee == "0.56"
    assert q.total == "6.56"


def test_ton_quote_is_unaffected_by_the_fee_guard():
    q = apply_retail_markup({"amount": "1.0", "currency": "ton", "fee": None}, margin_pct=10)
    assert q.currency == "ton"
    assert q.processing_fee == "0"
    # +10% on 1.0 TON, ceil to the 0.0001 grid.
    assert q.total == "1.1"


def test_negative_margin_is_refused():
    with pytest.raises(MyStarsValidationError):
        apply_retail_markup({"amount": "1.0", "currency": "ton", "fee": None}, margin_pct=-5)
