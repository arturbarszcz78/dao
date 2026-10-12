import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def blocks() -> dict:
    return json.loads((FIXTURES / "blocks.json").read_text())


@pytest.fixture(scope="session")
def statechain() -> dict:
    return json.loads((FIXTURES / "statechain.json").read_text())


NETWORK_ID = "testnet-0005"
