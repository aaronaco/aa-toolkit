from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def package_dir() -> Path:
    """The aa-toolkit-redact package folder in this checkout."""
    return PACKAGE_DIR


@pytest.fixture
def repo(package_dir: Path) -> Path:
    """The toolkit's repo folder in this checkout."""
    return package_dir.parents[1]
