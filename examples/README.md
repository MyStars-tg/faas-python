# Python examples

Runnable examples for [`mystars-faas`](../). Each file is self-contained.

| File | What it shows | Moves funds? |
|---|---|---|
| [`quickstart.py`](quickstart.py) | quote → check recipient → create order → **non-custodial** payment request → track | No (prints a payment request) |
| [`webhook_server.py`](webhook_server.py) | verify `X-Faas-Signature` over the raw body + dedup on `order_id` (stdlib `http.server`) | No |

> Paying an order programmatically (a self-custody payer) is on the Python roadmap — for now
> sign the `build_payment_request(...)` output with your own wallet or TON Connect.

## Run

Get an API key in [@my_stars_tg_bot](https://telegram.me/my_stars_tg_bot) → **API access**, then:

```bash
pip install mystars-faas
MYSTARS_API_KEY=faas_… python quickstart.py
```

`webhook_server.py` needs `MYSTARS_WEBHOOK_SECRET`.

> These examples are byte-compiled in CI (`python -m py_compile examples/*.py`) and linted
> with the package, so they never drift from the real API.
