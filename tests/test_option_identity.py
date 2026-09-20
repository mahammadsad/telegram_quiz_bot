from fractions import Fraction

import pytest

from utils.hashing import normalize_text
from utils.option_identity import option_identity


@pytest.mark.parametrize("first,second", [
    ("২৫", "25"), ("1.5", "১.৫০"), ("-0", "+0.000"),
    ("1/2", "0.50"), ("2:4", "0.5"), ("50%", "0.5"),
    ("৫০ শতাংশ", "0.5"), ("1e3", "1000"),
    ("1,000.5", "1000.50"), ("১,০০,০০০.৫ টাকা", "100000.5 টাকা"),
    ("বিকল্প ক: ২৫", "A. 25"), ("(A) 1.25", "option 1: 1.250"),
    ("New-York", "New York"), ("দিল্লি।", "দিল্লি"),
    ("5 cm.", "৫.০ cm"), ("৫।", "5"), ("“৫”", "5"),
])
def test_equivalent_values_have_one_key(first, second):
    assert option_identity(first) == option_identity(second)


@pytest.mark.parametrize("first,second", [
    ("1.5", "2.5"), ("-25", "25"), ("1.25", "12.5"),
    ("1/2", "12"), ("5%", "5"), ("1 m", "1 cm"),
    ("1,5", "15"), ("1,00", "100"), ("x+1", "x-1"),
    ("a+b", "a-b"), ("2^-1", "2^1"), ("A place", "place"),
    ("ক জন", "জন"), ("5!", "5!!"), ("5'", '5"'),
])
def test_meaningful_differences_are_not_erased(first, second):
    assert option_identity(first) != option_identity(second)


def test_literal_fraction_comparison_is_exact_not_rounded():
    assert option_identity("1/3") != option_identity("0.3333333333333333333333333333")
    values = [Fraction(number, 10) for number in range(-40, 41)]
    keys = [option_identity(f"{value.numerator}/{value.denominator}") for value in values]
    assert len(set(keys)) == len(values)


@pytest.mark.parametrize("value", ["1/0", "1e99999999", "9" * 10000, "NaN", "Infinity", "__import__('os')"])
def test_unknown_or_unbounded_literals_are_not_evaluated(value):
    assert isinstance(option_identity(value), str)


def test_stem_hash_normalization_contract_is_unchanged():
    assert normalize_text("-1.5") == "1 5"
    assert option_identity("-1.5") != option_identity("1.5")


@pytest.mark.parametrize("value", ["", " ", "...", "।", "+", "-", "*"])
def test_empty_and_punctuation_only_choices_stay_invalid(value):
    assert option_identity(value) == ""
