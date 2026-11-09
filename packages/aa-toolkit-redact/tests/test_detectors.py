"""An app adding its own Detectors and turning a built-in one off."""

import pytest

from aa_redact import Finding, Redactor, pattern


def test_a_pattern_detector_is_added_to_the_built_in_ones():
    redact = Redactor(detectors=[pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b")])

    assert redact("tax id 123-456-789 for bob@example.com") == "tax id [TAX_ID] for [EMAIL]"


def test_a_plain_function_is_a_detector_and_each_finding_gets_a_placeholder_for_its_kind():
    def order_and_customer(text):
        return [
            Finding("ORDER", text.index("A-1"), text.index("A-1") + 3),
            Finding("CUSTOMER", text.index("C-22"), text.index("C-22") + 4),
        ]

    redact = Redactor(detectors=[order_and_customer])

    assert redact("order A-1 by C-22 shipped") == "order [ORDER] by [CUSTOMER] shipped"


def test_a_detector_can_be_a_generator_and_report_findings_in_any_order():
    def backwards(text):
        yield Finding("LAST", len(text) - 1, len(text))
        yield Finding("FIRST", 0, 1)

    assert Redactor(detectors=[backwards])("a-b-c") == "[FIRST]-b-[LAST]"


def test_without_turns_off_one_built_in_detector_and_the_others_still_run():
    redact = Redactor(without=["EMAIL"], detectors=[pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b")])

    assert redact("tax id 123-456-789 for bob@example.com") == "tax id [TAX_ID] for bob@example.com"


def test_without_leaves_a_detector_the_app_added_under_the_same_kind_running():
    redact = Redactor(without=["EMAIL"], detectors=[pattern("EMAIL", r"\S+@corp\.example")])

    assert redact("bob@example.com and amy@corp.example") == "bob@example.com and [EMAIL]"


def test_a_kind_that_is_not_built_in_turns_nothing_off():
    assert Redactor(without=["TAX_ID"])("bob@example.com") == "[EMAIL]"


def test_a_redactor_does_not_change_when_the_lists_it_was_given_change():
    detectors = [pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b")]
    without = ["EMAIL"]
    redact = Redactor(detectors=detectors, without=without)

    detectors.clear()
    without.clear()

    assert redact("tax id 123-456-789 for bob@example.com") == "tax id [TAX_ID] for bob@example.com"


def test_a_redactor_has_no_settings_to_change_after_it_is_created():
    redact = Redactor()

    with pytest.raises(AttributeError):
        redact.detectors = []  # ty: ignore[unresolved-attribute]

    assert redact("bob@example.com") == "[EMAIL]"


def test_a_finding_cannot_be_changed():
    finding = Finding("EMAIL", 0, 3)

    with pytest.raises(AttributeError):
        finding.kind = "OTHER"  # ty: ignore[invalid-assignment]
