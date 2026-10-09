import base64
import json

import jwt
import pytest
from pydantic import ValidationError

from qs_platform.keys import SigningKeys, generate_signing_key
from qs_platform.passwords import hash_password, needs_rehash, verify_password
from tests.conftest import SIGNING_KEY, make_settings


def keys(**kwargs: str) -> SigningKeys:
    return SigningKeys(base64.b64decode(SIGNING_KEY), "key-1", **kwargs)


def test_passwords_are_salted_one_way_hashes() -> None:
    first, second = hash_password("correct horse"), hash_password("correct horse")

    assert first != second
    assert first.startswith("$argon2id$")
    assert "correct horse" not in first


def test_password_verification() -> None:
    stored = hash_password("correct horse")

    assert verify_password(stored, "correct horse") is True
    assert verify_password(stored, "Correct horse") is False
    assert verify_password(None, "anything") is False
    assert verify_password("not-a-hash", "anything") is False


def test_current_hashes_do_not_need_rehashing() -> None:
    assert needs_rehash(hash_password("x")) is False


def test_tokens_verify_against_the_published_key_set() -> None:
    signer = keys()
    token = signer.sign({"sub": "u1", "aud": "quantsim"})

    public = jwt.PyJWK(signer.jwks()["keys"][0])
    claims = jwt.decode(token, public.key, algorithms=["RS256"], audience="quantsim")

    assert claims["sub"] == "u1"
    assert jwt.get_unverified_header(token)["kid"] == "key-1"


def test_published_key_set_holds_no_private_material() -> None:
    entry = keys().jwks()["keys"][0]

    assert {"d", "p", "q", "dp", "dq", "qi"}.isdisjoint(entry)
    assert entry["kid"] == "key-1"
    assert entry["use"] == "sig"


def test_retired_keys_stay_published_for_rotation() -> None:
    old = SigningKeys(base64.b64decode(generate_signing_key(2048)), "key-0")
    signer = keys(retired_public_keys=json.dumps(old.jwks()))

    assert [k["kid"] for k in signer.jwks()["keys"]] == ["key-1", "key-0"]


def test_rejects_weak_signing_keys() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    with pytest.raises(ValueError, match="2048"):
        SigningKeys(weak, "weak")


def test_settings_reject_a_signing_key_that_is_not_base64_pem() -> None:
    from pydantic import SecretStr

    with pytest.raises(ValidationError, match="base64"):
        make_settings(signing_key=SecretStr("not base64!"))
    with pytest.raises(ValidationError, match="PEM private key"):
        make_settings(signing_key=SecretStr(base64.b64encode(b"hello").decode()))
