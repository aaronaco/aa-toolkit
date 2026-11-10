"""Values hidden because of the name they sit under, whatever they look like."""

from collections import namedtuple
from dataclasses import dataclass

import pytest

from aa_redact import Redactor

HIDDEN_NAMES = [
    "password",
    "PASSWORD",
    "password_hash",
    "passwords",
    "db_password",
    "user-password",
    "userPassword",
    "passWord",
    "passwd",
    "old_passwd",
    "secret",
    "secret_key",
    "client_secret",
    "SecretKey",
    "credential",
    "credentials",
    "aws_credentials_file",
    "token",
    "access_token",
    "accessToken",
    "X-Auth-Token",
    "oauth2Token",
    "api_key",
    "apiKey",
    "APIKey",
    "X-Api-Key",
    "apikey",
    "x_apikey",
    "access_key",
    "awsAccessKey",
    "private_key",
    "privateKey",
    "authorization",
    "Authorization",
    "Proxy-Authorization",
    "cookie",
    "Set-Cookie",
    "pwd",
    "db_pwd",
    "passphrase",
    "key_passphrase",
    "db.password",
    "password_length",
    "secretary",
]

VISIBLE_NAMES = [
    "token_count",
    "max_tokens",
    "tokens",
    "tokenizer",
    "username",
    "email",
    "api_key_id",
    "key",
    "cookie_count",
    "authorization_url",
    "pwd_changed",
    "passphrase_hint",
    "",
]


@pytest.mark.parametrize("name", HIDDEN_NAMES)
def test_a_value_under_a_sensitive_name_is_hidden(name):
    assert Redactor()({name: "abc123"}) == {name: "[REDACTED]"}


@pytest.mark.parametrize("name", VISIBLE_NAMES)
def test_a_value_under_any_other_name_stays(name):
    assert Redactor()({name: "abc123"}) == {name: "abc123"}


@pytest.mark.parametrize("value", [{"user": "bob"}, ["a", "b"], ("a",), {"a"}, 1234, 1.5, b"abc"])
def test_every_kind_of_value_under_a_sensitive_name_is_hidden_as_a_whole(value):
    assert Redactor()({"password": value}) == {"password": "[REDACTED]"}


@pytest.mark.parametrize("value", [None, True, False])
def test_none_and_booleans_under_a_sensitive_name_stay(value):
    assert Redactor()({"password": value}) == {"password": value}


def test_an_empty_text_under_a_sensitive_name_is_hidden():
    assert Redactor()({"password": ""}) == {"password": "[REDACTED]"}


def test_a_sensitive_name_counts_at_any_depth():
    value = {"users": [{"name": "bob", "access_token": "abc123"}]}

    assert Redactor()(value) == {"users": [{"name": "bob", "access_token": "[REDACTED]"}]}


def test_a_key_written_as_bytes_counts_as_a_name():
    assert Redactor()({b"password": "abc123"}) == {"password": "[REDACTED]"}


def test_a_number_used_as_a_key_is_not_a_name():
    assert Redactor(names=["7"])({7: "abc123"}) == {7: "abc123"}


def test_a_detector_still_checks_a_value_under_an_ordinary_name():
    assert Redactor()({"token_count": "bob@example.com"}) == {"token_count": "[EMAIL]"}


def test_a_word_passed_in_names_hides_fields_ending_with_it():
    redact = Redactor(names=["ssn"])

    assert redact({"ssn": "1", "customer_ssn": "2", "customerSsn": "3", "ssn_last4": "4"}) == {
        "ssn": "[REDACTED]",
        "customer_ssn": "[REDACTED]",
        "customerSsn": "[REDACTED]",
        "ssn_last4": "4",
    }


def test_a_word_in_names_is_compared_the_same_way_as_a_field_name():
    redact = Redactor(names=["Tax-ID"])

    assert redact({"customer_tax_id": "1", "taxId": "2"}) == {
        "customer_tax_id": "[REDACTED]",
        "taxId": "[REDACTED]",
    }


def test_names_add_to_the_built_in_words():
    assert Redactor(names=["ssn"])({"password": "abc"}) == {"password": "[REDACTED]"}


def test_allow_names_keeps_that_field_visible():
    redact = Redactor(allow_names=["password_length"])

    assert redact({"password_length": 12, "password": "abc"}) == {
        "password_length": 12,
        "password": "[REDACTED]",
    }


def test_allow_names_is_compared_the_same_way_as_a_field_name():
    redact = Redactor(allow_names=["password_length"])

    assert redact({"passwordLength": 12, "PASSWORD-LENGTH": 13}) == {
        "passwordLength": 12,
        "PASSWORD-LENGTH": 13,
    }


