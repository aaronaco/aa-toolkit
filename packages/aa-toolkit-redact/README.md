# aa-toolkit-redact

Takes sensitive values out of text before they leave an app. It uses only Python's standard library, so it has no dependencies.

A `Redactor` finds sensitive values with Detectors and leaves a Placeholder such as `[EMAIL]` where each one was.

## Install

Install it from the toolkit's GitHub repo, pinned to a version tag:

```bash
uv add "aa-toolkit-redact @ git+https://github.com/aaronaco/aa-toolkit@redact-v0.1.0#subdirectory=packages/aa-toolkit-redact"
```

## Use

Create a `Redactor` once and call it with text:

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

This version has one built-in Detector, `EMAIL`. It reads at most 64 characters before the `@`, so a longer address keeps its first characters.

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
