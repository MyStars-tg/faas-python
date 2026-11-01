"""The payment token is "GRAM", never "TON", in every published string.

Everything scanned here is prose a consumer reads: ``README.md`` renders on PyPI,
``pyproject.toml``'s ``description`` is the one-liner under the package name, and
docstrings ship inside the wheel (``help()``, IDE hovers, generated API docs).
So a stale "paid in TON" is a customer-visible copy defect, not an internal note.

"TON" survives ONLY as a NETWORK / WALLET / PROTOCOL reference — the chain is still
The Open Network. Every bare "TON" must therefore be immediately qualified by a
network noun ("TON wallet", "TON Connect", "TON address", "TON cell", "TON BoC").
The regressions this locks out are the settlement-currency forms: "paid in TON or
USDT", "(TON only)", "0.05 TON", "a TON amount".

Deliberately NOT flagged:

* ``nanoTON`` — the protocol's own smallest-unit name. Renaming it would break the
  mental model against ``@ton/core`` / toncenter, so it stays everywhere.
* ``GRAM (ex TON)`` — the transitional disambiguator, and the notice sentence
  "**GRAM** is the coin formerly named TON". Writing EITHER is always legal, anywhere,
  any number of times: nothing here caps how often the ticker is explained. An earlier
  revision capped both at one per document and banned them from docstrings; that turned
  "explain the rename" into a build failure and left readers landing on a mid-page
  anchor with a bare, unexplained ticker. Those caps are deleted. What IS enforced is
  the opposite — the ordinal rule at the bottom: a README's FIRST mention must explain
  itself. Bare "GRAM" reads as an unknown
  new coin to a developer meeting it cold on the PyPI page, so the FIRST mention in each
  published document spells out where it came from. Allowed as an exact literal ONLY —
  "GRAM (formerly TON)" and every other paraphrase still fails, and the tests at the
  bottom cap it at one per document and keep it out of docstrings and examples.
* ``USDT (TON)`` — USDT *on the TON network*. NOT banned: USDT was never renamed, so the
  parenthetical says WHICH USDT, symmetric with ``USDT (ERC20)`` / ``USDT (TRC20)``.
* Every lowercase ``ton`` (the API currency codes ``ton`` / ``usdt_ton``, ``ton://``
  deeplinks, ``to_nano``, ``TonConnectMessage``). Those are wire identifiers, not
  prose, and case-sensitivity is what exempts them.

A parenthetical after ``GRAM`` NEVER states the chain: after that ticker it can only mean
the former name, so ``GRAM (TON)`` is BANNED — shipping it beside ``GRAM (ex TON)`` put two
parentheticals with opposite meanings 12 characters apart. Keeping that one literal OUT of
:data:`ALLOWED_LITERALS` is what enforces it: the scanner then sees a bare ``TON`` followed
by ``)`` and flags it like any other coin mention.

``USDT (TON)`` carries none of that ambiguity and is allowed. The published line is
"paid in **GRAM (ex TON)** or **USDT (TON)**." — two adjacent parentheticals with different
meanings, chosen deliberately.

Fenced code blocks are NOT exempt — only the CODE in them is. ``pyproject.toml`` sets
``readme = "README.md"``, so the quickstart fence renders verbatim on the public PyPI
page: a ``#`` comment inside it is customer-facing copy that merely happens to sit next
to code. :func:`fence_prose` keeps the comment text and drops the rest.
"""

from __future__ import annotations

import ast
import re
import tokenize
from pathlib import Path

import pytest

#: ``sdk/python`` — the subtree published to PyPI and mirrored to GitHub.
ROOT = Path(__file__).resolve().parents[1]

#: Widened past the frontend's ``marketingCopy.test.ts`` matcher because SDK prose
#: also names the chain's data structures (cells, BoC) and transports (RPC).
NETWORK_NOUN = re.compile(
    r"^(wallets?|signing|blockchains?|networks?|connect|chains?|address(es)?"
    r"|cells?|BoC|RPCs?|explorers?|jettons?|mainnet|testnet)$",
    re.IGNORECASE,
)

#: Literal sequences that carry a bare "TON" legitimately — removed before scanning.
ALLOWED_LITERALS = re.compile(r"GRAM \(ex TON\)|USDT \(TON\)|is the coin formerly named TON|nanoTON")

#: Markdown/RST decoration may sit between the ticker and its noun, but sentence
#: punctuation genuinely ends the qualification, so it is never skipped.
TON = re.compile(r"\bTON\b[\s`*_\"'’]*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)?")

FENCE = re.compile(r"^[ \t]*```[^\n]*\n.*?^[ \t]*```[^\n]*$", re.MULTILINE | re.DOTALL)

