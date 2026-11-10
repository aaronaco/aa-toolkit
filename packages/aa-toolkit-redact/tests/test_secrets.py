"""A default Redactor finding common secrets and card numbers."""

import base64
import json

import pytest

from aa_redact import Redactor

# Test values are put together from pieces, so secret scanners don't flag this file.
AWS_KEY = "AK" + "IA" + "IOSFODNN7EXAMPLE"
GITHUB_TOKEN = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2
FINE_GRAINED_GITHUB_TOKEN = "github" + "_pat_" + "11ABCDEFG0" * 3 + "_" + "aBcDeFgHiJ" * 6
OPENAI_KEY = "sk" + "-" + "T3BlbkFJa1B2c3D4e5F6g7H8i9J0kLmN" * 2
OPENAI_PROJECT_KEY = "sk" + "-proj-" + "Ab1_Cd2-Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv" * 3
SLACK_TOKEN = "xo" + "xb-" + "123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"


def jwt(payload: dict[str, object]) -> str:
    def part(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(payload)}.c2lnbmF0dXJlLWJ5dGVz_x-Y"


JWT = jwt({"sub": "1234567890", "name": "Ann"})
UNSIGNED_JWT = jwt({"sub": "1"}).rsplit(".", 1)[0] + "."


def private_key(label: str = "", *, end: bool = True, newline: str = "\n") -> str:
    lines = [
        f"-----BEGIN {label}PRIVATE KEY-----",
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj",
        "MzEfYyjiWA4R4/M2bS1GB4t7NXp98C3SC6dVMvDuictGeurT8jNbvJZHtCSuYEvu",
        "NMoSfm76oqFvAp8Gy0iz5sxjZmSnXyCdPEovGhLa0VzMaQ8s+CLOyS56YyCFGeJZ==",
    ]
    if end:
        lines.append(f"-----END {label}PRIVATE KEY-----")
    return newline.join(lines)


