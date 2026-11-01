"""The README's ``## Errors`` table names every error class the package exports.

It is the reader's map from an HTTP status to the class to catch, so a class missing from it is a
class integrators do not know to handle.
"""

from __future__ import annotations

import re
from pathlib import Path

import mystars_faas
from mystars_faas import MyStarsError

README = Path(__file__).resolve().parents[1] / "README.md"


def _rows() -> list[tuple[set[str], str]]:
    text = README.read_text(encoding="utf-8")
    section = text.split("\n## Errors\n", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not line.lstrip().startswith("|") or set(cells[0]) <= {"-", " "}:
            continue
        rows.append((set(re.findall(r"`([A-Za-z_]+)`", cells[0])), cells[1]))
    return rows


def _exported_error_classes() -> set[str]:
    return {
        name
        for name in mystars_faas.__all__
        if isinstance(getattr(mystars_faas, name), type)
        and issubclass(getattr(mystars_faas, name), MyStarsError)
        and getattr(mystars_faas, name).__name__ == name  # aliases have their own column
        and name != "MyStarsError"
    }


def test_every_exported_error_class_has_a_row():
    listed = set().union(*(names for names, _ in _rows()))
    assert _exported_error_classes() - listed == set()


def test_the_rows_name_the_status_each_class_is_raised_for():
    status = {name: http for names, http in _rows() for name in names}
    assert "409" in status["IdempotencyInFlightError"]
    assert "422" in status["UnprocessableError"]
    assert "422" in status["RecipientIneligibleError"]
    assert "503" in status["FeatureUnavailableError"]
    assert "client-side" in status["WebhookVerificationError"]
    assert "client-side" in status["OrderWaitTimeout"]
