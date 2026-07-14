"""mystars-faas — official Python SDK for the MyStars FaaS API.

Buy Telegram Stars & Premium for any @username, paid in TON or USDT.

    from mystars_faas import MyStarsClient

    client = MyStarsClient.production(os.environ["MYSTARS_API_KEY"])
    quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
    order = client.create_order(type="stars", recipient="durov", quantity=100)
    final = client.wait_for_order(order.order_id)
"""

from __future__ import annotations

from ._transport import PRODUCTION_BASE_URL, RetryPolicy
from ._validate import (
    PREMIUM_MONTHS,
    STARS_MAX_QUANTITY,
    STARS_MIN_QUANTITY,
    canonical_username,
)
from ._version import CONTRACT_VERSION, __version__
from .async_client import AsyncMyStarsClient
from .client import MyStarsClient
from .errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    IdempotencyConflictError,
    InternalServerError,
    MyStarsAPIError,
    MyStarsError,
    MyStarsTransportError,
    MyStarsValidationError,
    NotFoundError,
    OrderNotCancellableError,
    OrderWaitTimeout,
    PermissionDeniedError,
    RateLimitedError,
    RecipientIneligibleError,
    ServiceUnavailableError,
    TimeoutError_,
    UnauthorizedError,
    WebhookVerificationError,
)
from .markup import RetailQuote, apply_retail_markup, ceil_ton_to_4dp, ceil_usd_to_cents
from .models import (
    CANCELLABLE_STATUSES,
    INITIAL_STATUS,
    ORDER_STATUSES,
    TERMINAL_STATUSES,
    WEBHOOK_TERMINAL_STATUSES,
    CreateOrderResult,
    CurrencyInfo,
    FeeBreakdown,
    Order,
    OrdersPage,
    PaymentInstruction,
    PricingBatchEntry,
    PricingQuote,
    PricingQuoteBatch,
    Product,
    RecipientCheck,
    WebhookEvent,
    is_terminal,
)
from .payment import (
    PaymentRequest,
    TonConnectMessage,
    build_comment_payload,
    build_jetton_transfer_payload,
    build_payment_request,
    build_ton_connect_messages,
    build_ton_deeplink,
    parse_ton_address,
    to_micro,
    to_nano,
)
from .reconcile import reconcile
from .webhook import WebhookVerifier, verify_webhook_signature

__all__ = [
    "__version__",
    "CONTRACT_VERSION",
    "MyStarsClient",
    "AsyncMyStarsClient",
    "RetryPolicy",
    "PRODUCTION_BASE_URL",
    # errors
    "MyStarsError",
    "MyStarsValidationError",
    "MyStarsTransportError",
    "TimeoutError_",
    "MyStarsAPIError",
    "BadRequestError",
    "AuthenticationError",
    "UnauthorizedError",
    "PermissionDeniedError",
    "ForbiddenError",
    "NotFoundError",
    "ConflictError",
    "IdempotencyConflictError",
    "OrderNotCancellableError",
    "RecipientIneligibleError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "InternalServerError",
    "WebhookVerificationError",
    "OrderWaitTimeout",
    # models
    "CurrencyInfo",
    "Product",
    "FeeBreakdown",
    "PricingBatchEntry",
    "PricingQuote",
    "PricingQuoteBatch",
    "RecipientCheck",
    "PaymentInstruction",
    "Order",
    "CreateOrderResult",
    "OrdersPage",
    "WebhookEvent",
    "TERMINAL_STATUSES",
    "WEBHOOK_TERMINAL_STATUSES",
    "CANCELLABLE_STATUSES",
    "INITIAL_STATUS",
    "ORDER_STATUSES",
    "is_terminal",
    # webhook / markup / payment / validation
    "WebhookVerifier",
    "verify_webhook_signature",
    "apply_retail_markup",
    "ceil_usd_to_cents",
    "ceil_ton_to_4dp",
    "RetailQuote",
    "build_payment_request",
    "build_ton_connect_messages",
    "build_ton_deeplink",
    "build_comment_payload",
    "build_jetton_transfer_payload",
    "parse_ton_address",
    "to_nano",
    "to_micro",
    "PaymentRequest",
    "TonConnectMessage",
    "reconcile",
    "canonical_username",
    "STARS_MIN_QUANTITY",
    "STARS_MAX_QUANTITY",
    "PREMIUM_MONTHS",
]