def with_check_digit(digits: str) -> str:
    """Add the digit that makes `digits` pass the Luhn check."""
    total = 0
    for position, digit in enumerate(reversed(digits)):
        value = int(digit) * (2 if position % 2 == 0 else 1)
        total += value - 9 if value > 9 else value
    return digits + str(-total % 10)


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        (f"key {AWS_KEY} used", "key [AWS_ACCESS_KEY] used"),
        (f"key {'AS' + 'IA' + 'Y34FZKBOKMUTVV7A'}", "key [AWS_ACCESS_KEY]"),
        (f"token {GITHUB_TOKEN} used", "token [GITHUB_TOKEN] used"),
        (f"push with {FINE_GRAINED_GITHUB_TOKEN}", "push with [GITHUB_TOKEN]"),
        (f"app {'gh' + 's_' + 'Z9y8X7w6V5u4T3s2R1q0' * 2}", "app [GITHUB_TOKEN]"),
        (f"key {OPENAI_KEY} used", "key [API_KEY] used"),
        (f"key {OPENAI_PROJECT_KEY} used", "key [API_KEY] used"),
        (f"key {'sk' + '-' + '0123456789abcdef' * 2} used", "key [API_KEY] used"),
        (f"key {'sk' + '-' + 'AB12' * 8} used", "key [API_KEY] used"),
        (f"bot {SLACK_TOKEN} posted", "bot [SLACK_TOKEN] posted"),
        (f"session {JWT} expired", "session [JWT] expired"),
        (f"session {UNSIGNED_JWT} expired", "session [JWT] expired"),
        ("sent Bearer abc123DEF456ghi789 upstream", "sent [BEARER_TOKEN] upstream"),
        (f"sent bearer {JWT}", "sent [BEARER_TOKEN]"),
        (f"loaded {private_key()} ok", "loaded [PRIVATE_KEY] ok"),
        (f"loaded {private_key('RSA ')} ok", "loaded [PRIVATE_KEY] ok"),
        (f"loaded {private_key('OPENSSH ')} ok", "loaded [PRIVATE_KEY] ok"),
        (f"loaded {private_key('ENCRYPTED ')} ok", "loaded [PRIVATE_KEY] ok"),
        (f"loaded {private_key('EC ', newline=chr(13) + chr(10))} ok", "loaded [PRIVATE_KEY] ok"),
        ('{"pem": "' + private_key(newline="\\n") + '"}', '{"pem": "[PRIVATE_KEY]"}'),
        (f"loaded {private_key(newline=' ')} ok", "loaded [PRIVATE_KEY] ok"),
        ("card 4111 1111 1111 1111 declined", "card [CARD] declined"),
        ("card 4111-1111-1111-1111 declined", "card [CARD] declined"),
        ("card 4111111111111111 declined", "card [CARD] declined"),
        ("card=4111111111111111&cvv=1", "card=[CARD]&cvv=1"),
        ("visa 4222222222222", "visa [CARD]"),
        ("mastercard 5555555555554444", "mastercard [CARD]"),
        ("mastercard 2223003122003222", "mastercard [CARD]"),
        ("amex 3782 822463 10005", "amex [CARD]"),
        ("amex 378282246310005", "amex [CARD]"),
        ("amex 3782 8224 6310 005", "amex [CARD]"),
        ("card 4111.1111.1111.1111 declined", "card [CARD] declined"),
        ("discover 6011111111111117", "discover [CARD]"),
        ("jcb 3530111333300000", "jcb [CARD]"),
        ("diners 30569309025904", "diners [CARD]"),
        ("diners 3056 930902 5904", "diners [CARD]"),
        ("unionpay 6200000000000005", "unionpay [CARD]"),
        (f"long visa {with_check_digit('411111111111111111')}", "long visa [CARD]"),
        ("card 4111111111111111 exp 12 25", "card [CARD] exp 12 25"),
        ("card 4111 1111 1111 1111 12 25", "card [CARD] 12 25"),
        ("ref 9999 4111 1111 1111 1111", "ref 9999 [CARD]"),
    ],
)
def test_each_built_in_kind_of_value_becomes_its_placeholder(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    "text",
    [
        "AKIA",
        "AKIA" + "IOSFODNN7EX",
        "AKIA" + "iosfodnn7example",
        "XAKIA" + "IOSFODNN7EXAMPLE",
        "AKIB" + "IOSFODNN7EXAMPLE",
        "ghp_",
        "gh" + "p_" + "short1234",
        "gh" + "x_" + "a1B2c3D4e5F6g7H8i9J0" * 2,
        "xgh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2,
        "github_pat_",
        "github" + "_pat_" + "short",
        "pip install scikit-learn",
        "sk-learn-compatible-transformers-pipeline",
        "sk-" + "a1B2c3D4e5",
        "sk-" + "abcdefghijklmnopqrstuvwxyzabcdef",
        "task-" + "T3BlbkFJa1B2c3D4e5F6g7H8i9J0kLmN",
        "xoxo-hugs-and-kisses-forever",
        "xo" + "xb-" + "12345",
        "eyJhbGciOiJIUzI1NiJ9",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0",
        "eyJ.eyJ.sig",
        "the bearer of bad news",
        "Bearer Authentication is a scheme",
        "BEARER TOKENISATION",
        "bearer token",
        "Bearer abc",
        "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A\n-----END PUBLIC KEY-----",
        "-----BEGIN CERTIFICATE-----\nMIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUF",
        "BEGIN " + "PRIVATE KEY",
        "https://example.com:8080/path",
        "ssh://git@localhost:22/repo",
        "http://[::1]:8080/",
        "see https://example.com/a:b@c",
        "ratio a:b@c",
        "card 4111111111111112 declined",
        "card 4111 1111 1111 1112 declined",
        "number 41111111111111110000",
        "order 4111 1111 1111 111",
        "amex 3782822463100055",
        "uptime 1731312000000 ms",
    ],
)
def test_a_look_alike_of_each_kind_stays_unchanged(text):
    assert Redactor()(text) == text


@pytest.mark.parametrize(
    "number",
    [
        with_check_digit("999999999999999"),
        with_check_digit("123456781234567"),
        with_check_digit("700000000000000"),
        with_check_digit("1" * 18),
    ],
)
def test_a_number_that_passes_the_luhn_check_without_a_known_issuer_prefix_stays(number):
    text = f"order {number} shipped"

    assert Redactor()(text) == text


