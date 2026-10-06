"""Redis, behind the Cache port.

The only method worth reading is :meth:`add`, which is ``SET NX PX``. That one
call is the difference between two agents writing one record and one agent
writing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .probe import Probe
from .probe import probe as probe_target


@dataclass
class RedisCache:
    url: str = "redis://127.0.0.1:6379/0"
    _client: object = field(default=None, repr=False)

    def client(self):
        if self._client is None:
            import redis  # noqa: PLC0415 — optional extra

            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is None:
            self.client().set(key, value)
        else:
            self.client().set(key, value, ex=ttl_seconds)

    def get(self, key: str) -> str | None:
        return self.client().get(key)

    def add(self, key: str, value: str, ttl_seconds: int | None = None) -> bool:
        """SET NX. False means someone else holds it — this is the lock."""
        got = self.client().set(key, value, nx=True, ex=ttl_seconds)
        return bool(got)

    def delete(self, key: str) -> None:
        self.client().delete(key)

    def probe(self) -> Probe:
        """Why, not just whether - a missing `redis` package is not a down Redis."""
        return probe_target(self.url, lambda: bool(self.client().ping()), requires="redis")

    def ping(self) -> bool:
        return bool(self.probe())
