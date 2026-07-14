from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Union

import httpx

from mystars_faas import MyStarsClient
from mystars_faas._transport import RetryPolicy

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contract"

API_KEY = "faas_" + "a" * 64

Spec = dict[str, Any]
Script = Union[list[Spec], Callable[[httpx.Request, int], Spec]]


def load_contract(name: str) -> Any:
    return json.loads((CONTRACT_DIR / name).read_text())


def _mock_transport(script: Script) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        idx = len(calls)
        calls.append(request)
        if callable(script):
            spec = script(request, idx)
        else:
            spec = script[min(idx, len(script) - 1)]
        status = spec.get("status", 200)
        body = spec.get("json")
        headers = {"content-type": "application/json", **spec.get("headers", {})}
        content = b"" if body is None else json.dumps(body).encode()
        return httpx.Response(status, headers=headers, content=content)

    return httpx.MockTransport(handler), calls


def make_client(
    script: Script,
    *,
    retry: RetryPolicy | None = None,
    sleeps: list[float] | None = None,
) -> tuple[MyStarsClient, list[httpx.Request]]:
    transport, calls = _mock_transport(script)

    def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    client = MyStarsClient(
        API_KEY,
        transport=transport,
        retry=retry or RetryPolicy(base_delay=0.001, max_retries=3, jitter=False),
        sleep=sleep,
        rand=lambda: 0.0,
    )
    return client, calls
