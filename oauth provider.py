"""
Minimaler OAuth-2.1-Authorization-Server, eingebettet im MCP-Server selbst.

Speichert Clients/Codes/Tokens jetzt PERSISTENT via Upstash Redis (storage.py),
statt nur im Prozess-RAM. Damit ueberlebt eine bestehende Verbindung Render-
Neustarts (Cold-Start, Redeploy) - Claude muss den Connector nicht mehr staendig
neu verbinden, genau wie bei "richtigen" Connectors (z.B. Strava).

Falls UPSTASH_REDIS_REST_URL/TOKEN nicht gesetzt sind, faellt der Provider auf
In-Memory-Speicherung zurueck (funktioniert lokal zum Testen, aber Sessions
gehen bei jedem Neustart verloren - siehe README).
"""

from __future__ import annotations

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

import storage

ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 Tage
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365  # 1 Jahr
AUTH_CODE_TTL_SECONDS = 5 * 60  # 5 Minuten zum Login
PENDING_TTL_SECONDS = 10 * 60  # 10 Minuten Zeit zum Login, bevor die Anfrage verfaellt

# In-Memory-Fallback (nur falls Upstash nicht konfiguriert ist - siehe README)
_mem_clients: dict[str, dict] = {}
_mem_pending: dict[str, dict] = {}
_mem_auth_codes: dict[str, dict] = {}
_mem_access_tokens: dict[str, dict] = {}
_mem_refresh_tokens: dict[str, dict] = {}


async def _kv_set(mem: dict, prefix: str, key: str, value: dict, ttl: int | None = None) -> None:
    if storage.is_configured():
        await storage.set_json(f"{prefix}:{key}", value, ttl_seconds=ttl)
    else:
        mem[key] = value


async def _kv_get(mem: dict, prefix: str, key: str) -> dict | None:
    if storage.is_configured():
        return await storage.get_json(f"{prefix}:{key}")
    return mem.get(key)


async def _kv_delete(mem: dict, prefix: str, key: str) -> None:
    if storage.is_configured():
        await storage.delete(f"{prefix}:{key}")
    else:
        mem.pop(key, None)


class GarminAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(self, issuer_url: str, password: str):
        self.issuer_url = issuer_url.rstrip("/")
        self.password = password

    # --- Client-Registrierung (Dynamic Client Registration) ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = await _kv_get(_mem_clients, "client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await _kv_set(_mem_clients, "client", client_info.client_id, client_info.model_dump(mode="json"))

    # --- Authorization-Code-Flow ---

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(24)
        data = {"client_id": client.client_id, "params": params.model_dump(mode="json")}
        await _kv_set(_mem_pending, "pending", request_id, data, ttl=PENDING_TTL_SECONDS)
        return f"{self.issuer_url}/login?request_id={request_id}"

    async def get_pending(self, request_id: str) -> tuple[str, AuthorizationParams] | None:
        data = await _kv_get(_mem_pending, "pending", request_id)
        if data is None:
            return None
        return data["client_id"], AuthorizationParams.model_validate(data["params"])

    async def complete_login(self, request_id: str) -> str:
        """Wird von der /login-POST-Route in server.py aufgerufen, NACHDEM das
        Passwort erfolgreich geprueft wurde. Erzeugt den Authorization Code und
        gibt die fertige Redirect-URL zurueck."""
        pending = await self.get_pending(request_id)
        if pending is None:
            raise ValueError("Unbekannte oder abgelaufene request_id.")
        client_id, params = pending
        await _kv_delete(_mem_pending, "pending", request_id)

        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["garmin"],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        await _kv_set(_mem_auth_codes, "authcode", code, auth_code.model_dump(mode="json"), ttl=AUTH_CODE_TTL_SECONDS)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        data = await _kv_get(_mem_auth_codes, "authcode", authorization_code)
        if data is None:
            return None
        code = AuthorizationCode.model_validate(data)
        if code.client_id != client.client_id or code.expires_at < time.time():
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        await _kv_delete(_mem_auth_codes, "authcode", authorization_code.code)

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        expires_at = int(time.time() + ACCESS_TOKEN_TTL_SECONDS)

        access_obj = AccessToken(
            token=access_token, client_id=client.client_id, scopes=authorization_code.scopes,
            expires_at=expires_at, resource=authorization_code.resource,
        )
        refresh_obj = RefreshToken(token=refresh_token, client_id=client.client_id, scopes=authorization_code.scopes)

        await _kv_set(_mem_access_tokens, "access", access_token, access_obj.model_dump(mode="json"), ttl=ACCESS_TOKEN_TTL_SECONDS)
        await _kv_set(_mem_refresh_tokens, "refresh", refresh_token, refresh_obj.model_dump(mode="json"), ttl=REFRESH_TOKEN_TTL_SECONDS)

        return OAuthToken(
            access_token=access_token, token_type="bearer", expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token, scope=" ".join(authorization_code.scopes),
        )

    # --- Refresh-Token-Flow ---

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        data = await _kv_get(_mem_refresh_tokens, "refresh", refresh_token)
        if data is None:
            return None
        token = RefreshToken.model_validate(data)
        if token.client_id != client.client_id:
            return None
        return token

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str],
    ) -> OAuthToken:
        await _kv_delete(_mem_refresh_tokens, "refresh", refresh_token.token)

        granted_scopes = scopes or refresh_token.scopes
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time() + ACCESS_TOKEN_TTL_SECONDS)

        access_obj = AccessToken(token=new_access, client_id=client.client_id, scopes=granted_scopes, expires_at=expires_at)
        refresh_obj = RefreshToken(token=new_refresh, client_id=client.client_id, scopes=granted_scopes)

        await _kv_set(_mem_access_tokens, "access", new_access, access_obj.model_dump(mode="json"), ttl=ACCESS_TOKEN_TTL_SECONDS)
        await _kv_set(_mem_refresh_tokens, "refresh", new_refresh, refresh_obj.model_dump(mode="json"), ttl=REFRESH_TOKEN_TTL_SECONDS)

        return OAuthToken(
            access_token=new_access, token_type="bearer", expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=new_refresh, scope=" ".join(granted_scopes),
        )

    # --- Access-Token-Verifikation ---

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = await _kv_get(_mem_access_tokens, "access", token)
        if data is None:
            return None
        access_token = AccessToken.model_validate(data)
        if access_token.expires_at is not None and access_token.expires_at < time.time():
            await _kv_delete(_mem_access_tokens, "access", token)
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await _kv_delete(_mem_access_tokens, "access", token.token)
        await _kv_delete(_mem_refresh_tokens, "refresh", token.token)
