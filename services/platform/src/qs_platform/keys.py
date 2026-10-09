"""The key that signs access tokens and the public key set other services verify with.

Rotation: generate a new key, move the old key's public JWK into
``QS_RETIRED_PUBLIC_KEYS``, and deploy with the new ``QS_SIGNING_KEY`` and
``QS_SIGNING_KEY_ID``. Tokens signed by the old key keep verifying until they expire;
services fetch the new key automatically when they first see its id.
"""

import base64
import json
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ALGORITHM = "RS256"
MIN_KEY_BITS = 2048


class SigningKeys:
    def __init__(
        self, private_key_pem: bytes, key_id: str, retired_public_keys: str | None = None
    ) -> None:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < MIN_KEY_BITS:
            raise ValueError(f"the signing key must be an RSA key of at least {MIN_KEY_BITS} bits")
        self._private_key = key
        self.key_id = key_id
        self._retired: list[dict[str, Any]] = []
        if retired_public_keys:
            document = json.loads(retired_public_keys)
            self._retired = [k for k in document.get("keys", []) if k.get("kid") != key_id]

    def sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(
            claims, self._private_key, algorithm=ALGORITHM, headers={"kid": self.key_id}
        )

    def jwks(self) -> dict[str, Any]:
        """Public keys only: the current one first, then retired ones."""
        current: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self._private_key.public_key()))
        current.update({"kid": self.key_id, "alg": ALGORITHM, "use": "sig"})
        return {"keys": [current, *self._retired]}


def generate_signing_key(bits: int = 3072) -> str:
    """A new RSA private key as base64-encoded PEM, ready for ``QS_SIGNING_KEY``."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode()
