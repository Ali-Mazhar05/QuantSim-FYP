"""Password hashing with Argon2id (NFR-SEC-004): salted, one-way, memory-hard.

Verifying against an unknown username still runs one full hash, so response time does
not reveal which usernames exist.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP-recommended Argon2id profile: 19 MiB, 2 iterations, 1 lane
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
_DUMMY_HASH = _hasher.hash("not-a-real-password-used-to-equalise-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True when ``password`` matches; also spends the same time when there is no user."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash uses weaker parameters than today's; rehash on next login."""
    return _hasher.check_needs_rehash(stored_hash)
