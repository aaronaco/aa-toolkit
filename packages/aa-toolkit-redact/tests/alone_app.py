"""A small app that CI runs with only the redaction library installed."""

from importlib.metadata import distributions

from aa_redact import Finding, Redactor, pattern

installed = sorted(dist.name for dist in distributions())
assert installed == ["aa-toolkit-redact"], installed


def order_numbers(text: str) -> list[Finding]:
    start = text.find("A-1")
    return [Finding("ORDER", start, start + 3)] if start >= 0 else []


redact = Redactor(detectors=[pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b"), order_numbers])
cleaned = redact("order A-1, tax id 123-456-789, for bob@example.com")
assert cleaned == "order [ORDER], tax id [TAX_ID], for [EMAIL]", cleaned
print("ok")