#: A ``#`` or ``//`` comment on a fenced line. ``[^:/]`` keeps ``https://`` out.
FENCE_COMMENT = re.compile(r"(?:^|[^:/])(?://|#)(.*)$")


def fence_prose(src: str) -> str:
    """Reduce each fenced block to the PROSE in it: comment text stays, code goes.

    Deleting fences wholesale would blind this guard to the copy PyPI renders most
    prominently — the quickstart snippet. The identifiers those snippets exist to show
    (``ton://``, ``ton_deeplink``, ``usdt_ton``) need no fence to protect them:
    :func:`coin_mentions` is case-sensitive, so lowercase ``ton`` can never match.
    """

    def keep_comments(match: re.Match[str]) -> str:
        lines = match.group(0).split("\n")[1:-1]  # drop the ``` markers themselves
        return "\n".join(
            (m.group(1) if (m := FENCE_COMMENT.search(line)) else "") for line in lines
        )

    return FENCE.sub(keep_comments, src)


def coin_mentions(text: str) -> list[str]:
    """Every "TON" not immediately qualified by a network noun, as readable snippets."""
    flat = ALLOWED_LITERALS.sub(" ", re.sub(r"\s+", " ", text))
    out = []
    for match in TON.finditer(flat):
        nxt = match.group(1) or ""
        if any(NETWORK_NOUN.match(seg) for seg in nxt.split("-")):
            continue
        start = max(0, match.start() - 45)
        out.append("..." + flat[start : match.start() + 55].strip() + "...")
    return out


def docstrings_and_comments(path: Path) -> str:
    """Every docstring (shipped in the wheel) plus every ``#`` note in a module."""
    src = path.read_text(encoding="utf-8")
    parts = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                parts.append(fence_prose(doc))
    with path.open(encoding="utf-8") as handle:
        for token in tokenize.generate_tokens(handle.readline):
            if token.type == tokenize.COMMENT:
                parts.append(token.string)
    return "\n".join(parts)


def _rel(paths: list[Path]) -> list[str]:
    return sorted(str(p.relative_to(ROOT)) for p in paths)


MARKDOWN = _rel([p for p in ROOT.rglob("*.md") if ".github" not in p.parts])
SOURCES = _rel(list((ROOT / "mystars_faas").rglob("*.py")))
EXAMPLES = _rel(list((ROOT / "examples").glob("*.py")))


def test_sweep_actually_covers_the_published_surface() -> None:
    """A broken glob would make every case below pass on an empty list."""
    assert "README.md" in MARKDOWN
    assert "SECURITY.md" in MARKDOWN
    assert "mystars_faas/markup.py" in SOURCES
    assert "mystars_faas/models.py" in SOURCES
    assert "mystars_faas/payment.py" in SOURCES
    assert "examples/quickstart.py" in EXAMPLES
    assert len(SOURCES) >= 12


