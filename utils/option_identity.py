"""Comparison keys for displayed answers, never persisted content identities.

Question-stem normalization deliberately discards punctuation. Answer options
cannot: a minus sign, decimal point or fraction bar can change their value.
This parser handles bounded literal quantities, not arbitrary expressions or
unit conversions. Independent answer/proof verification remains mandatory.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from fractions import Fraction

from utils.hashing import normalize_text

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯−", "0123456789-")
_NUMBER = r"[+-]?(?:[0-9]{1,64}(?:\.[0-9]{0,64})?|\.[0-9]{1,64})(?:e[+-]?[0-9]{1,3})?"
_QUANTITY = re.compile(
    rf"(?P<number>{_NUMBER})(?:\s*[/：:]\s*(?P<denominator>{_NUMBER}))?"
    r"(?:\s*(?P<unit>[%°a-z\u0980-\u09ff][%°a-z\u0980-\u09ff²³/ .]*))?"
)
_EXPLICIT_LABEL = re.compile(
    r"^(?:(?:option|বিকল্প)\s*[a-dক-ঘ1-4]\s*[:.)-]\s*"
    r"|[a-dক-ঘ][.):]\s+|[([][a-dক-ঘ][)\]]\s*)"
)
_GROUPED_NUMBER = re.compile(r"(?<![\w.])[0-9][0-9,]*(?:,[0-9]+)+(?![0-9,])")


def _ungroup(match: re.Match[str]) -> str:
    text = match.group()
    # Western and Indian digit grouping only. Do not guess decimal commas.
    if re.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}", text):
        return text.replace(",", "")
    return text


def option_identity(value: object) -> str:
    text = unicodedata.normalize("NFC", str(value)).strip().lower().translate(_DIGITS)
    # Bare numeric prefixes are values, not option labels: "1.5" and "1:2"
    # must never lose their first digit. Ambiguous bare-letter prose is kept.
    text = _EXPLICIT_LABEL.sub("", text, count=1).strip()
    text = text.rstrip("।").strip()
    if len(text) >= 2 and (text[0], text[-1]) in {('"', '"'), ("'", "'"), ("‘", "’"), ("“", "”")}:
        text = text[1:-1].strip()
    if not re.search(r"[\w\u0980-\u09ff]", text):
        return ""
    if len(text) <= 256:
        quantity = _QUANTITY.fullmatch(_GROUPED_NUMBER.sub(_ungroup, text))
        if quantity:
            number = Fraction(Decimal(quantity["number"]))
            if quantity["denominator"] is not None:
                denominator = Fraction(Decimal(quantity["denominator"]))
                if not denominator:
                    # Invalid fractions cannot claim a numeric equivalence.
                    return "expression:" + re.sub(r"\s+", "", text)
                number /= denominator
            unit = re.sub(r"[\s.]+", "", quantity["unit"] or "")
            if unit in {"%", "শতাংশ", "percent"}:
                number /= 100
                unit = ""
            return f"quantity:{number.numerator}/{number.denominator}:{unit}"
    # Unknown numeric expressions retain meaningful operators; no eval and no
    # claim that a symbolic identity or unit conversion has been proved.
    if re.search(r"[0-9]|[+*/=<>^√±]|\b[a-z]\s*-\s*[a-z]\b", text):
        return "expression:" + re.sub(r"[\s।]+", "", text)
    # Preserve existing punctuation/spacing-insensitive comparisons for prose.
    return re.sub(r"[^\w\u0980-\u09ff]+", "", normalize_text(text))
