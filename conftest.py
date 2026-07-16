import json
import base64
import os
import sys
import types

os.environ.setdefault("AUTH_DISABLED", "1")


# ---------------------------------------------------------------------------
# Minimal jose stub for tests — only injected when real python-jose is absent.
# ---------------------------------------------------------------------------
if "jose" not in sys.modules:
    _jose = types.ModuleType("jose")
    _jwt = types.ModuleType("jose.jwt")

    class JWTError(Exception):
        pass

    def _encode(claims, key, algorithm="HS256"):
        payload = json.dumps(claims, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    def _decode(token, key, algorithms=None):
        padding = "=" * (-len(token) % 4)
        try:
            return json.loads(base64.urlsafe_b64decode(token + padding))
        except Exception as exc:
            raise JWTError(str(exc)) from exc

    _jwt.encode = _encode
    _jwt.decode = _decode
    _jwt.JWTError = JWTError

    _jose.jwt = _jwt
    _jose.JWTError = JWTError

    sys.modules["jose"] = _jose
    sys.modules["jose.jwt"] = _jwt
