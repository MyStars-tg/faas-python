"""Asyncio partner resources (contract 2.1.0): ``client.campaigns``, ``client.gifts``, ``client.giveaways``.

The awaitable twins of :mod:`mystars_faas.resources` — same methods, same validation, same
requests (both build them through ``mystars_faas._partner``).

Campaigns and giveaways are enabled per tenant on request (a tenant without access gets
:class:`~mystars_faas.PermissionDeniedError`). Every giveaway ``POST`` — and a campaign create or
recipient append — sends an ``Idempotency-Key``: pass a stable ``idempotency_key`` derived from your
own record, or one is minted per call and reused across that call's retries.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any, Callable, cast

from . import _partner as P
from ._transport import _Request
from .partner_types import (
    Campaign,
    CampaignConfirmation,
    CampaignDetail,
    CampaignRecipient,
    CampaignRecipientsAppended,
    CampaignRecipientsPage,
    CampaignRevalidation,
    CampaignsPage,
    CampaignStats,
    Capacity,
    CreatedCampaign,
    GiftCatalog,
    Giveaway,
    GiveawayAttestation,
    GiveawayAttestationResult,
    GiveawayAttestationsPage,
    GiveawayAutopost,
    GiveawayChannelList,
    GiveawayChannelWithChecks,
    GiveawayClosed,
    GiveawayEntrantsPage,
    GiveawayFunding,
    GiveawayQuote,
    GiveawayResults,
    GiveawaySeries,
    GiveawaySeriesPage,
    GiveawaysPage,
    GiveawayStats,
    GiveawayStatusChange,
)

Send = Callable[[_Request], "Awaitable[tuple[Any, int, Mapping[str, str]]]"]


class _Base:
    def __init__(self, send: Send, new_key: Callable[[], str]) -> None:
        self._send = send
        self._new_key = new_key

    async def _data(self, req: _Request) -> Any:
        return (await self._send(req))[0]

    def _key(self, key: str | None) -> str:
        return key or self._new_key()

    async def _pages(self, fetch: Callable[[str | None], Awaitable[Any]], items: str, cursor: str | None = None) -> AsyncIterator[Any]:
        while True:
            page = await fetch(cursor)
            for item in page[items]:
                yield item
            cursor = page.get("next_cursor")
            if not cursor:
                return


class AsyncCampaigns(_Base):
    """Outreach campaigns: one product to a list of usernames, ONE payment, one reversal of what was not delivered."""

    async def create(
        self,
        *,
        product: str,
        payment_currency: str,
        recipients: Sequence[str],
        quantity: int | None = None,
        months: int | None = None,
        gift_id: str | None = None,
        comment: str | None = None,
        hide_name: bool | None = None,
        idempotency_key: str | None = None,
    ) -> CreatedCampaign:
        """Create a draft (``POST /v1/campaigns``) and start validating up to 5,000 recipients.

        Recipients are sent as given — the server stores malformed or repeated entries as rejected
        rows so the counts add up. Returns the campaign, the request's ``batch`` and ``replayed``.

        Raises:
            MyStarsValidationError: On bad input, before any request.
            PermissionDeniedError: 403 — campaigns are not enabled for your tenant.
            UnprocessableError: 422 ``product_not_available`` / ``currency_not_available``.
            IdempotencyConflictError: 409 — the key was used with a different body.
        """
        req = P.campaign_create(
            product=product, payment_currency=payment_currency, recipients=recipients, quantity=quantity, months=months,
            gift_id=gift_id, comment=comment, hide_name=hide_name, key=self._key(idempotency_key),
        )
        return cast(CreatedCampaign, P.with_replayed(*(await self._send(req))))

    async def add_recipients(self, campaign_id: str, recipients: Sequence[str], *, idempotency_key: str | None = None) -> CampaignRecipientsAppended:
        """Append up to 5,000 usernames to a draft (``POST /v1/campaigns/{id}/recipients``); one key per chunk."""
        req = P.campaign_add_recipients(campaign_id, recipients, self._key(idempotency_key))
        return cast(CampaignRecipientsAppended, P.with_replayed(*(await self._send(req))))

    async def validate(self, campaign_id: str) -> CampaignRevalidation:
        """Re-check unverified, stale and state-dependent rows of a draft (``POST …/validate``)."""
        return cast(CampaignRevalidation, await self._data(P.campaign_action(campaign_id, "validate")))

    async def confirm(self, campaign_id: str) -> CampaignConfirmation:
        """Lock the list and the price (``POST …/confirm``): pay ``amount`` of ``currency`` to ``pay_to`` with ``memo``."""
        return cast(CampaignConfirmation, await self._data(P.campaign_action(campaign_id, "confirm")))

    async def cancel(self, campaign_id: str) -> Campaign:
        """``cancelled`` before payment; ``cancelling`` after (settles with a reversal of the undelivered value)."""
        return cast(Campaign, await self._data(P.campaign_action(campaign_id, "cancel")))

    async def pause(self, campaign_id: str) -> Campaign:
        """Stop starting new deliveries (``POST …/pause``)."""
        return cast(Campaign, await self._data(P.campaign_action(campaign_id, "pause")))

    async def resume(self, campaign_id: str) -> Campaign:
        """``paused`` → ``running`` (``POST …/resume``). Not retried automatically."""
        return cast(Campaign, await self._data(P.campaign_action(campaign_id, "resume")))

    async def get(self, campaign_id: str) -> CampaignDetail:
        """One campaign with its verdict counts (``GET /v1/campaigns/{id}``)."""
        return cast(CampaignDetail, await self._data(P.campaign_get(campaign_id)))

    async def list(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> CampaignsPage:
        """One page of your campaigns, newest first (``GET /v1/campaigns``)."""
        return cast(CampaignsPage, await self._data(P.campaigns_list(status, limit, cursor)))

    def iter_all(self, *, status: str | None = None, page_size: int | None = None) -> AsyncIterator[Campaign]:
        """Every campaign across all pages."""
        return self._pages(lambda c: self.list(status=status, limit=page_size, cursor=c), "campaigns")

    async def recipients(
        self,
        campaign_id: str,
        *,
        verdict: str | None = None,
        status: str | None = None,
        reason: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> CampaignRecipientsPage:
        """One page of a campaign's rows in submission order (``GET …/recipients``)."""
        return cast(CampaignRecipientsPage, await self._data(P.campaign_recipients(campaign_id, verdict, status, reason, limit, cursor)))

    def iter_recipients(
        self, campaign_id: str, *, verdict: str | None = None, status: str | None = None, reason: str | None = None, page_size: int | None = None
    ) -> AsyncIterator[CampaignRecipient]:
        """Every row of a campaign across all pages."""
        return self._pages(
            lambda c: self.recipients(campaign_id, verdict=verdict, status=status, reason=reason, limit=page_size, cursor=c), "recipients"
        )

    async def stats(self, campaign_id: str) -> CampaignStats:
        """Counts by verdict / status / reason, amounts and an ETA (``GET …/stats``)."""
        return cast(CampaignStats, await self._data(P.campaign_get(campaign_id, "/stats")))

    async def capacity(self, *, type: str, recipients: int | None = None) -> Capacity:
        """How fast a campaign of ``recipients`` would be delivered right now (``GET /v1/capacity``)."""
        return cast(Capacity, await self._data(P.capacity(type, recipients)))


