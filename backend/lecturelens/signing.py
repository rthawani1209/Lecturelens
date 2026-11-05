"""Short-lived signed URLs: the server can check a link without a session or a lookup."""

import hashlib
import hmac
import time

from .config import get_settings


def _mac(value: str, exp: int) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{value}:{exp}".encode(), hashlib.sha256).hexdigest()


def sign(value: str, ttl_s: int) -> tuple[int, str]:
    exp = int(time.time()) + ttl_s
    return exp, _mac(value, exp)


# nothing we sign lives longer than a day, so a later expiry is a forgery
MAX_TTL_S = 24 * 3600


def verify(value: str, exp: int, sig: str) -> bool:
    now = time.time()
    return now < exp <= now + MAX_TTL_S and hmac.compare_digest(_mac(value, exp), sig)
