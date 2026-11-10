"""Text longer than max_length is cut and marked [TRUNCATED], without leaving half a secret."""

import pytest

from aa_redact import Redactor, known_values

DEFAULT_LIMIT = 64 * 1024
GITHUB_TOKEN = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2
PRIVATE_KEY = "\n".join(
    [
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        *["MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"] * 60,
        "-----END RSA " + "PRIVATE KEY-----",
    ]
)


def test_text_longer_than_the_default_limit_is_cut_and_marked_truncated():
    before_cut = "a" * DEFAULT_LIMIT
    cleaned = Redactor()(before_cut + "past the cut bob@example.com")

    assert cleaned == before_cut + "[TRUNCATED]"
    assert "past the cut" not in cleaned


def test_text_at_the_default_limit_is_kept_whole():
    text = "a" * (DEFAULT_LIMIT - 16) + " bob@example.com"

    assert Redactor()(text) == "a" * (DEFAULT_LIMIT - 16) + " [EMAIL]"


def test_max_length_set_by_the_app_is_used():
    redact = Redactor(max_length=10)

    assert redact("0123456789") == "0123456789"
    assert redact("0123456789 extra") == "0123456789[TRUNCATED]"


@pytest.mark.parametrize(
    ("value", "placeholder"),
    [
        ("bob.smith@example.com", "[EMAIL]"),
        (GITHUB_TOKEN, "[GITHUB_TOKEN]"),
        (PRIVATE_KEY, "[PRIVATE_KEY]"),
        ("correct-horse-battery-staple", "[DB_PASSWORD]"),
    ],
)
def test_a_value_sitting_across_the_limit_is_found_and_no_part_of_it_comes_back(
    value, placeholder
):
    redact = Redactor(
        detectors=[known_values("DB_PASSWORD", ["correct-horse-battery-staple"])],
        max_length=10,
    )
    cleaned = redact(f"user: {value} and more after")

    assert cleaned == f"user: {placeholder}[TRUNCATED]"
    assert value[:4] not in cleaned
    assert "and more" not in cleaned


def test_a_private_key_sitting_across_the_default_limit_is_found_whole():
    prefix = "a " * (DEFAULT_LIMIT // 2 - 5)
    cleaned = Redactor()(f"{prefix}{PRIVATE_KEY} after the key")

    assert cleaned == f"{prefix}[PRIVATE_KEY][TRUNCATED]"
    assert "BEGIN" not in cleaned
    assert "MIIE" not in cleaned
    assert "after the key" not in cleaned


def test_a_pair_sitting_across_the_limit_is_hidden_and_no_part_of_the_value_comes_back():
    redact = Redactor(max_length=12)

    assert redact("password=hunter2 and more") == "password=[REDACTED][TRUNCATED]"


def test_a_url_password_sitting_across_the_limit_is_hidden_and_no_part_of_it_comes_back():
    redact = Redactor(max_length=18)

    assert (
        redact("postgres://bob:hunter2@db.example.com/app")
        == "postgres://bob:[URL_PASSWORD][TRUNCATED]"
    )


def test_a_value_completely_past_the_limit_is_dropped_without_leaving_a_placeholder():
    redact = Redactor(max_length=10)

    assert redact("0123456789 bob@example.com") == "0123456789[TRUNCATED]"


def test_detectors_do_not_receive_text_past_the_limit_and_key_margin():
    seen = []

    def spy(text):
        seen.append(len(text))
        return []

    redact = Redactor(detectors=[spy], max_length=100)
    redact("a" * 200_000)

    assert seen == [100 + 16 * 1024]


def test_a_nested_value_longer_than_the_limit_is_cut_and_marked_truncated():
    redact = Redactor(max_length=10)

    assert redact({"note": "0123456789 extra", "ok": "short"}) == {
        "note": "0123456789[TRUNCATED]",
        "ok": "short",
    }


@pytest.mark.parametrize("limit", [0, -1, False, True])
def test_a_max_length_below_one_or_not_a_count_raises_when_the_redactor_is_made(limit):
    with pytest.raises((TypeError, ValueError), match="max_length"):
        Redactor(max_length=limit)
