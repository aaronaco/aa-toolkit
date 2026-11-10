# aa-toolkit-redact

Takes sensitive values out of text and data before they leave an app. It uses only Python's standard library, so it has no dependencies.

A `Redactor` finds sensitive values with Detectors and leaves a Placeholder such as `[EMAIL]` where each one was.

## Install

Install it from the toolkit's GitHub repo, pinned to a version tag:

```bash
uv add "aa-toolkit-redact @ git+https://github.com/aaronaco/aa-toolkit@redact-v0.1.0#subdirectory=packages/aa-toolkit-redact"
```

## Use

Create a `Redactor` once and call it with any value:

```python
from aa_redact import Redactor

redact = Redactor()

print(redact("order 4521 for bob.smith@example.com"))
```

That prints:

```text
order 4521 for [EMAIL]
```

A `Redactor` doesn't change after it's created, so every thread can share one.

## What's found

These built-in Detectors are on without any setup:

| Kind | What it finds |
| --- | --- |
| `AWS_ACCESS_KEY` | AWS access key IDs: `AKIA`, `ASIA`, `ABIA` or `ACCA` and at least 16 more capitals or digits. |
| `GITHUB_TOKEN` | GitHub tokens: `ghp_`, `gho_`, `ghu_`, `ghs_` or `ghr_` and at least 36 more characters, or `github_pat_` and at least 22. |
| `API_KEY` | OpenAI-style keys: `sk-` and at least 20 more characters, with a digit or both capitals and small letters, so `sk-learn-…` isn't one. |
| `SLACK_TOKEN` | Slack tokens: `xoxb-`, `xoxp-`, `xoxd-`, `xapp-` and the like, with at least 10 more characters. |
| `JWT` | JSON Web Tokens: three dot-separated parts, the first two starting with `eyJ`. |
| `BEARER_TOKEN` | `Bearer` and the token after it, when the token has at least 8 characters and isn't a plain word. |
| `PRIVATE_KEY` | A private key from its begin line through its end line. A key cut off before its end line is hidden up to where its lines stop. |
| `URL_PASSWORD` | The password in a URL such as `postgres://user:password@host`. The rest of the URL stays. |
| `EMAIL` | Email addresses. |
| `CARD` | Card numbers that start like a real card and pass the Luhn check. They can be one run of digits, or groups of four (or 4, 6 and 5 for American Express) split by spaces, dashes or dots. |

Tokens match on their prefix and a minimum length, so they keep working when a service makes its tokens longer. A long number that starts like a card and passes the check still becomes `[CARD]`. Turn `CARD` off with `without=` if your app's numbers do that.

The `EMAIL` Detector reads at most 64 characters before the `@`, so a longer address keeps its first characters. An address that uses a symbol such as `!`, `&` or `/` before the `@` keeps what comes before the symbol.

```python
from aa_redact import Redactor

redact = Redactor()

print(redact("connect postgres://app:hunter2@db.internal:5432/orders failed"))
print(redact("charged 4111 1111 1111 1111 for order 4521"))
```

That prints:

```text
connect postgres://app:[URL_PASSWORD]@db.internal:5432/orders failed
charged [CARD] for order 4521
```

### IP addresses and phone numbers

`ip_address` and `phone_number` are built in but off, because whether they count as personal data depends on the app. Pass them in `detectors=` to turn them on:

```python
from aa_redact import Redactor, ip_address, phone_number

redact = Redactor(detectors=[ip_address, phone_number])

print(redact("login from 203.0.113.7, callback +1 555 123 4567"))
```

That prints:

```text
login from [IP_ADDRESS], callback [PHONE]
```

`ip_address` finds IPv4 and IPv6 addresses. `phone_number` finds numbers that start with `+` and a country code, numbers with an area code in brackets, like `(555) 123-4567`, and numbers written in groups, like `555-123-4567` or `020 7946 0958`. A run of digits with no `+`, brackets or groups isn't found, because it can't be told apart from an order number.

## Clean nested values

A `Redactor` gives back the same shape it was given:

```python
from aa_redact import Redactor

redact = Redactor()

print(redact({"to": ["bob@example.com"], "qty": 2}))
```

That prints:

```text
{'to': ['[EMAIL]'], 'qty': 2}
```

| Value | What comes back |
| --- | --- |
| Text | Text with Placeholders in it. |
| Dictionary, list, tuple or set | The same shape with every value cleaned, at any depth. Dictionary keys are cleaned too, and two keys that clean to the same text become one. A named tuple stays that named tuple, with its field names checked. Other subclasses come back as the plain type. |
| Number | The same number, or a Placeholder when a Detector matches it. |
| `None`, `True` or `False` | The same value. |
| Bytes | Text, decoded as UTF-8 and cleaned. |
| Any other object | The text it would be shown as, cleaned. An object that can't be turned into text becomes a note such as `[UNPRINTABLE Customer]`. |
| A structure that contains itself, or is nested more than 32 levels deep | `[REDACTED]` in place of that part. |

## Hide values by field name

A value under a Sensitive name is hidden whatever it looks like. The same rule applies to `name=value` pairs inside text:

```python
from aa_redact import Redactor

redact = Redactor()

print(redact({"access_token": "abc123", "token_count": 5}))
print(redact("login password=abc123 page=2"))
```

That prints:

```text
{'access_token': '[REDACTED]', 'token_count': 5}
login password=[REDACTED] page=2
```

