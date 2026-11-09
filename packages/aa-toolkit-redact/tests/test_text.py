"""An app creating a Redactor and calling it with text."""

import pytest

from aa_redact import Redactor


def test_an_email_is_replaced_and_the_rest_of_the_text_is_unchanged():
    redact = Redactor()

    assert (
        redact("order 4521 for bob.smith@example.com, paid 12.50")
        == "order 4521 for [EMAIL], paid 12.50"
    )


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("bob@example.com", "[EMAIL]"),
        ("Bob.Smith+orders@mail.example.co.uk", "[EMAIL]"),
        ("first_last-99@sub-domain.example.org", "[EMAIL]"),
        ("<bob@example.com>", "<[EMAIL]>"),
        ("mailto:bob@example.com", "mailto:[EMAIL]"),
        ('{"email": "bob@example.com"}', '{"email": "[EMAIL]"}'),
        ("email=bob@example.com&page=2", "email=[EMAIL]&page=2"),
        ("Write to bob@example.com.", "Write to [EMAIL]."),
        ("from a@example.com to b@example.com", "from [EMAIL] to [EMAIL]"),
        ("josé@example.com", "[EMAIL]"),
        ("bob@münchen.de", "[EMAIL]"),
        ("bob@example.xn--p1ai", "[EMAIL]"),
        ("bob@aa.bb.cc.dd.ee.ff.gg.hh.ii.company.com", "[EMAIL]"),
        ("bob@" + "a." * 125 + "com.", "[EMAIL]."),
        ("bob@xn--mnchen-3ya.XN--P1AI.", "[EMAIL]."),
    ],
)
def test_an_email_is_found(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no email here",
        "@bob mentioned you",
        "a @ b",
        "bob@",
        "bob@localhost",
        "bob@example",
        "bob@example.c",
        "bob@.com",
        "bob@example.123",
        "price: 3 @ 4.50 each",
        "user@@example..com",
    ],
)
def test_a_look_alike_is_not_an_email(text):
    assert Redactor()(text) == text