def test_allow_names_is_an_exact_name_and_never_changes_the_list_of_words():
    redact = Redactor(allow_names=["token"])

    assert redact({"token": "abc", "access_token": "def"}) == {
        "token": "abc",
        "access_token": "[REDACTED]",
    }


def test_a_detector_still_checks_a_value_under_an_allowed_name():
    redact = Redactor(allow_names=["password_hint"])

    assert redact({"password_hint": "bob@example.com"}) == {"password_hint": "[EMAIL]"}


@pytest.mark.parametrize("option", ["names", "allow_names"])
def test_a_single_word_passed_as_text_and_not_a_list_raises_when_the_redactor_is_made(option):
    with pytest.raises(TypeError, match=option):
        Redactor(**{option: "password"})


@pytest.mark.parametrize("word", ["", "--", " "])
def test_a_word_in_names_with_no_letters_raises_when_the_redactor_is_made(word):
    with pytest.raises(ValueError, match="names"):
        Redactor(names=[word])


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("password=abc", "password=[REDACTED]"),
        ("password = abc", "password = [REDACTED]"),
        ("password: abc", "password: [REDACTED]"),
        ("password:abc", "password:[REDACTED]"),
        ("password := abc", "password := [REDACTED]"),
        ("password => abc", "password => [REDACTED]"),
        ("'password': 'abc'", "'password': '[REDACTED]'"),
        ('"password": "abc"', '"password": "[REDACTED]"'),
        ("password='a b' user=bob", "password='[REDACTED]' user=bob"),
        ('password="a b" user=bob', 'password="[REDACTED]" user=bob'),
        ("{'password': 'a b', 'user': 'bob'}", "{'password': '[REDACTED]', 'user': 'bob'}"),
        ('{"password": "abc", "user": "bob"}', '{"password": "[REDACTED]", "user": "bob"}'),
        ("{b'password': b'abc'}", "{b'password': b'[REDACTED]'}"),
        ("Login(user='bob', password='abc')", "Login(user='bob', password='[REDACTED]')"),
        ("{'password': 1234, 'user': 'bob'}", "{'password': [REDACTED], 'user': 'bob'}"),
        ('{"password":1234,"user":"bob"}', '{"password":[REDACTED],"user":"bob"}'),
    ],
)
def test_a_value_after_a_sensitive_name_in_text_is_hidden_and_the_name_stays(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        (r"{\"password\": \"abc\", \"user\": \"bob\"}", r"{\"password\": \"[REDACTED]\", \"user\": \"bob\"}"),
        (r"{\\\"password\\\": \\\"abc\\\"}", r"{\\\"password\\\": \\\"[REDACTED]\\\"}"),
        (r'"password": "a\"b", "user": "bob"', r'"password": "[REDACTED]", "user": "bob"'),
        (r"\"password\": \"a\\\"b\", \"user\"", r"\"password\": \"[REDACTED]\", \"user\""),
    ],
    ids=["escaped once", "escaped twice", "escaped quote inside", "doubly escaped quote inside"],
)
def test_a_password_in_escaped_json_is_hidden(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("/login?password=abc&page=2", "/login?password=[REDACTED]&page=2"),
        ("password=abc, user=bob", "password=[REDACTED], user=bob"),
        ("password=abc.", "password=[REDACTED]."),
        ("connect(password=abc)", "connect(password=[REDACTED])"),
        ("password=ab,cd next", "password=[REDACTED] next"),
        ("password=it's next", "password=[REDACTED] next"),
        ("Server=db;Password=abc;Port=1", "Server=db;Password=[REDACTED]"),
        ('url="http://db/?password=abc"', 'url="http://db/?password=[REDACTED]"'),
        ("url='http://db/?password=abc'", "url='http://db/?password=[REDACTED]'"),
        (r"url=\"http://db/?password=abc\"", r"url=\"http://db/?password=[REDACTED]\""),
    ],
)
def test_a_value_without_quotes_ends_where_the_surrounding_text_takes_over(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("{'password': {'user': 'bob'}, 'ok': 1}", "{'password': [REDACTED], 'ok': 1}"),
        ('{"credentials": {"a": ["b"]}, "ok": 1}', '{"credentials": [REDACTED], "ok": 1}'),
        ("password=[1, 2] next", "password=[REDACTED] next"),
        ("password=(a b) next", "password=[REDACTED] next"),
        ("password={a [b c", "password=[REDACTED]"),
    ],
)
def test_a_whole_structure_after_a_sensitive_name_in_text_is_hidden(text, cleaned):
    assert Redactor()(text) == cleaned


def test_a_quote_that_is_never_closed_hides_the_rest_of_the_text():
    assert Redactor()("password='abc def") == "password='[REDACTED]"


