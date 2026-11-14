from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()


def make_test_jwt(tenant_id: str, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid4()),
        "tenant_id": tenant_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, TEST_PRIVATE_KEY, algorithm="RS256", headers={"kid": "test-key"})


def make_auth_headers(tenant_id: str = "00000000-0000-0000-0000-000000000001") -> dict[str, str]:
    return {"Authorization": f"Bearer {make_test_jwt(tenant_id)}"}
