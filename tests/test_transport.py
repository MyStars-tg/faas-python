"""B2: a response body larger than the 4 MB ceiling is rejected, not buffered whole."""

from __future__ import annotations

import httpx
import pytest

from mystars_faas import AsyncMyStarsClient, MyStarsAPIError, MyStarsClient
from mystars_faas._transport import MAX_RESPONSE_BYTES, RetryPolicy

API_KEY = "faas_" + "c" * 64


def _oversized_transport() -> httpx.MockTransport:
    # A JSON-shaped body comfortably over the 4 MB ceiling.
    content = b'{"currencies":"' + b"a" * (MAX_RESPONSE_BYTES + 1024) + b'"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=content)

    return httpx.MockTransport(handler)


def _small_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b'{"currencies":[]}')

    return httpx.MockTransport(handler)


def test_response_size_cap_sync():
    client = MyStarsClient(API_KEY, transport=_oversized_transport(), retry=RetryPolicy(max_retries=0))
    with pytest.raises(MyStarsAPIError) as exc:
        client.list_currencies()
    assert exc.value.code == "response_too_large"


def test_normal_response_under_cap_sync():
    client = MyStarsClient(API_KEY, transport=_small_transport(), retry=RetryPolicy(max_retries=0))
    assert client.list_currencies() == []


@pytest.mark.asyncio
async def test_response_size_cap_async():
    async with AsyncMyStarsClient(API_KEY, transport=_oversized_transport(), retry=RetryPolicy(max_retries=0)) as client:
        with pytest.raises(MyStarsAPIError) as exc:
            await client.list_currencies()
    assert exc.value.code == "response_too_large"


@pytest.mark.asyncio
async def test_normal_response_under_cap_async():
    async with AsyncMyStarsClient(API_KEY, transport=_small_transport(), retry=RetryPolicy(max_retries=0)) as client:
        assert await client.list_currencies() == []
