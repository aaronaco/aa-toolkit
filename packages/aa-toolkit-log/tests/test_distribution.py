"""The installed distribution that provides the aa_log import."""

from importlib.metadata import distribution
from pathlib import Path

import aa_log


def test_the_package_is_aa_toolkit_log_at_version_0_1_0():
    dist = distribution("aa-toolkit-log")

    assert dist.name == "aa-toolkit-log"
    assert dist.version == "0.1.0"


def test_the_package_has_no_dependencies():
    assert not distribution("aa-toolkit-log").requires


def test_aa_log_imports_from_the_package_folder(package_dir):
    assert Path(aa_log.__file__).resolve().parent == package_dir / "src" / "aa_log"