@pytest.mark.parametrize(
    "text",
    [
        f"loaded {private_key(end=False)}",
        f"loaded {private_key('RSA ', end=False)}",
        f"loaded {private_key(end=False, newline='')}",
        "loaded -----BEGIN " + "PRIVATE KEY-----",
        "loaded -----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkq",
    ],
)
def test_a_private_key_with_no_end_line_is_still_hidden(text):
    assert Redactor()(text) == "loaded [PRIVATE_KEY]"


@pytest.mark.parametrize(
    "key",
    [
        private_key(newline=""),
        private_key().replace("\nMzEf", "MIIEvQIBADANBgkq" * 40 + "\nMzEf"),
    ],
)
def test_a_private_key_whose_lines_are_joined_or_long_is_hidden_whole(key):
    assert Redactor()(f"loaded {key} ok") == "loaded [PRIVATE_KEY] ok"


def test_a_pgp_private_key_block_is_hidden():
    block = "\n".join(
        [
            "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----",
            "",
            "lQOYBGVhY2gBCADXc9mF3m8x1JmYj7wq0cP8n1sG2y5Dqk2y4c1QGq3u6u2b7h9a",
            "=pQ7x",
            "-----END PGP " + "PRIVATE KEY BLOCK-----",
        ]
    )

    assert Redactor()(f"exported {block} done") == "exported [PRIVATE_KEY] done"


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        (
            "postgres://bob:s3cret@db.example.com:5432/app",
            "postgres://bob:[URL_PASSWORD]@db.example.com:5432/app",
        ),
        ("redis://:s3cret@localhost:6379/0", "redis://:[URL_PASSWORD]@localhost:6379/0"),
        (
            "https://ann:p%40ss@example.com/path?q=1",
            "https://ann:[URL_PASSWORD]@example.com/path?q=1",
        ),
        ("amqp://guest:p@ss@rabbit.local/", "amqp://guest:[URL_PASSWORD]@rabbit.local/"),
        (
            "mongodb+srv://bob.smith:pw:with:colons@cluster0.example.net",
            "mongodb+srv://bob.smith:[URL_PASSWORD]@cluster0.example.net",
        ),
        (
            'connect "mysql://root:toor@127.0.0.1/db" failed',
            'connect "mysql://root:[URL_PASSWORD]@127.0.0.1/db" failed',
        ),
        (
            "from postgres://a:x@h1/db to postgres://b:y@h2/db",
            "from postgres://a:[URL_PASSWORD]@h1/db to postgres://b:[URL_PASSWORD]@h2/db",
        ),
        (
            "https://x-access-token:abc123XYZ@github.com/o/r.git",
            "https://x-access-token:[URL_PASSWORD]@github.com/o/r.git",
        ),
        ("postgres://app_token:pw123@db/x", "postgres://app_token:[URL_PASSWORD]@db/x"),
        (
            '{"url": "postgres:\\/\\/bob:s3cret@db\\/app"}',
            '{"url": "postgres:\\/\\/bob:[URL_PASSWORD]@db\\/app"}',
        ),
    ],
)
def test_a_password_in_a_url_is_hidden_and_the_rest_of_the_url_stays(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("AWS_ACCESS_KEY", f"key {AWS_KEY}"),
        ("GITHUB_TOKEN", f"key {GITHUB_TOKEN}"),
        ("API_KEY", f"key {OPENAI_KEY}"),
        ("SLACK_TOKEN", f"key {SLACK_TOKEN}"),
        ("JWT", f"key {JWT}"),
        ("BEARER_TOKEN", "key Bearer abc123DEF456ghi789"),
        ("PRIVATE_KEY", f"key {private_key()}"),
        ("URL_PASSWORD", "key postgres://bob:s3cret@db/app"),
        ("CARD", "key 4111111111111111"),
    ],
)
def test_without_turns_off_only_the_kind_it_names(kind, text):
    others = f"{text} and bob@example.com and 5555555555554444"
    if kind == "CARD":
        others = f"{text} and bob@example.com and {AWS_KEY}"

    cleaned = Redactor(without=[kind])(others)

    assert cleaned.startswith(f"{text} and ")
    assert f"[{kind}]" not in cleaned
    assert "[EMAIL]" in cleaned
    assert cleaned.endswith("[CARD]" if kind != "CARD" else "[AWS_ACCESS_KEY]")