@pytest.mark.parametrize("rel", MARKDOWN)
def test_markdown_names_the_token_gram(rel: str) -> None:
    assert coin_mentions(fence_prose((ROOT / rel).read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("rel", SOURCES)
def test_docstrings_name_the_token_gram(rel: str) -> None:
    assert coin_mentions(docstrings_and_comments(ROOT / rel)) == []


@pytest.mark.parametrize("rel", EXAMPLES)
def test_examples_name_the_token_gram(rel: str) -> None:
    assert coin_mentions((ROOT / rel).read_text(encoding="utf-8")) == []


def test_pyproject_description_names_the_token_gram() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^description = "(.*)"$', text, re.MULTILINE)
    assert match, "pyproject.toml lost its [project] description"
    assert coin_mentions(match.group(1)) == []


def test_reads_comment_prose_inside_a_fence_but_not_the_code() -> None:
    """The bug this guard shipped with: it deleted fenced blocks wholesale, so the
    coin mentions living in README quickstart COMMENTS — the copy PyPI renders most
    prominently — were structurally invisible to it, even while the byte-identical
    string sat in the ``bad`` list below."""
    snippet = "\n".join(
        [
            "```python",
            "print(req.ton_deeplink)        # ton://transfer/... (TON only)",
            "client.create_order(payment_currency='usdt_ton')  # ton and usdt_ton are wire codes",
            "```",
        ]
    )
    found = coin_mentions(fence_prose(snippet))
    assert len(found) == 1, found
    assert "TON only" in found[0]


def test_matcher_flags_the_coin_forms_and_passes_the_network_forms() -> None:
    """Non-vacuity: the matcher fires on what this rename removed, and only that."""
    for bad in [
        "paid in **TON** or **USDT (TON)**",
        "Ceil a TON amount to the 0.0001-GRAM grid",
        "ton_deeplink: A ``ton://`` deeplink (TON only).",
        "The attached TON value in nanoTON, as a string.",
        "JETTON_TRANSFER_GAS_NANO = '50000000'  # 0.05 TON",
        "usdt_per_ton: The TON→USDT rate used, when available",
        "fund this address with TON/USDT",
        # The allowance is a LITERAL, not a shape - every paraphrase still fails.
        # A parenthetical after GRAM never states the chain, so this one is banned.
        # (`USDT (TON)` is NOT banned - it is in the `good` list below.)
        "paid in GRAM (TON) or USDT, with the balance in nanoTON",
        "paid in GRAM (formerly TON) since the rename",
        "paid in GRAM (ex-TON) since the rename",
        "paid in Gram (ex TON) since the rename",
    ]:
        assert coin_mentions(bad) != [], bad
    for good in [
        "Parse a friendly (base64url) or raw (``wc:hex``) TON address.",
        "One message of a TON Connect ``sendTransaction`` request.",
        "Non-custodial invoice builder - dependency-free TON BoC builders.",
        "A minimal bit accumulator for building a single TON cell's data.",
        "generate or import a TON wallet (WalletContractV4)",
        "``to_nano``, ``ton://transfer``, ``usdt_ton``, ``amount_ton``",
        # Restored 2026-08-02: USDT was never renamed, so its parenthetical is a plain
        # chain marker, symmetric with ``USDT (ERC20)`` / ``USDT (TRC20)``.
        "paid in **GRAM (ex TON)** or **USDT (TON)**.",
        "paid in GRAM (ex TON) or USDT (TON), with the balance in nanoTON",
    ]:
        assert coin_mentions(good) == [], good


#: The transitional disambiguator, as a literal - the ONLY sanctioned spelling.
EX_TON = "GRAM (ex TON)"

#: A first mention that explains itself: inline, or via the top-of-file notice.
EXPLAINED_FIRST = re.compile(r"^GRAM \(ex TON\)|^GRAM\**\s+is the coin formerly named TON")


def first_coin_mention(text: str) -> tuple[bool, bool, str]:
    """Return ``(found, explained, snippet)`` for the FIRST ``GRAM`` in ``text``.

    Ordinal, not a count. "Once per document" is a BOOK convention: it assumes the
    reader started at page one. It does not survive a README reached by anchor, or a
    reference page where every heading is its own landing spot - an explanation 60% of
    the way down is invisible to everyone who arrived below it. So the requirement is
    position, never frequency.
    """
    match = re.search(r"\bGRAM\b", text)
    if not match:
        return False, True, ""
    tail = text[match.start() :]
    return True, bool(EXPLAINED_FIRST.match(tail)), tail[:90].split("\n")[0]


def test_the_coldest_reads_carry_the_disambiguator() -> None:
    """Bare "GRAM" on the PyPI page reads as an unknown new coin.

    ``pyproject.toml`` sets ``readme = "README.md"``, so the description line and the
    README's first line are exactly what a developer meets with no surrounding context.
    A rename that quietly drops the explanation from them is the regression.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^description = "(.*)"$', text, re.MULTILINE)
    assert match
    assert EX_TON in match.group(1)
    assert EX_TON in (ROOT / "README.md").read_text(encoding="utf-8")


def test_disambiguator_allowance_is_tight() -> None:
    """It strips one exact literal; it must not license any parenthetical with "TON"."""
    doc = "\n".join(
        [
            "Buy Stars & Premium for any @username, paid in **GRAM (ex TON)** or **USDT (TON)**.",
            "",
            "Later in the very same file: you can also pay in TON if you prefer.",
        ]
    )
    found = coin_mentions(doc)
    assert len(found) == 1, found
    assert "pay in TON" in found[0]


@pytest.mark.parametrize("rel", [r for r in MARKDOWN if r.endswith("README.md")])
def test_readme_explains_the_ticker_at_its_first_mention(rel: str) -> None:
    """The REPLACEMENT for the deleted caps: required presence AND position."""
    found, explained, snippet = first_coin_mention((ROOT / rel).read_text(encoding="utf-8"))
    if not found:
        return
    assert explained, f"unexplained first mention in {rel}: {snippet}"


def test_ordinal_rule_accepts_an_explained_first_mention_and_rejects_a_late_one() -> None:
    assert first_coin_mention("# Doc\n\n> **GRAM** is the coin formerly named TON.\n\nPay 5 GRAM.")[1]
    assert first_coin_mention("# Doc\n\nPaid in **GRAM (ex TON)** or **USDT**.")[1]
    # The exact shape this rule exists to catch: explained, but too late.
    assert not first_coin_mention("# Doc\n\nPay 5 GRAM now.\n\nLater: **GRAM (ex TON)**.")[1]
    assert not first_coin_mention("# Doc\n\nNo coin named here.")[0]