@pytest.mark.parametrize(
    "text",
    [
        "password=",
        "password: ",
        'password=""',
        "password=&page=2",
        "token_count=5",
        "max_tokens: 10",
        '"token_count": 5',
        "tokens=3",
        "password",
        "my password is long",
        "12:30:00",
        "http://example.com:8080/",
    ],
)
def test_text_with_no_value_under_a_sensitive_name_is_unchanged(text):
    assert Redactor()(text) == text


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("access_token=abc", "access_token=[REDACTED]"),
        ("accessToken: abc", "accessToken: [REDACTED]"),
        ("X-Api-Key: abc", "X-Api-Key: [REDACTED]"),
        ('"X-Api-Key": "abc"', '"X-Api-Key": "[REDACTED]"'),
        ("PASSWORD_HASH=abc", "PASSWORD_HASH=[REDACTED]"),
        ("db.password=abc", "db.password=[REDACTED]"),
    ],
)
def test_a_name_in_text_is_compared_the_same_way_as_a_field_name(text, cleaned):
    assert Redactor()(text) == cleaned


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("note: password=abc", "note: password=[REDACTED]"),
        ("user=password=abc", "user=password=[REDACTED]"),
        ("password=a secret=b", "password=[REDACTED] secret=[REDACTED]"),
        ("password=abc email bob@example.com", "password=[REDACTED] email [EMAIL]"),
    ],
)
def test_every_pair_in_text_is_checked(text, cleaned):
    assert Redactor()(text) == cleaned


def test_a_value_under_a_sensitive_name_that_a_detector_also_finds_is_hidden_by_name():
    assert Redactor()("password=bob@example.com") == "password=[REDACTED]"


@pytest.mark.parametrize(
    "text",
    [
        "password=abc",
        "'password': 'abc'",
        "password=abc, user=bob",
        "Authorization: Bearer abc",
        "password={'a': 1}",
    ],
)
def test_cleaning_text_a_second_time_changes_nothing(text):
    redact = Redactor()

    assert redact(redact(text)) == redact(text)


@pytest.mark.parametrize(
    ("text", "cleaned"),
    [
        ("Authorization: Bearer abc.def", "Authorization: [REDACTED]"),
        ("authorization=Basic dXNlcjpwYXNz", "authorization=[REDACTED]"),
        ("Proxy-Authorization: Basic abc", "Proxy-Authorization: [REDACTED]"),
        ("Authorization: Bearer abc\r\nHost: db", "Authorization: [REDACTED]\r\nHost: db"),
        ("'Authorization': 'Bearer abc', 'Host': 'db'", "'Authorization': '[REDACTED]', 'Host': 'db'"),
        ('"Authorization: Bearer abc"', '"Authorization: [REDACTED]"'),
        (r"\"Authorization\": \"Bearer abc\"", r"\"Authorization\": \"[REDACTED]\""),
    ],
)
def test_both_the_scheme_and_the_credential_of_an_authorization_header_are_hidden(text, cleaned):
    assert Redactor()(text) == cleaned


def test_every_value_in_a_cookie_header_is_hidden():
    assert Redactor()("Cookie: a=1; sid=abc\nHost: db") == "Cookie: [REDACTED]\nHost: db"


def test_a_word_passed_in_names_counts_inside_text():
    assert Redactor(names=["ssn"])("customer_ssn=123 ssn_last4=4") == (
        "customer_ssn=[REDACTED] ssn_last4=4"
    )


@pytest.mark.parametrize(
    "text",
    ["password_length=12", "password_length: 12", "'password_length': 12", '"passwordLength": 12'],
)
def test_allow_names_keeps_a_pair_in_text_visible(text):
    assert Redactor(allow_names=["password_length"])(text) == text


def test_allow_names_for_token_keeps_only_that_exact_name_in_text():
    assert Redactor(allow_names=["token"])("token=abc access_token=def") == (
        "token=abc access_token=[REDACTED]"
    )


def test_a_detector_still_checks_a_pair_under_an_allowed_name():
    assert Redactor(allow_names=["password_hint"])("password_hint=bob@example.com") == (
        "password_hint=[EMAIL]"
    )


def test_an_object_shown_with_a_sensitive_field_has_that_value_hidden():
    @dataclass
    class Login:
        user: str
        password: str

    assert Redactor()(Login("bob", "abc")).endswith("Login(user='bob', password='[REDACTED]')")


def test_a_named_tuple_with_a_sensitive_field_has_that_value_hidden():
    login = namedtuple("Login", ["user", "password"])("bob", "abc")

    assert Redactor()(login) == "Login(user='bob', password='[REDACTED]')"


def test_bytes_holding_a_pair_have_the_value_hidden():
    assert Redactor()(b"password=abc") == "password=[REDACTED]"


def test_a_dictionary_key_holding_a_pair_has_the_value_hidden():
    assert Redactor()({"password=abc": 1}) == {"password=[REDACTED]": 1}
