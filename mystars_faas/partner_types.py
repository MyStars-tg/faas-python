"""Typed shapes of the partner products (contract 2.1.0): campaigns, gifts, giveaways, series.

The resources return the server's JSON as these ``TypedDict``s — plain ``dict`` objects at
runtime, field-for-field ``snake_case``, money as decimal STRINGS (convert with
``decimal.Decimal`` when you compute). Keys a newer server adds are kept. Campaigns and
giveaways are enabled per tenant on request.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, Union

CampaignProduct = Literal["stars", "premium", "star_gift"]
CampaignStatus = Literal[
    "draft", "awaiting_payment", "paid", "running", "paused", "cancelling", "settling",
    "awaiting_approval", "completed", "cancelled", "expired", "failed",
]
CampaignValidationVerdict = Literal["pending", "ok", "unverified", "rejected"]
CampaignDeliveryStatus = Literal["pending", "excluded", "queued", "delivered", "failed", "skipped"]
GiveawayStatus = Literal["draft", "awaiting_funding", "open", "closed", "drawn", "settling", "settled", "cancelled"]
GiveawayPrizeType = Literal["stars", "premium", "gift"]
GiveawaySeriesStatus = Literal["active", "paused", "cancelled", "completed"]

#: Statuses a campaign never leaves.
TERMINAL_CAMPAIGN_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "expired", "failed"})


class CampaignPaymentInstruction(TypedDict):
    """How to pay a confirmed campaign: one transfer, memo = the campaign id."""

    currency: str
    chain: str
    pay_to_address: str
    memo: str
    amount: str
    amount_smallest_unit: str
    asset: str
    decimals: int
    transfer: str
    jetton_master: str | None


class FundingPaymentInstruction(TypedDict):
    """How to fund a giveaway. ``memo`` is ``None`` and ``address_kind`` ``"one_time_deposit"``:
    send exactly ``amount_smallest_unit`` of ``asset`` to ``pay_to_address`` before ``expires_at``."""

    payment_id: str
    currency: str
    chain: str
    pay_to_address: str
    memo: str | None
    address_kind: str
    amount: str
    amount_smallest_unit: str
    asset: str
    decimals: int
    transfer: str
    jetton_master: str | None
    amount_usd: str
    expires_at: str


class CampaignRecipientBatch(TypedDict):
    submitted: int
    accepted: int
    rejected: int


class CampaignVerdictCounts(TypedDict):
    total: int
    pending: int
    ok: int
    unverified: int
    rejected: int


class Campaign(TypedDict):
    campaign_id: str
    status: str
    product: str
    quantity: int | None
    months: int | None
    gift: dict[str, Any] | None
    payment_currency: str
    recipient_count: int | None
    unit_price: str | None
    amount: str | None
    #: Present only while ``awaiting_payment`` in a currency that is offered: ``None`` for a
    #: ``usdt_ton`` campaign where USDT payments are not offered.
    payment: CampaignPaymentInstruction | None
    payment_tx: str | None
    received_amount: str | None
    max_deliverable: int | None
    failure_reason: str | None
    pause_reason: str | None
    reversal_due: str | None
    reversal_amount: str | None
    reversal_skip_reason: str | None
    #: The transaction hash of the reversal; ``None`` while none has gone out, or when it was
    #: confirmed without a reference that can be shown (contact support). Never a placeholder
    #: (contract v2.1.3).
    reversal_tx: str | None
    created_at: str
    updated_at: str
    confirmed_at: str | None
    expires_at: str | None
    paid_at: str | None
    finished_at: str | None


class CreatedCampaign(Campaign):
    batch: CampaignRecipientBatch
    #: ``True`` for an idempotent replay (HTTP 200).
    replayed: bool


class CampaignDetail(Campaign):
    recipients: CampaignVerdictCounts


class CampaignRevalidation(Campaign):
    requeued: int


class CampaignRecipientsAppended(TypedDict):
    campaign_id: str
    batch: CampaignRecipientBatch
    replayed: bool


class CampaignConfirmation(TypedDict):
    campaign_id: str
    status: str
    recipient_count: int
    unit_price: str
    amount: str
    currency: str
    pay_to: str
    memo: str
    expires_at: str
    payment: CampaignPaymentInstruction


class CampaignsPage(TypedDict):
    campaigns: list[Campaign]
    next_cursor: str | None


class CampaignRecipient(TypedDict):
    position: int
    username: str | None
    validation_verdict: str
    validation_reason: str | None
    validated_at: str | None
    delivery_status: str
    delivery_reason: str | None
    order_id: str | None
    delivered_at: str | None


class CampaignRecipientsPage(TypedDict):
    campaign_id: str
    recipients: list[CampaignRecipient]
    next_cursor: str | None


class CampaignStats(TypedDict):
    campaign_id: str
    status: str
    validation: dict[str, Any]
    delivery: dict[str, Any]
    amounts: dict[str, Any]
    eta_seconds: int | None
    gift: dict[str, Any] | None


class GiftPrice(TypedDict):
    amount: str
    amount_smallest_unit: str


class Gift(TypedDict):
    gift_id: str
    stars: str
    title: str | None
    emoji: str | None
    limited: bool
    availability_remains: int | None
    availability_total: int | None
    upgrade_stars: str | None
    thumb: str | None
    #: Indicative per-gift price in the catalog currency; the binding price is locked at confirm.
    price: GiftPrice


class GiftCatalog(TypedDict):
    currency: str
    comment_max_length: int
    catalog_refreshed_at: str | None
    gifts: list[Gift]


class GiveawayChannelChecks(TypedDict):
    bot_is_admin: bool
    bot_can_post: bool
    owner_is_admin: bool


class GiveawayChannel(TypedDict):
    id: str
    chat_id: str
    username: str | None
    title: str | None
    chat_type: str | None
    bot_is_admin: bool
    bot_can_post: bool
    owner_verified: bool
    invite_link: str | None
    checked_at: str | None


class GiveawayChannelList(TypedDict):
    channels: list[GiveawayChannel]
    bot_username: str | None
    max_winners: int


class GiveawayChannelWithChecks(TypedDict):
    channel: GiveawayChannel
    checks: GiveawayChannelChecks


class GiveawayQuote(TypedDict):
    prize_type: str
    prize_quantity_per_winner: int
    winner_count: int
    slots: int
    currency: str
    amount: str
    amount_usd: str


class Giveaway(TypedDict, total=False):
    id: str
    public_id: str
    status: str
    external_ref: str | None
    listed: bool
    entries_events: bool
    title: str | None
    prize_type: str
    prize_quantity_per_winner: int
    winner_count: int
    channel_id: str | None
    series_id: str | None
    series_index: int | None
    duration_sec: int | None
    created_at: str | None
    opens_at: str | None
    closes_at: str | None
    closed_at: str | None
    commit_hash: str | None
    entry_url: str | None
    proof_url: str
    conditions_format: str
    antibot: dict[str, Any]
    #: :meth:`get` only — the frozen conditions, entry counts, escrow and funding.
    conditions: list[dict[str, Any]]
    entries: dict[str, int]
    escrow: dict[str, Any] | None
    #: ``status`` and ``tx_hash`` — the payment's on-chain transaction hash as 64 hex characters or
    #: the 44-character base64 form, to look up in a TON explorer as given; ``None`` until it is seen.
    funding: dict[str, Any] | None
    #: :meth:`create` only — ``True`` when the server answered from an earlier request with the key.
    replayed: bool


class GiveawaysPage(TypedDict):
    giveaways: list[Giveaway]
    next_cursor: str | None


class GiveawayFunding(TypedDict):
    giveaway_id: str
    status: str
    payment: FundingPaymentInstruction


class GiveawayStatusChange(TypedDict):
    giveaway_id: str
    status: str


class GiveawayClosed(GiveawayStatusChange):
    """``POST /v1/giveaways/{id}/close``."""

    #: When the giveaway closed: the same value as ``closed_at`` in ``GET /v1/giveaways/{id}``.
    closed_at: str | None


class GiveawayAutopost(TypedDict, total=False):
    giveaway_id: str
    status: str
    checks: GiveawayChannelChecks
    posts: list[dict[str, Any]]


class GiveawayEntrantsPage(TypedDict):
    giveaway_id: str
    #: Each entrant's ``score`` (0-1, the sum of every signal's weight, clamped) and
    #: ``score_reasons``: the signals that RAISED it, plus ``premium_required`` (weight ``0``).
    #: Signals that lower it (Telegram Premium, an earlier purchase) count but are not listed,
    #: so the listed weights need not add up to ``score``. Each ``seq`` is the entry's ID: one
    #: sequence shared by every giveaway on the platform, so it orders entries but is neither a
    #: count nor a position in this giveaway (the same value as on the proof page and in webhooks).
    entrants: list[dict[str, Any]]
    next_cursor: str | None


class GiveawayResults(TypedDict):
    giveaway_id: str
    status: str
    proof_url: str
    commit_hash: str | None
    conditions_hash: str | None
    conditions_format: str
    antibot: dict[str, Any]
    draw: dict[str, Any] | None
    #: Each winner's ``seq`` is its entry's ID (see :class:`GiveawayEntrantsPage`).
    winners: list[dict[str, Any]]
    slots: dict[str, int] | None
    reversals: list[dict[str, Any]]


class GiveawayStats(TypedDict):
    giveaway_id: str
    status: str
    funnel: dict[str, Any]
    recheck_coverage: dict[str, int] | None
    antibot: dict[str, Any]
    attestations: list[dict[str, Any]]


class GiveawayAttestationResult(TypedDict):
    giveaway_id: str
    condition_key: str
    satisfied: bool
    received: int
    changed: int


class GiveawayAttestation(TypedDict):
    condition_key: str
    telegram_user_id: str
    satisfied: bool
    attested_at: str


class GiveawayAttestationsPage(TypedDict):
    giveaway_id: str
    attestations: list[GiveawayAttestation]
    next_cursor: str | None


class GiveawaySeries(TypedDict, total=False):
    id: str
    status: str
    paused_reason: str | None
    interval: str
    every: int
    starts_at: str
    count: int | None
    until: str | None
    last_index: int
    on_unfunded: str
    currency: str
    next_index: int | None
    next_occurrence_at: str | None
    occurrences_created: int
    consecutive_failures: int
    consecutive_misses: int
    template: dict[str, Any]
    created_at: str
    updated_at: str | None
    paused_at: str | None
    ended_at: str | None
    #: :meth:`cancel` only.
    existing_occurrences: str
    note: str
    #: :meth:`create` only.
    replayed: bool


class GiveawaySeriesPage(TypedDict):
    series: list[GiveawaySeries]
    next_cursor: str | None


#: A condition as you send it: a membership gate or an attestation you assert.
GiveawayCondition = dict[str, Any]
#: Delivery capacity (Stars / Premium or star-gift form).
Capacity = dict[str, Any]
#: Either a ``str`` or ``int`` Telegram user id.
TelegramUserId = Union[int, str]
