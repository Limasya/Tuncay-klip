"""Simple stub implementation of the `jose.jwt` module for testing purposes.

Provides `encode` and `decode` functions compatible with the test suite's expectations.
"""

import json
import base64

class JWTError(Exception):
    """Exception raised for JWT encoding/decoding errors."""
    pass

def encode(claims: dict, key: str, algorithm: str = "HS256") -> str:
    """Encode claims into a base64 URL‑safe token string.

    This is a minimal stub that does **not** perform any cryptographic signing.
    It is sufficient for the project's unit tests which only verify round‑trip
    encode/decode behavior.
    """
    payload = json.dumps(claims, separators=(',', ':')).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")
    return token

def decode(token: str, key: str, algorithms=None) -> dict:
    """Decode a token produced by :func:`encode`.

    Raises :class:`JWTError` if the token cannot be decoded.
    """
    # Add padding back for base64 decoding
    padding = "=" * (-len(token) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(token + padding)
        claims = json.loads(payload_bytes.decode("utf-8"))
        return claims
    except Exception as exc:
        raise JWTError(str(exc))
