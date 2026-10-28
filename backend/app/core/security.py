import datetime as dt
import hmac
import time
from collections import defaultdict, deque

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.policies.engine import has_permission

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str) -> str:
    s = get_settings()
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=s.jwt_ttl_minutes)
    return jwt.encode({"sub": username, "role": role, "exp": exp}, s.jwt_secret, algorithm="HS256")


class Actor:
    def __init__(self, username: str, role: str):
        self.username, self.role = username, role


def current_actor(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        data = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
        return Actor(data["sub"], data["role"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None


def require(operation: str):
    def dep(actor: Actor = Depends(current_actor)) -> Actor:
        if not has_permission(actor.role, operation):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not permitted to perform this operation")
        return actor
    return dep


def automation_auth(x_trustlayer_automation_key: str | None = Header(default=None)) -> str:
    secret = get_settings().n8n_shared_secret
    if not secret or not x_trustlayer_automation_key or not hmac.compare_digest(x_trustlayer_automation_key, secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid automation credentials")
    return "n8n-automation"


class RateLimiter:
    """Small in-memory sliding-window limiter (single-process prototype)."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; please slow down")
        q.append(now)


limiter = RateLimiter()
