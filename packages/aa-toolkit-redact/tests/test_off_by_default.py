"""IP addresses and phone numbers: built in, and found only when an app turns them on."""

import pytest

from aa_redact import Redactor, ip_address, phone_number

IP_ADDRESSES = [
    ("from 203.0.113.7 at noon", "from [IP_ADDRESS] at noon"),
    ("host=10.0.0.1:8080", "host=[IP_ADDRESS]:8080"),
    ("ip 255.255.255.255.", "ip [IP_ADDRESS]."),
    ("from 2001:db8::8a2e:370:7334 at noon", "from [IP_ADDRESS] at noon"),
    ("from 2001:0db8:0000:0000:0000:ff00:0042:8329", "from [IP_ADDRESS]"),
    ("loopback ::1.", "loopback [IP_ADDRESS]."),
    ("mapped ::ffff:192.0.2.128 ok", "mapped [IP_ADDRESS] ok"),
    ("url http://[2001:db8::1]:8080/", "url http://[[IP_ADDRESS]]:8080/"),
    ("peer ::1: unavailable", "peer [IP_ADDRESS]: unavailable"),
    ("peer fe80::1: unavailable", "peer [IP_ADDRESS]: unavailable"),
    ("route 2001:db8:: is up", "route [IP_ADDRESS] is up"),
]

PHONE_NUMBERS = [
    ("call +1 555 123 4567 now", "call [PHONE] now"),
    ("call +15551234567 now", "call [PHONE] now"),
    ("call +44 20 7946 0958 now", "call [PHONE] now"),
    ("call +63 917 123 4567 now", "call [PHONE] now"),
    ("call +1 (555) 123-4567 now", "call [PHONE] now"),
    ("call (555) 123-4567 now", "call [PHONE] now"),
    ("call 555-123-4567 now", "call [PHONE] now"),
    ("call 555.123.4567.", "call [PHONE]."),
    ("call 020 7946 0958 now", "call [PHONE] now"),
    ("call 0917-123-4567 now", "call [PHONE] now"),
]


@pytest.mark.parametrize("text", [text for text, _ in IP_ADDRESSES + PHONE_NUMBERS])
def test_a_default_redactor_leaves_ip_addresses_and_phone_numbers_alone(text):
    assert Redactor()(text) == text


@pytest.mark.parametrize(("text", "cleaned"), IP_ADDRESSES + PHONE_NUMBERS)
def test_ip_addresses_and_phone_numbers_are_found_once_passed_in_detectors(text, cleaned):
    assert Redactor(detectors=[ip_address, phone_number])(text) == cleaned


@pytest.mark.parametrize(
    "text",
    [
        "version 1.2.3",
        "version 1.2.3.4.5",
        "build 999.1.1.1",
        "01.02.03.04",
        "time 12:30:45",
        "mac 00:1A:2B:3C:4D:5E",
        "std::vector",
        "a :: b",
        "ratio 3:4",
        "abc:def",
    ],
)
def test_a_look_alike_is_not_an_ip_address(text):
    assert Redactor(detectors=[ip_address])(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "on 2026-11-11",
        "order 12345678",
        "order 12345678901",
        "total 1 000 000",
        "ip 192.168.1.10",
        "call 555-123-45678",
        "+12",
        "card 4111 1111 1111 1112",
        "id abc-555-123-4567",
    ],
)
def test_a_look_alike_is_not_a_phone_number(text):
    assert Redactor(detectors=[phone_number])(text) == text


def test_ip_address_and_phone_number_each_work_alone():
    assert Redactor(detectors=[ip_address])("10.0.0.1 or +15551234567") == (
        "[IP_ADDRESS] or +15551234567"
    )
    assert Redactor(detectors=[phone_number])("10.0.0.1 or +15551234567") == "10.0.0.1 or [PHONE]"
