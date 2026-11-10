"""An app passing any kind of value to a Redactor and getting the same shape back."""

import re
from decimal import Decimal
from fractions import Fraction
from typing import NamedTuple

import pytest

from aa_redact import Finding, Redactor, pattern


@pytest.mark.parametrize(
    ("value", "cleaned"),
    [
        ({"to": "bob@example.com", "qty": 2}, {"to": "[EMAIL]", "qty": 2}),
        (["bob@example.com", "paid"], ["[EMAIL]", "paid"]),
        (("bob@example.com", "paid"), ("[EMAIL]", "paid")),
        ({"bob@example.com", "paid"}, {"[EMAIL]", "paid"}),
        (frozenset({"bob@example.com"}), frozenset({"[EMAIL]"})),
        ([], []),
        ({}, {}),
        ((), ()),
    ],
)
def test_a_structure_comes_back_in_the_same_shape_with_every_value_cleaned(value, cleaned):
    result = Redactor()(value)

    assert result == cleaned
    assert type(result) is type(cleaned)


def test_values_are_cleaned_at_any_depth():
    value = {"orders": [{"contacts": ({"to": "bob@example.com"}, ["ann@example.com", 7])}]}

    assert Redactor()(value) == {"orders": [{"contacts": ({"to": "[EMAIL]"}, ["[EMAIL]", 7])}]}


def test_the_value_passed_in_is_not_changed():
    value = {"contacts": ["bob@example.com"]}

    Redactor()(value)

    assert value == {"contacts": ["bob@example.com"]}


def test_the_same_list_used_twice_is_cleaned_both_times():
    shared = ["bob@example.com"]

    assert Redactor()([shared, shared]) == [["[EMAIL]"], ["[EMAIL]"]]


def test_a_dictionary_key_holding_an_email_is_cleaned_too():
    assert Redactor()({"bob@example.com": "paid"}) == {"[EMAIL]": "paid"}


def test_a_key_that_is_not_text_keeps_its_type():
    assert Redactor()({7: "bob@example.com", ("a", 1): "x"}) == {7: "[EMAIL]", ("a", 1): "x"}


def digits(text):
    return [Finding("DIGITS", *match.span()) for match in re.finditer(r"\d{4}", text)]


@pytest.mark.parametrize("number", [4111, 41.11e3, Decimal("4111.5")])
def test_a_number_that_matches_a_detector_becomes_a_placeholder(number):
    assert "[DIGITS]" in Redactor(detectors=[digits])(number)


@pytest.mark.parametrize("number", [12, 1.5, -3, Decimal("2.50"), Fraction(1, 3), 2j])
def test_a_number_that_does_not_match_stays_a_number(number):
    result = Redactor(detectors=[digits])(number)

    assert result == number
    assert type(result) is type(number)


@pytest.mark.parametrize("value", [None, True, False])
def test_none_and_booleans_are_left_alone(value):
    assert Redactor(detectors=[pattern("WORD", r"\w+")])(value) is value


class Customer:
    def __str__(self):
        return "customer bob@example.com"


class Broken:
    def __str__(self):
        raise LookupError("bob@example.com")


class Plain:
    pass


def test_an_object_is_checked_as_the_text_it_would_be_shown_as():
    assert Redactor()(Customer()) == "customer [EMAIL]"


def test_an_object_with_nothing_to_hide_comes_back_as_its_text():
    assert Redactor()(ValueError("no stock")) == "no stock"


def test_an_object_inside_a_structure_is_checked_too():
    assert Redactor()({"who": [Customer()]}) == {"who": ["customer [EMAIL]"]}


def test_a_named_tuple_comes_back_as_the_same_named_tuple():
    class Contact(NamedTuple):
        to: str
        note: str

    result = Redactor()(Contact("bob@example.com", "paid"))

    assert result == Contact("[EMAIL]", "paid")
    assert type(result) is Contact


def test_a_key_that_cannot_be_turned_into_text_becomes_a_note_and_its_value_is_still_cleaned():
    assert Redactor()({Broken(): "bob@example.com"}) == {"[UNPRINTABLE Broken]": "[EMAIL]"}


def test_an_object_that_cannot_be_turned_into_text_becomes_a_note_naming_its_type():
    assert Redactor()(Broken()) == "[UNPRINTABLE Broken]"


def test_a_number_too_long_to_turn_into_text_becomes_a_note():
    assert Redactor()(10**5000) == "[UNPRINTABLE int]"


@pytest.mark.parametrize("kind", [bytes, bytearray, memoryview])
def test_bytes_are_decoded_and_checked_as_text(kind):
    assert Redactor()(kind(b"to bob@example.com")) == "to [EMAIL]"


def test_bytes_with_nothing_to_hide_come_back_as_text():
    assert Redactor()(b"paid") == "paid"


def test_bytes_that_are_not_valid_text_still_finish_and_are_checked():
    assert Redactor()(b"\xff\xfe to bob@example.com") == "�� to [EMAIL]"


def test_a_list_that_contains_itself_has_that_part_hidden():
    loop = ["bob@example.com"]
    loop.append(loop)

    assert Redactor()(loop) == ["[EMAIL]", "[REDACTED]"]


def test_a_dictionary_that_contains_itself_has_that_part_hidden():
    loop = {"to": "bob@example.com"}
    loop["self"] = loop

    assert Redactor()(loop) == {"to": "[EMAIL]", "self": "[REDACTED]"}


def test_a_tuple_that_contains_itself_through_a_list_has_that_part_hidden():
    inner = []
    loop = (inner,)
    inner.append(loop)

    assert Redactor()(loop) == (["[REDACTED]"],)


def nested(levels, innermost):
    value = innermost
    for _ in range(levels):
        value = [value]
    return value


def depth_of(value):
    levels = 0
    while isinstance(value, list):
        value, levels = value[0], levels + 1
    return levels, value


def test_a_structure_nested_past_the_limit_has_that_part_hidden_and_the_call_finishes():
    assert depth_of(Redactor()(nested(100_000, "secret text"))) == (32, "[REDACTED]")


def test_a_structure_at_the_limit_is_kept_whole():
    assert depth_of(Redactor()(nested(32, "bob@example.com"))) == (32, "[EMAIL]")
