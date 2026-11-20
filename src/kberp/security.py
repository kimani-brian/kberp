"""Password hashing, session tokens and constant-time comparison.

Everything in this module is security-critical and deliberately small: Argon2id
for passwords, `secrets` for tokens, and `hmac.compare_digest` for every value
whose timing could otherwise leak. The security *audit* lives in
`kberp.security_audit` so importing this module stays cheap.
"""

from __future__ import annotations

import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with the library defaults: 64 MiB memory, 3 iterations, 1 lane.
# The defaults track OWASP guidance and are re-evaluated on dependency bumps.
_hasher = PasswordHasher()

# A fixed hash used only to spend the same work when a user does not exist.
_DUMMY_HASH = _hasher.hash("kberp-timing-equaliser")

SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 24


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Compare a password with a stored hash, in constant-ish time.

    A missing hash still runs a verification against a dummy value so an
    unknown user and a wrong password cost roughly the same. Any malformed or
    unsupported hash is treated as a failed login rather than an error.
    """
    if not stored_hash:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_session_token() -> str:
    """A URL-safe, unguessable session identifier."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def new_csrf_token() -> str:
    """A URL-safe CSRF token, independent of the session token."""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two strings without leaking their common prefix."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
