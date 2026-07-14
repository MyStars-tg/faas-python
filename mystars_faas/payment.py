"""Non-custodial invoice builder — dependency-free TON BoC builders.

Ports the TypeScript SDK's builders (themselves ports of the verified frontend)
to pure Python: TEP op-0 comment cell, TEP-74 jetton transfer, ``ton://`` deeplink,
and decimal→smallest-unit conversions. The cross-language ``deeplink-vectors.json``
fixture pins these byte-for-byte against the TS output.
"""

from __future__ import annotations

import base64
import re
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .errors import MyStarsValidationError
from .models import PaymentInstruction

JETTON_TRANSFER_OP = 0xF8A7EA5
FORWARD_TON_AMOUNT_NANO = 0
JETTON_TRANSFER_GAS_NANO = "50000000"  # 0.05 TON

# Same grammar as the TS SDK's DECIMAL_RE (`/^-?\d+(\.\d+)?$/`): plain decimal
# only — rejects scientific notation (`1e3`), a leading `+`, bare dots, and
# surrounding whitespace so the two SDKs accept/reject identical strings.
_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")


# ─── conversions ─────────────────────────────────────────────────────────────

def _to_units(amount: str | Decimal | int, decimals: int) -> int:
    # A ``Decimal``/``int`` is a trusted numeric value, so normalise it to plain
    # fixed-point first — ``str(Decimal('1E-9'))`` is ``"1E-9"`` (scientific notation),
    # which the strict grammar below would reject even though the value is valid.
    # ``format(d, 'f')`` renders it as ``"0.000000001"``; a non-finite ``Decimal``
    # (``NaN``/``Infinity``) renders to a token the regex still rejects. A *string*
    # input keeps the strict grammar unchanged — scientific-notation strings stay
    # rejected, preserving accept/reject parity with the TS SDK.
    s = format(amount, "f") if isinstance(amount, Decimal) else str(amount)
    if not _DECIMAL_RE.fullmatch(s):
        raise MyStarsValidationError(f'invalid decimal amount "{amount}"')
    d = Decimal(s)
    scaled = (d * (10 ** decimals)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(scaled)


def to_nano(amount: str | Decimal | int) -> int:
    """Convert a decimal TON amount to integer nanoTON (×1e9).

    Args:
        amount: A TON amount as a string, ``Decimal``, or int. For a **string** input,
            scientific notation, a leading ``+``, and whitespace are rejected (plain decimal
            only). A ``Decimal``/int is first normalised to fixed-point, so a ``Decimal`` in
            scientific notation such as ``Decimal('1E-9')`` is accepted.

    Returns:
        The amount in nanoTON (1 TON = 1,000,000,000 nanoTON).

    Raises:
        MyStarsValidationError: If ``amount`` is not a plain decimal string.
    """
    return _to_units(amount, 9)


def to_micro(amount: str | Decimal | int) -> int:
    """Convert a decimal USDT amount to integer micro-USDT (×1e6).

    Args:
        amount: A USDT amount as a string, ``Decimal``, or int. A **string** must be plain
            decimal (no scientific notation); a ``Decimal``/int is normalised to fixed-point
            first, so ``Decimal('1E-9')`` is accepted.

    Returns:
        The amount in micro-USDT (1 USDT = 1,000,000 micro-USDT).

    Raises:
        MyStarsValidationError: If ``amount`` is not a plain decimal string.
    """
    return _to_units(amount, 6)


# ─── CRC helpers ─────────────────────────────────────────────────────────────

def crc32c(data: bytes) -> int:
    """Compute the CRC-32C (Castagnoli) checksum used in the BoC trailer."""
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if crc & 1 else crc >> 1
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def crc16xmodem(data: bytes) -> int:
    """Compute the CRC-16/XMODEM checksum used to validate a friendly TON address."""
    crc = 0x0000
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


# ─── BitBuilder ──────────────────────────────────────────────────────────────

class BitBuilder:
    """A minimal big-endian bit accumulator for building a single TON cell's data.

    Supports the subset of TVM cell primitives the invoice builders need
    (``store_uint``, ``store_coins`` var-uint, ``store_address``, ``store_string_tail``) and
    :meth:`finalize` returns ``(bytes, bit_count)`` for cell serialization.
    """

    def __init__(self) -> None:
        self._full: list[int] = []
        self._cur = 0
        self._pos = 0

    def store_uint(self, value: int, bits: int) -> BitBuilder:
        """Append ``value`` as a big-endian unsigned integer of ``bits`` bits. Returns ``self``."""
        v = int(value)
        for i in range(bits - 1, -1, -1):
            bit = (v >> i) & 1
            self._cur = ((self._cur << 1) | bit) & 0xFF
            self._pos += 1
            if self._pos == 8:
                self._full.append(self._cur)
                self._cur = 0
                self._pos = 0
        return self

    def store_bit(self, bit: int) -> BitBuilder:
        """Append a single bit (any truthy value stores 1). Returns ``self``."""
        return self.store_uint(1 if bit else 0, 1)

    def store_coins(self, amount: int) -> BitBuilder:
        """Append ``amount`` in the TVM variable-length coins encoding (4-bit byte-length prefix +
        big-endian bytes; ``0`` is a 4-bit zero). Returns ``self``."""
        if amount == 0:
            return self.store_uint(0, 4)
        hex_ = format(amount, "x")
        byte_len = (len(hex_) + 1) // 2
        self.store_uint(byte_len, 4)
        padded = hex_.zfill(byte_len * 2)
        for i in range(byte_len):
            self.store_uint(int(padded[i * 2 : i * 2 + 2], 16), 8)
        return self

    def store_address(self, address: str) -> BitBuilder:
        """Append a TON address as a standard ``MsgAddressInt`` (tag + workchain + 256-bit hash).
        Accepts any form :func:`parse_ton_address` parses. Returns ``self``."""
        workchain, hash_ = parse_ton_address(address)
        self.store_uint(0b10, 2)
        self.store_bit(0)
        self.store_uint(workchain + 256 if workchain < 0 else workchain, 8)
        for byte in hash_:
            self.store_uint(byte, 8)
        return self

    def store_string_tail(self, text: str) -> BitBuilder:
        """Append ``text`` as raw UTF-8 bytes (the cell's snake-data tail). Returns ``self``."""
        for byte in text.encode("utf-8"):
            self.store_uint(byte, 8)
        return self

    @property
    def total_bits(self) -> int:
        """The number of bits stored so far."""
        return len(self._full) * 8 + self._pos

    def finalize(self) -> tuple[bytes, int]:
        """Pack the accumulated bits into bytes.

        Returns:
            ``(data, bit_count)`` — the byte-padded data and the exact bit length, ready for
            cell serialization.
        """
        bits = self.total_bits
        byte_len = (bits + 7) // 8
        result = bytearray(byte_len)
        for i, b in enumerate(self._full):
            result[i] = b
        if self._pos > 0:
            result[len(self._full)] = (self._cur << (8 - self._pos)) & 0xFF
        return bytes(result), bits


# ─── address parsing ─────────────────────────────────────────────────────────

def parse_ton_address(address: str) -> tuple[int, bytes]:
    """Parse a friendly (base64url) or raw (``wc:hex``) TON address.

    Args:
        address: A friendly base64url address, or a raw ``<workchain>:<64-hex>`` address.

    Returns:
        A ``(workchain, 32-byte account hash)`` tuple.

    Raises:
        MyStarsValidationError: If the address is malformed (bad workchain, wrong length, bad
            hex, invalid base64, or a friendly-address checksum mismatch).
    """
    if ":" in address:
        wc_str, _, hash_hex = address.partition(":")
        if not _is_int(wc_str):
            raise MyStarsValidationError(f'invalid TON address: bad workchain "{wc_str}"')
        workchain = int(wc_str)
        if workchain not in (0, -1):
            raise MyStarsValidationError(f"invalid TON address: workchain must be 0 or -1, got {workchain}")
        if len(hash_hex) != 64 or not all(c in "0123456789abcdefABCDEF" for c in hash_hex):
            raise MyStarsValidationError("invalid TON address: hash must be 64 hex characters")
        return workchain, bytes.fromhex(hash_hex)

    standard = address.replace("-", "+").replace("_", "/")
    standard += "=" * (-len(standard) % 4)
    try:
        raw = base64.b64decode(standard)
    except Exception as exc:  # noqa: BLE001
        raise MyStarsValidationError("invalid TON address: not valid base64") from exc
    if len(raw) != 36:
        raise MyStarsValidationError(f"invalid TON address: expected 36 bytes, got {len(raw)}")
    payload = raw[:34]
    expected_crc = (raw[34] << 8) | raw[35]
    if expected_crc != crc16xmodem(payload):
        raise MyStarsValidationError("invalid TON address: checksum mismatch")
    workchain = raw[1] - 256 if raw[1] > 127 else raw[1]
    return workchain, raw[2:34]


def _is_int(s: str) -> bool:
    return bool(s) and (s.lstrip("-").isdigit())


# ─── cell + BoC serializer ───────────────────────────────────────────────────

def _serialize_cell(data: bytes, bits: int, ref_indices: list[int]) -> bytes:
    data_len = (bits + 7) // 8
    d1 = len(ref_indices)
    d2 = (bits // 8) * 2 if bits % 8 == 0 else (bits // 8) * 2 + 1
    cell_data = bytearray(data[:data_len])
    if bits % 8 != 0:
        remaining = bits % 8
        cell_data[data_len - 1] |= 1 << (8 - remaining - 1)
    return bytes([d1, d2]) + bytes(cell_data) + bytes(ref_indices)


def _serialize_boc(cells: list[bytes]) -> str:
    total = sum(len(c) for c in cells)
    offset_bytes = 1 if total < 256 else 2
    boc = bytearray(b"\xb5\xee\x9c\x72")
    boc.append((1 << 6) | 1)  # has_crc32c, ref_byte_size=1
    boc.append(offset_bytes)
    boc.append(len(cells))
    boc.append(1)  # roots
    boc.append(0)  # absent
    if offset_bytes == 2:
        boc.append((total >> 8) & 0xFF)
    boc.append(total & 0xFF)
    boc.append(0)  # root index
    for cell in cells:
        boc += cell
    crc = crc32c(bytes(boc))
    boc += bytes([crc & 0xFF, (crc >> 8) & 0xFF, (crc >> 16) & 0xFF, (crc >> 24) & 0xFF])
    return base64.b64encode(bytes(boc)).decode("ascii")


def _comment_cell(memo: str) -> bytes:
    data, bits = BitBuilder().store_uint(0, 32).store_string_tail(memo).finalize()
    return _serialize_cell(data, bits, [])


def build_comment_payload(comment: str) -> str:
    """Build the op-0 text-comment payload as a base64 BoC."""
    return _serialize_boc([_comment_cell(comment)])


def build_jetton_transfer_payload(amount_micro: str | int, destination: str, sender: str, memo: str) -> str:
    """Build the TEP-74 jetton transfer BoC payload (base64)."""
    ref = _comment_cell(memo)
    body = (
        BitBuilder()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(0, 64)
        .store_coins(int(amount_micro))
        .store_address(destination)
        .store_address(sender)
        .store_bit(0)
        .store_coins(FORWARD_TON_AMOUNT_NANO)
        .store_bit(1)
    )
    body_data, body_bits = body.finalize()
    serialized_body = _serialize_cell(body_data, body_bits, [1])
    return _serialize_boc([serialized_body, ref])


# ─── deeplink + payment request ───────────────────────────────────────────────

def build_ton_deeplink(payment: PaymentInstruction) -> str:
    """Build a ``ton://transfer/...`` deeplink for a TON payment instruction.

    Args:
        payment: A ``ton`` :class:`~mystars_faas.PaymentInstruction` (must have
            ``pay_to_address`` and ``memo``).

    Returns:
        A ``ton://transfer/<addr>?amount=<nano>&text=<memo>`` URI.

    Raises:
        MyStarsValidationError: If ``payment.currency`` is not ``ton`` (USDT needs a jetton
            transfer), or ``pay_to_address`` / ``memo`` is missing.
    """
    if payment.currency != "ton":
        raise MyStarsValidationError("a ton:// deeplink is only valid for `ton` payments (USDT needs a jetton transfer)")
    pay_to = _require(payment.pay_to_address, "pay_to_address")
    memo = _require(payment.memo, "memo")
    nano = to_nano(payment.amount)
    return f"ton://transfer/{pay_to}?amount={nano}&text={urllib.parse.quote(memo, safe='')}"


@dataclass
class TonConnectMessage:
    """One message of a TON Connect ``sendTransaction`` request.

    Attributes:
        address: The destination address (the pay-to address for TON; the payer's own jetton
            wallet for USDT).
        amount: The attached TON value in nanoTON, as a string.
        payload: The base64 BoC body (op-0 comment for TON; jetton-transfer body for USDT).
    """

    address: str
    amount: str
    payload: str | None = None


@dataclass
class PaymentRequest:
    """Wallet-ready ways to pay an order, built non-custodially from a payment instruction.

    Attributes:
        currency: ``"ton"`` or ``"usdt_ton"``.
        pay_to_address: The destination address.
        memo: The required transfer comment (the order id).
        amount_units: The display unit (``"ton"`` or ``"usdt"``).
        amount_smallest_unit: The amount in nanoTON / micro-USDT, as a string.
        ton_connect: TON Connect ``sendTransaction`` messages (empty for USDT until the payer's
            sender/jetton-wallet addresses are supplied).
        ton_deeplink: A ``ton://`` deeplink (TON only).
        tonkeeper_link: A Tonkeeper universal link (TON only).
        qr_payload: A string to render as a QR code (TON only).
        note: Guidance when a USDT request can't be fully built without the payer's wallet info.
    """

    currency: str
    pay_to_address: str
    memo: str
    amount_units: str
    amount_smallest_unit: str
    ton_connect: list[TonConnectMessage] = field(default_factory=list)
    ton_deeplink: str | None = None
    tonkeeper_link: str | None = None
    qr_payload: str | None = None
    note: str | None = None


def build_ton_connect_messages(
    payment: PaymentInstruction, *, sender_address: str | None = None, jetton_wallet_address: str | None = None
) -> list[TonConnectMessage]:
    """Build the TON Connect ``sendTransaction`` message list for a payment instruction.

    For ``ton`` this is one message to the pay-to address with an op-0 comment. For ``usdt_ton``
    it is one jetton-transfer message sent to the *payer's own* USDT jetton wallet, which
    requires both the payer's wallet addresses.

    Args:
        payment: The :class:`~mystars_faas.PaymentInstruction` to pay.
        sender_address: The payer's own wallet address (required for USDT).
        jetton_wallet_address: The payer's own USDT jetton-wallet address (required for USDT).

    Returns:
        A list of :class:`TonConnectMessage` to hand to a TON Connect wallet.

    Raises:
        MyStarsValidationError: If ``pay_to_address`` / ``memo`` is missing, or (for USDT) the
            payer's ``sender_address`` / ``jetton_wallet_address`` is not supplied.
    """
    pay_to = _require(payment.pay_to_address, "pay_to_address")
    memo = _require(payment.memo, "memo")
    if payment.currency == "ton":
        return [TonConnectMessage(address=pay_to, amount=str(to_nano(payment.amount)), payload=build_comment_payload(memo))]
    if not sender_address or not jetton_wallet_address:
        raise MyStarsValidationError(
            "a USDT TON Connect message needs sender_address + jetton_wallet_address (the payer's own USDT jetton wallet)"
        )
    payload = build_jetton_transfer_payload(to_micro(payment.amount), pay_to, sender_address, memo)
    return [TonConnectMessage(address=jetton_wallet_address, amount=JETTON_TRANSFER_GAS_NANO, payload=payload)]


def build_payment_request(
    payment: PaymentInstruction, *, sender_address: str | None = None, jetton_wallet_address: str | None = None
) -> PaymentRequest:
    """Build every wallet-ready way to pay an order from its payment instruction.

    For ``ton`` it fills in the deeplink, Tonkeeper link, QR payload, and TON Connect message.
    For ``usdt_ton`` it returns the amounts and a TON Connect message *iff* the payer's wallet
    addresses are supplied; otherwise it sets :attr:`PaymentRequest.note` explaining what's needed.
    Non-custodial: holds no keys, signs nothing.

    Args:
        payment: The :class:`~mystars_faas.PaymentInstruction` to pay.
        sender_address: The payer's own wallet address (USDT only).
        jetton_wallet_address: The payer's own USDT jetton-wallet address (USDT only).

    Returns:
        A :class:`PaymentRequest`.

    Raises:
        MyStarsValidationError: If ``pay_to_address`` / ``memo`` is missing, or an amount is not a
            valid decimal.
    """
    pay_to = _require(payment.pay_to_address, "pay_to_address")
    memo = _require(payment.memo, "memo")
    if payment.currency == "ton":
        nano = str(to_nano(payment.amount))
        deeplink = f"ton://transfer/{pay_to}?amount={nano}&text={urllib.parse.quote(memo, safe='')}"
        return PaymentRequest(
            currency="ton",
            pay_to_address=pay_to,
            memo=memo,
            amount_units="ton",
            amount_smallest_unit=nano,
            ton_deeplink=deeplink,
            tonkeeper_link=f"https://app.tonkeeper.com/transfer/{pay_to}?amount={nano}&text={urllib.parse.quote(memo, safe='')}",
            qr_payload=deeplink,
            ton_connect=[TonConnectMessage(address=pay_to, amount=nano, payload=build_comment_payload(memo))],
        )
    micro = str(to_micro(payment.amount))
    req = PaymentRequest(currency="usdt_ton", pay_to_address=pay_to, memo=memo, amount_units="usdt", amount_smallest_unit=micro)
    if sender_address and jetton_wallet_address:
        req.ton_connect = build_ton_connect_messages(payment, sender_address=sender_address, jetton_wallet_address=jetton_wallet_address)
    else:
        req.note = "USDT: pass sender_address + jetton_wallet_address (the payer's own USDT jetton wallet) to build a signable TON Connect message."
    return req


def _require(value: str | None, field_name: str) -> str:
    if not value:
        raise MyStarsValidationError(f"payment.{field_name} is missing")
    return value
