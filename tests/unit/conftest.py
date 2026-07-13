import copy
from pathlib import Path

import pytest
import yaml

from fwos_core.schema import load_schema

REPO = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO / "config" / "example-config.yaml"


@pytest.fixture(scope="session")
def schema():
    return load_schema(REPO / "config" / "schema.json")


@pytest.fixture(scope="session")
def example_text():
    return EXAMPLE_CONFIG.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def _example_doc(example_text):
    return yaml.safe_load(example_text)


@pytest.fixture
def example_doc(_example_doc):
    """Fresh mutable copy of the example config document per test."""
    return copy.deepcopy(_example_doc)
