from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


class InvalidImpressionToken(ValueError):
    pass


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_impression_token(
    *,
    secret: bytes,
    model_version: str,
    item_ids: list[str],
    ttl_seconds: int = 1800,
    now: int | None = None,
) -> str:
    if len(secret) < 32:
        raise ValueError("impression signing secret must be at least 32 bytes")
    if not 1 <= ttl_seconds <= 3600 or not item_ids:
        raise ValueError("impression token requires items and a TTL from 1 to 3600 seconds")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "session_id": secrets.token_urlsafe(18),
        "model_version": model_version,
        "item_ids": list(dict.fromkeys(item_ids)),
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_impression_token(
    token: str,
    *,
    secret: bytes,
    item_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    try:
        encoded, signed = token.split(".", maxsplit=1)
        expected = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signed)):
            raise InvalidImpressionToken("invalid impression signature")
        payload = json.loads(_decode(encoded))
        current_time = int(time.time() if now is None else now)
        if payload["iat"] > current_time + 30 or payload["exp"] < current_time:
            raise InvalidImpressionToken("impression token is expired or not yet valid")
        if item_id not in payload["item_ids"]:
            raise InvalidImpressionToken("item is not part of this impression")
        if not payload["session_id"] or not payload["model_version"]:
            raise InvalidImpressionToken("impression token is incomplete")
        return payload
    except InvalidImpressionToken:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidImpressionToken("malformed impression token") from exc
