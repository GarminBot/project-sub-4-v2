"""
Persistenter Key-Value-Store fuer OAuth-Clients/Codes/Tokens, ueber die
Upstash-Redis-REST-API (kein Socket noetig, passt gut zu Render + async).

Ohne persistente Speicherung wuerden alle Tokens beim Neustart des Render-
Prozesses verloren gehen (RAM wird geleert) -> Claude muesste den Connector
jedes Mal neu verbinden. Mit Upstash ueberlebt der Zustand Neustarts.

Benoetigt zwei Env-Variablen (von upstash.com, kostenloser Tier):
  UPSTASH_REDIS_REST_URL
  UPSTASH_REDIS_REST_TOKEN
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

_BASE_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


def is_configured() -> bool:
    return bool(_BASE_URL and _TOKEN)


_client: httpx.AsyncClient | None = (
    httpx.AsyncClient(base_url=_BASE_URL, headers={"Authorization": f"Bearer {_TOKEN}"}, timeout=10.0)
    if is_configured()
    else None
)


def _require_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Upstash ist nicht konfiguriert (UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN fehlen).")
    return _client


async def set_json(key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
    client = _require_client()
    payload = json.dumps(value)
    command = ["SET", key, payload]
    if ttl_seconds:
        command += ["EX", str(ttl_seconds)]
    resp = await client.post("/", content=json.dumps(command))
    resp.raise_for_status()


async def get_json(key: str) -> dict[str, Any] | None:
    client = _require_client()
    resp = await client.post("/", content=json.dumps(["GET", key]))
    resp.raise_for_status()
    result = resp.json().get("result")
    if result is None:
        return None
    return json.loads(result)


async def delete(key: str) -> None:
    client = _require_client()
    resp = await client.post("/", content=json.dumps(["DEL", key]))
    resp.raise_for_status()
