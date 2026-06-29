"""Quickstart - quote -> check recipient -> create order -> non-custodial payment request.

No funds move here: this only PRINTS a payment request that you (or your end-user's wallet)
pay from your own wallet.

Run:
    MYSTARS_API_KEY=faas_... python examples/quickstart.py
"""

import os

from mystars_faas import MyStarsClient, build_payment_request


def main() -> None:
    api_key = os.environ.get("MYSTARS_API_KEY")
    if not api_key:
        raise SystemExit("set MYSTARS_API_KEY - get one in @my_stars_tg_bot -> API access")

    # The context manager closes the underlying httpx connection pool on exit.
    with MyStarsClient.production(api_key) as client:
        # 1) Quote the all-in price (100 Stars for @durov, paid in TON).
        quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
        print("price:", quote.amount, quote.currency)

        # 2) (optional) Confirm the recipient resolves and can receive the item.
        check = client.check_recipient("durov", type="stars")
        if not check.eligible:
            raise SystemExit(check.telegram_message or "recipient ineligible")

        # 3) Create the order. A STABLE idempotency key (derived from your own order id) makes
        #    a retry return the SAME order instead of creating a duplicate.
        my_order_id = os.environ.get("MY_ORDER_ID") or "demo-0001"
        order = client.create_order(
            type="stars",
            recipient="durov",
            quantity=100,
            payment_currency="ton",
            idempotency_key=f"quickstart-{my_order_id}",
        )

        # 4) Turn the order's payment block into something a wallet can pay (NON-CUSTODIAL -
        #    no keys involved; you/your user sign in your own wallet).
        req = build_payment_request(order.payment)
        print("order:", order.order_id)
        print("pay from your own wallet:", req.ton_deeplink)

        # 5) Track the order to a terminal state (delivered / failed / reversed / expired).
        final = client.wait_for_order(order.order_id, on_update=lambda o: print("status:", o.status))
        print("done:", final.status, final.purchase_tx or "")


if __name__ == "__main__":
    main()
