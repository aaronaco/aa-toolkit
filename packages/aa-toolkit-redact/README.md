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

This version has one built-in Detector, `EMAIL`. It reads at most 64 characters before the `@`, so a longer address keeps its first characters. An address that uses a symbol such as `!`, `&` or `/` before the `@` keeps what comes before the symbol.

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
