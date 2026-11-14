from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.jwt_helpers import TEST_PUBLIC_KEY


@pytest.fixture(autouse=True)
def mock_jwks_client():
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=TEST_PUBLIC_KEY)
    with patch("app.core.security.get_jwk_client", return_value=mock_client):
        yield mock_client
