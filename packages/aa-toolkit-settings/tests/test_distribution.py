"""The installed distribution that provides the aa_settings import."""

from importlib.metadata import distribution
from pathlib import Path

import aa_settings


def test_the_package_is_aa_toolkit_settings_at_version_0_1_0():
    dist = distribution("aa-toolkit-settings")

    assert dist.name == "aa-toolkit-settings"
    assert dist.version == "0.1.0"


def test_the_package_depends_only_on_pydantic_settings_and_keyring():
    assert sorted(distribution("aa-toolkit-settings").requires or []) == [
        "keyring>=25.7.0",
        "pydantic-settings>=2.16.2",
    ]


def test_aa_settings_imports_from_the_package_folder(package_dir):
    assert Path(aa_settings.__file__).resolve().parent == package_dir / "src" / "aa_settings"


def test_the_public_names_are_the_settings_types_and_helpers():
    assert sorted(aa_settings.__all__) == [
        "BaseSettings",
        "Secret",
        "SecretStoreError",
        "SettingsConfigDict",
        "SettingsError",
        "delete_secret",
        "save_secret",
        "secret_values",
    ]


def test_the_package_tells_type_checkers_it_is_typed(package_dir):
    assert (package_dir / "src" / "aa_settings" / "py.typed").is_file()