class AsyncGifts(_Base):
    """The star gifts a ``star_gift`` campaign can send."""

    async def list(self, *, currency: str) -> GiftCatalog:
        """The sendable catalog with an INDICATIVE per-gift price (``GET /v1/gifts``).

        ``currency`` is required (``"ton"``, the native GRAM coin, or ``"usdt_ton"``); a missing or
        unknown one raises before any request.

        Raises:
            UnprocessableError: 422 ``currency_not_available`` — ``usdt_ton`` where USDT payments
                are not offered.
        """
        return cast(GiftCatalog, await self._data(P.gifts_list(currency)))


class AsyncGiveawayChannels(_Base):
    """Your registered giveaway chats."""

    async def list(self) -> GiveawayChannelList:
        """Your chats, the bot to add as an administrator, and the winner ceiling."""
        return cast(GiveawayChannelList, await self._data(_Request("GET", "/giveaways/channels")))

    async def register(self, chat: str, *, invite_link: str | None = None, idempotency_key: str | None = None) -> GiveawayChannelWithChecks:
        """Register a chat and get the live checks back."""
        return cast(GiveawayChannelWithChecks, await self._data(P.channels_register(chat, invite_link, self._key(idempotency_key))))

    async def check(self, channel_id: str, *, idempotency_key: str | None = None) -> GiveawayChannelWithChecks:
        """Run the chat checks again."""
        req = P.keyed_post(f"/giveaways/channels/{P.seg(channel_id)}/check", self._key(idempotency_key))
        return cast(GiveawayChannelWithChecks, await self._data(req))

    async def remove(self, channel_id: str) -> None:
        """Take a chat off your list."""
        await self._send(P.delete(f"/giveaways/channels/{P.seg(channel_id)}"))


