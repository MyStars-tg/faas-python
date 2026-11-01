"""FastAPI / Flask tenant-webhook helpers, exercised against stand-in framework modules (the extras are optional)."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from conftest import load_contract

V = load_contract("webhook-v2-vectors.json")
CASE = next(c for c in V["cases"] if c["name"] == "envelope_campaign_paid")


class _Response:
    def __init__(self, status_code: int, content: str) -> None:
        self.status_code = status_code
        self.content = content


class _Request:
    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


@pytest.fixture
def fake_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("fastapi")
    mod.Request = _Request  # type: ignore[attr-defined]
    mod.Response = _Response  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastapi", mod)


def test_fastapi_tenant_route(fake_fastapi: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import mystars_faas.webhook as webhook
    from mystars_faas.integrations.fastapi import faas_tenant_webhook_route

    monkeypatch.setattr(webhook.time, "time", lambda: CASE["timestamp"])
    seen: list[Any] = []
    handler = faas_tenant_webhook_route(CASE["secret"], seen.append)
    good = asyncio.run(handler(_Request(CASE["body"].encode(), {"x-faas-signature-v2": CASE["expected_headers"]["X-Faas-Signature-V2"]})))
    assert good.status_code == 200 and seen[0].type == "campaign.paid"
    bad = asyncio.run(handler(_Request(CASE["body"].encode(), {"x-faas-signature-v2": "t=1,v1=00"})))
    assert bad.status_code == 400 and len(seen) == 1
    overlong = asyncio.run(handler(_Request(CASE["body"].encode(), {"x-faas-signature-v2": "t=" + "1" * 5000 + ",v1=ab"})))
    assert overlong.status_code == 400 and len(seen) == 1


def test_flask_tenant_view(monkeypatch: pytest.MonkeyPatch) -> None:
    import mystars_faas.webhook as webhook

    flask = types.ModuleType("flask")
    flask.request = types.SimpleNamespace(  # type: ignore[attr-defined]
        get_data=lambda: CASE["body"].encode(),
        headers={"X-Faas-Signature-V2": CASE["expected_headers"]["X-Faas-Signature-V2"]},
    )
    monkeypatch.setitem(sys.modules, "flask", flask)
    monkeypatch.setattr(webhook.time, "time", lambda: CASE["timestamp"])
    from mystars_faas.integrations.flask import faas_tenant_webhook_view

    seen: list[Any] = []
    assert faas_tenant_webhook_view(CASE["secret"], seen.append)() == ("ok", 200)
    assert seen[0].id == CASE["event_id"]
    assert faas_tenant_webhook_view("wrong", seen.append)() == ("invalid signature", 400)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1], ids=repr)
def test_the_adapters_refuse_a_misconfigured_tolerance_when_built(bad: float, fake_fastapi: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from mystars_faas import MyStarsValidationError
    from mystars_faas.integrations.fastapi import faas_tenant_webhook_route

    flask = types.ModuleType("flask")
    flask.request = types.SimpleNamespace()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "flask", flask)
    from mystars_faas.integrations.flask import faas_tenant_webhook_view

    with pytest.raises(MyStarsValidationError, match="tolerance_sec"):
        faas_tenant_webhook_route(CASE["secret"], lambda _e: None, tolerance_sec=bad)
    with pytest.raises(MyStarsValidationError, match="tolerance_sec"):
        faas_tenant_webhook_view(CASE["secret"], lambda _e: None, tolerance_sec=bad)
