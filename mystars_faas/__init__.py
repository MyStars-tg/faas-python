"""mystars-faas — official Python SDK for the MyStars FaaS API.

Buy Telegram Stars & Premium for any @username, paid in GRAM or USDT (TON).
``payment_currency`` is required on every pricing and order call: ``ton`` is the native GRAM coin
(not USDT); ``usdt_ton`` is USDT.

    from mystars_faas import MyStarsClient

    client = MyStarsClient.production(os.environ["MYSTARS_API_KEY"])
    quote = client.get_pricing(type="stars", quantity=100, payment_currency="ton")
    order = client.create_order(type="stars", recipient="durov", quantity=100, payment_currency="ton")
    final = client.wait_for_order(order.order_id)

Partner products (contract 2.1.0, enabled per tenant on request): ``client.campaigns``,
``client.gifts`` and ``client.giveaways`` (with ``.channels`` and ``.series``); tenant event
webhooks are verified with :meth:`WebhookVerifier.verify_tenant_event` (``X-Faas-Signature-V2``).
"""

from __future__ import annotations

from ._partner import (
    ATTESTATION_BATCH_MAX,
    GIVEAWAY_DURATION_MIN_SEC,
    MAX_RECIPIENTS_PER_REQUEST,
    RESERVED_SERIES_KEY_PREFIX,
)
from ._transport import PRODUCTION_BASE_URL, RetryPolicy
from ._validate import (
    PAYMENT_CURRENCIES,
    PREMIUM_MONTHS,
    STARS_MAX_QUANTITY,
    STARS_MIN_QUANTITY,
    PaymentCurrency,
    canonical_username,
)
from ._version import CONTRACT_VERSION, __version__
from .async_client import AsyncMyStarsClient
from .client import MyStarsClient
from .errors import (
    FEATURE_UNAVAILABLE_CODES,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    FeatureUnavailableError,
    ForbiddenError,
    IdempotencyConflictError,
    IdempotencyInFlightError,
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
    UnprocessableError,
    WebhookVerificationError,
)
from .markup import RetailQuote, apply_retail_markup, ceil_ton_to_4dp, ceil_usd_to_cents
from .models import (
    CANCELLABLE_STATUSES,
    INITIAL_STATUS,
    ORDER_STATUSES,
    TENANT_EVENT_TYPES,
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
    TenantEvent,
    WebhookEvent,
    is_terminal,
)
from .partner_types import TERMINAL_CAMPAIGN_STATUSES
from .payment import (
    FundingPaymentRequest,
    PaymentRequest,
    TonConnectMessage,
    build_comment_payload,
    build_funding_payment_request,
    build_jetton_transfer_payload,
    build_payment_request,
    build_ton_connect_messages,
    build_ton_deeplink,
    parse_ton_address,
    payment_comment,
    to_micro,
    to_nano,
    verify_funding_payment,
)
from .reconcile import reconcile
from .webhook import (
    SIGNATURE_V2_TOLERANCE_SEC,
    WebhookVerifier,
    verify_webhook_signature,
    verify_webhook_signature_v2,
)

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
    "IdempotencyInFlightError",
    "OrderNotCancellableError",
    "RecipientIneligibleError",
    "UnprocessableError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "FeatureUnavailableError",
    "FEATURE_UNAVAILABLE_CODES",
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
    "TenantEvent",
    "TENANT_EVENT_TYPES",
    "TERMINAL_CAMPAIGN_STATUSES",
    "TERMINAL_STATUSES",
    "WEBHOOK_TERMINAL_STATUSES",
    "CANCELLABLE_STATUSES",
    "INITIAL_STATUS",
    "ORDER_STATUSES",
    "is_terminal",
    # webhook / markup / payment / validation
    "WebhookVerifier",
    "verify_webhook_signature",
    "verify_webhook_signature_v2",
    "SIGNATURE_V2_TOLERANCE_SEC",
    "apply_retail_markup",
    "ceil_usd_to_cents",
    "ceil_ton_to_4dp",
    "RetailQuote",
    "build_payment_request",
    "build_funding_payment_request",
    "verify_funding_payment",
    "payment_comment",
    "FundingPaymentRequest",
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
    "PAYMENT_CURRENCIES",
    "PaymentCurrency",
    # partner products (contract 2.1.0)
    "MAX_RECIPIENTS_PER_REQUEST",
    "ATTESTATION_BATCH_MAX",
    "GIVEAWAY_DURATION_MIN_SEC",
    "RESERVED_SERIES_KEY_PREFIX",
]