Names are compared after lower-casing them and treating dashes, underscores and camelCase as word breaks, so `X-Api-Key`, `x_api_key` and `xApiKey` are the same name.

- `password`, `passwd`, `secret` and `credential` match anywhere in the name, so `passwords` and `secret_key` are hidden, and so are harmless names like `secretary`.
- `token`, `api_key`, `apikey`, `access_key`, `private_key`, `authorization`, `cookie`, `pwd` and `passphrase` match when they are the last words of the name, so `access_token` is hidden and `token_count` isn't.

A dictionary or list under a Sensitive name is hidden as a whole. `None` and booleans stay, because they hold no secret.

Inside text, the pair can be written `name=value`, `name: value`, with quotes, as Python prints a dictionary, or as escaped JSON. A name in quotes can hold spaces, like `"API Key"`. The name stays and the value becomes `[REDACTED]`. A value in brackets, or written as a call like `Secret('abc')`, is hidden up to its closing bracket. A value without quotes runs to the next space, `"` or `&`, and a value after `authorization` or `cookie` runs to the end of the line. So `Server=db;Password=abc;Port=1` hides the port as well.

Pass `names=` to add words, which match as the last words of a name. Pass `allow_names=` to keep exact field names visible, both as fields and inside text. It never changes the words, so allowing `token` leaves `access_token` hidden. A value under an allowed name still goes through the Detectors.

```python
from aa_redact import Redactor

redact = Redactor(names=["ssn"], allow_names=["password_length"])

print(redact({"customer_ssn": "123", "password_length": 12, "password": "abc"}))
```

That prints:

```text
{'customer_ssn': '[REDACTED]', 'password_length': 12, 'password': '[REDACTED]'}
```

## Add your own Detector

`pattern(kind, regex)` makes a Detector from a regular expression. Pass it in `detectors=`. Your Detectors are added to the built-in ones, so adding one never turns another off.

```python
from aa_redact import Redactor, pattern

redact = Redactor(detectors=[pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b")])

print(redact("tax id 123-456-789 for bob@example.com"))
```

That prints:

```text
tax id [TAX_ID] for [EMAIL]
```

A regex that isn't valid raises when `pattern()` is called, not later when text is checked.

A Detector can also be a plain function. It takes the text and returns a `Finding(kind, start, end)` for each value it found, where `text[start:end]` is the value:

```python
from aa_redact import Finding, Redactor


def order_numbers(text: str) -> list[Finding]:
    start = text.find("A-")
    return [Finding("ORDER", start, start + 6)] if start >= 0 else []


redact = Redactor(detectors=[order_numbers])

print(redact("order A-4521 shipped"))
```

That prints:

```text
order [ORDER] shipped
```

When a Detector raises an error, the error comes out of the `Redactor`. So does a `ValueError` when a `Finding` doesn't fit the text.

When Findings overlap, they become one Placeholder. The longest Finding gives the kind. When two are the same length, the earlier Detector wins: the built-in ones come first, then yours in the order you passed them.

## Hide Known values

`known_values(kind, values)` makes a Detector for the exact secrets your app already holds, such as a database password or a key with no prefix. Each Known value is hidden when it appears as written, URL-encoded or JSON-escaped. Empty values are ignored, so an unset setting can be passed safely, and when one Known value is contained in a longer one, the longer one is matched first.

```python
from aa_redact import Redactor, known_values

redact = Redactor(detectors=[known_values("DB_PASSWORD", ["p@ss/w0rd", ""])])

print(redact("dsn=https://db.internal/?pw=p%40ss%2Fw0rd"))
```

That prints:

```text
dsn=https://db.internal/?pw=[DB_PASSWORD]
```

## Turn off a built-in Detector

Pass a list of kinds in `without=`. Every other Detector still runs, and so do the ones you added.

```python
from aa_redact import Redactor

redact = Redactor(without=["EMAIL"])

print(redact("order 4521 for bob.smith@example.com"))
```

That prints:

```text
order 4521 for bob.smith@example.com
```

## Size limit

Text longer than `max_length`, 64 KB (`65536` characters) by default per value, is cut at the limit and ends with `[TRUNCATED]`. Detectors run on the limit plus a 16 KB margin—big enough for a whole private key—so a value that sits across the cut is still found and no part of it comes back. Text past the cut is never returned.

Pass `max_length=` to set a different limit:

```python
from aa_redact import Redactor

redact = Redactor(max_length=12)

print(redact("user: bob.smith@example.com and more"))
```

That prints:

```text
user: [EMAIL][TRUNCATED]
```

## What this library can't do

Redaction is a safety net, not a guarantee. The better fix is not logging secrets at all.

- **Values with no recognizable pattern aren't found.** Patterns can't find a person's name, a street address, or an AWS secret access key, which is 40 random base64 characters with no prefix. Pass secrets your app already holds to `known_values()`, or keep them under Sensitive names.
- **Base64-encoded forms of Known values aren't found.** `known_values()` checks each value as written, URL-encoded and JSON-escaped.
- **A very slow custom pattern can stall logging.** Every built-in pattern has bounded repeats so hostile input stays fast, and `max_length` caps how much text is checked, but Python's `re` has no timeout. Write custom patterns in `pattern()` with bounded repeats and no nested `+` or `*`.
- **Log handlers an app adds itself aren't covered.** When used with [`aa-toolkit-log`](../aa-toolkit-log/README.md), `configure_logging(redact=...)` cleans only the handlers it installs.