class AsyncGiveawaySeriesResource(_Base):
    """Recurring giveaways — each occurrence is an ordinary giveaway, funded on its own."""

    async def create(
        self,
        *,
        template: Mapping[str, Any],
        interval: str,
        starts_at: str,
        every: int | None = None,
        count: int | None = None,
        until: str | None = None,
        currency: str | None = None,
        on_unfunded: str | None = None,
        idempotency_key: str | None = None,
    ) -> GiveawaySeries:
        """Schedule a giveaway every ``every`` × ``interval`` from ``starts_at`` — give exactly one of ``count`` / ``until``."""
        req = P.series_create(
            template=template, interval=interval, starts_at=starts_at, every=every, count=count, until=until,
            currency=currency, on_unfunded=on_unfunded, key=self._key(idempotency_key),
        )
        return cast(GiveawaySeries, P.with_replayed(*(await self._send(req))))

    async def list(self, *, status: str | None = None, limit: int | None = None, cursor: str | None = None) -> GiveawaySeriesPage:
        """One page of your series."""
        return cast(GiveawaySeriesPage, await self._data(P.series_list(status, limit, cursor)))

    def iter_all(self, *, status: str | None = None, page_size: int | None = None) -> AsyncIterator[GiveawaySeries]:
        """Every series across all pages."""
        return self._pages(lambda c: self.list(status=status, limit=page_size, cursor=c), "series")

    async def get(self, series_id: str) -> GiveawaySeries:
        """One series."""
        return cast(GiveawaySeries, await self._data(_Request("GET", f"/giveaways/series/{P.seg(series_id)}")))

    async def pause(self, series_id: str, *, idempotency_key: str | None = None) -> GiveawaySeries:
        """Stop spawning until resumed."""
        return cast(GiveawaySeries, await self._data(P.keyed_post(f"/giveaways/series/{P.seg(series_id)}/pause", self._key(idempotency_key))))

    async def resume(self, series_id: str, *, idempotency_key: str | None = None) -> GiveawaySeries:
        """Re-check the chat, then spawn from the next slot not yet passed."""
        return cast(GiveawaySeries, await self._data(P.keyed_post(f"/giveaways/series/{P.seg(series_id)}/resume", self._key(idempotency_key))))

    async def cancel(self, series_id: str, *, idempotency_key: str | None = None) -> GiveawaySeries:
        """Stop future occurrences (existing ones run on)."""
        return cast(GiveawaySeries, await self._data(P.keyed_post(f"/giveaways/series/{P.seg(series_id)}/cancel", self._key(idempotency_key))))


