"""The installed distribution that provides the aa_redact import."""

from importlib.metadata import distribution
from pathlib import Path

import aa_redact


def test_the_package_is_aa_toolkit_redact_at_version_0_1_0():
    dist = distribution("aa-toolkit-redact")

    assert dist.name == "aa-toolkit-redact"
    assert dist.version == "0.1.0"


def test_the_package_has_no_dependencies():
    assert not distribution("aa-toolkit-redact").requires


def test_aa_redact_imports_from_the_package_folder(package_dir):
    assert Path(aa_redact.__file__).resolve().parent == package_dir / "src" / "aa_redact"


def test_the_public_interface_is_the_redactor_the_finding_the_helpers_and_the_off_detectors():
    assert sorted(aa_redact.__all__) == [
        "Finding",
        "Redactor",
        "ip_address",
        "known_values",
        "pattern",
        "phone_number",
    ]


def test_the_package_tells_type_checkers_it_is_typed(package_dir):
    assert (package_dir / "src" / "aa_redact" / "py.typed").is_file()