class AsyncGiveaways(_Base):
    """Provably-fair partner giveaways in your Telegram chats."""

    def __init__(self, send: Send, new_key: Callable[[], str]) -> None:
        super().__init__(send, new_key)
        #: Your registered chats.
        self.channels = AsyncGiveawayChannels(send, new_key)
        #: Recurring series.
        self.series = AsyncGiveawaySeriesResource(send, new_key)

    async def quote(
        self, *, prize_type: str, prize_quantity_per_winner: int, winner_count: int, currency: str | None = None, gift_id: str | None = None
    ) -> GiveawayQuote:
        """The funding price at your wholesale terms (``GET /v1/giveaways/quote``)."""
        return cast(GiveawayQuote, await self._data(P.giveaway_quote(prize_type, prize_quantity_per_winner, winner_count, currency, gift_id)))

    async def create(
        self,
        *,
        channel_id: str,
        prize_type: str,
        prize_quantity_per_winner: int,
        winner_count: int,
        duration_sec: int,
        title: str | None = None,
        conditions: Sequence[Mapping[str, Any]] | None = None,
        antibot: Mapping[str, Any] | None = None,
        external_ref: str | None = None,
        listed: bool | None = None,
        entries_events: bool | None = None,
        gift: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Giveaway:
        """Create a classic giveaway as a draft (``POST /v1/giveaways``); ``replayed`` on an earlier key."""
        template = {
            "channel_id": channel_id, "title": title, "prize_type": prize_type, "prize_quantity_per_winner": prize_quantity_per_winner,
            "winner_count": winner_count, "duration_sec": duration_sec,
            "conditions": None if conditions is None else [dict(c) for c in conditions],
            "antibot": None if antibot is None else dict(antibot), "external_ref": external_ref, "listed": listed,
            "entries_events": entries_events, "gift": None if gift is None else dict(gift),
        }
        req = P.giveaway_create(template, self._key(idempotency_key))
        return cast(Giveaway, P.with_replayed(*(await self._send(req))))

    async def list(
        self, *, status: str | None = None, series_id: str | None = None, limit: int | None = None, cursor: str | None = None
    ) -> GiveawaysPage:
        """One page of your giveaways, newest first; ``series_id`` lists one series' occurrences."""
        return cast(GiveawaysPage, await self._data(P.giveaways_list(status, series_id, limit, cursor)))

    def iter_all(self, *, status: str | None = None, series_id: str | None = None, page_size: int | None = None) -> AsyncIterator[Giveaway]:
        """Every giveaway across all pages."""
        return self._pages(lambda c: self.list(status=status, series_id=series_id, limit=page_size, cursor=c), "giveaways")

    async def get(self, giveaway_id: str) -> Giveaway:
        """One giveaway with entry counts, escrow, funding and the frozen conditions."""
        return cast(Giveaway, await self._data(_Request("GET", f"/giveaways/{P.seg(giveaway_id)}")))

    async def fund(self, giveaway_id: str, *, currency: str | None = None, idempotency_key: str | None = None) -> GiveawayFunding:
        """Open the funding order (201) or serve the open one again (200). Pays the giveaway's own
        one-time deposit address (``memo`` ``None``, no comment) — see
        :func:`~mystars_faas.build_funding_payment_request`.

        A new key does not get a new instruction: while an order is open, a call in that order's
        currency serves it again with the same ``expires_at``; a call in the other currency (no
        ``currency`` means ``ton``) is refused with 409 ``funding_order_open_in_other_currency``,
        whose ``details["currency"]`` names the open order's currency (call again with it; the
        refused call kept no answer, so its key may be reused).
        An expired instruction cannot be paid or replaced: the call answers 409
        ``funding_order_not_payable``, then 409 ``not_fundable`` once the giveaway is cancelled —
        create a new giveaway to try again. A retry with the same key returns the same answer;
        each call mints a new key unless you pass one."""
        return cast(GiveawayFunding, await self._data(P.giveaway_fund(giveaway_id, currency, self._key(idempotency_key))))

    async def cancel(self, giveaway_id: str, *, idempotency_key: str | None = None) -> GiveawayStatusChange:
        """Cancel a ``draft`` or ``awaiting_funding`` giveaway."""
        return cast(GiveawayStatusChange, await self._data(P.keyed_post(f"/giveaways/{P.seg(giveaway_id)}/cancel", self._key(idempotency_key))))

    async def close(self, giveaway_id: str, *, idempotency_key: str | None = None) -> GiveawayClosed:
        """Close an ``open`` giveaway now."""
        return cast(GiveawayClosed, await self._data(P.keyed_post(f"/giveaways/{P.seg(giveaway_id)}/close", self._key(idempotency_key))))

    async def enable_autopost(self, giveaway_id: str, *, channel_id: str | None = None, idempotency_key: str | None = None) -> GiveawayAutopost:
        """Let the bot post the giveaway (and its follow-ups)."""
        body = {} if channel_id is None else {"channel_id": channel_id}
        return cast(GiveawayAutopost, await self._data(P.keyed_post(f"/giveaways/{P.seg(giveaway_id)}/autopost", self._key(idempotency_key), body)))

    async def disable_autopost(self, giveaway_id: str) -> GiveawayAutopost:
        """Stop the bot's posts."""
        return cast(GiveawayAutopost, await self._data(P.delete(f"/giveaways/{P.seg(giveaway_id)}/autopost")))

    async def entrants(
        self,
        giveaway_id: str,
        *,
        status: str | None = None,
        filter_reason: str | None = None,
        condition_status: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> GiveawayEntrantsPage:
        """One page of entrants with scores, conditions and gift acceptance."""
        req = P.giveaway_entrants(giveaway_id, status, filter_reason, condition_status, limit, cursor)
        return cast(GiveawayEntrantsPage, await self._data(req))

    def iter_entrants(
        self,
        giveaway_id: str,
        *,
        status: str | None = None,
        filter_reason: str | None = None,
        condition_status: str | None = None,
        page_size: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Every entrant across all pages."""
        return self._pages(
            lambda c: self.entrants(
                giveaway_id, status=status, filter_reason=filter_reason, condition_status=condition_status, limit=page_size, cursor=c
            ),
            "entrants",
        )

    async def results(self, giveaway_id: str) -> GiveawayResults:
        """Draw data, winners and deliveries, unused slots, reversals."""
        return cast(GiveawayResults, await self._data(_Request("GET", f"/giveaways/{P.seg(giveaway_id)}/results")))

    async def stats(self, giveaway_id: str) -> GiveawayStats:
        """The funnel."""
        return cast(GiveawayStats, await self._data(_Request("GET", f"/giveaways/{P.seg(giveaway_id)}/stats")))

    async def attest(
        self,
        giveaway_id: str,
        *,
        condition_key: str,
        telegram_user_ids: Sequence[int | str],
        satisfied: bool,
        idempotency_key: str | None = None,
    ) -> GiveawayAttestationResult:
        """Assert (or, ``satisfied=False``, revoke) your own condition for up to 1,000 users — until the giveaway
        closes (409 ``attestations_frozen`` after).

        A batch that would take the condition past its cap of Telegram users is refused whole with 409
        ``attestation_limit_reached`` (``details["limit"]``); nothing is written. Every user the condition has
        asserted or revoked counts toward the cap (a revocation does not free a place); ids it already holds add
        nothing, so they can still be asserted or revoked at the cap."""
        req = P.giveaway_attest(giveaway_id, condition_key, telegram_user_ids, satisfied, self._key(idempotency_key))
        return cast(GiveawayAttestationResult, await self._data(req))

    async def attestations(
        self,
        giveaway_id: str,
        *,
        condition_key: str | None = None,
        satisfied: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> GiveawayAttestationsPage:
        """One page of the assertions as they stand. A cancelled giveaway's attestations are deleted 7 days
        after the cancellation by default; the page is empty after that."""
        return cast(GiveawayAttestationsPage, await self._data(P.giveaway_attestations(giveaway_id, condition_key, satisfied, limit, cursor)))

    def iter_attestations(
        self, giveaway_id: str, *, condition_key: str | None = None, satisfied: bool | None = None, page_size: int | None = None
    ) -> AsyncIterator[GiveawayAttestation]:
        """Every assertion across all pages."""
        return self._pages(
            lambda c: self.attestations(giveaway_id, condition_key=condition_key, satisfied=satisfied, limit=page_size, cursor=c),
            "attestations",
        )

