"""
Minimaler OAuth-2.1-Authorization-Server, eingebettet im MCP-Server selbst.

Diese Version ist fuer einen persoenlichen Claude-Connector optimiert:
- Optional ohne Passwortabfrage: MCP_AUTO_APPROVE=true
- OAuth-Clients und Tokens werden in eine JSON-Datei geschrieben, damit Claude
  nach einem App-Neustart nicht sofort neu verbunden werden muss.

Wichtig: Auf Render Free kann der Dienst trotzdem einschlafen oder neu gestartet
werden. Damit die Verbindung wirklich stabil bleibt, braucht es entweder einen
Always-on/paid Render Service oder einen externen Uptime-Ping. Fuer Token-Persistenz
nach einem Neustart sollte TOKEN_STORE_PATH auf einen persistenten Render-Disk-Pfad
zeigen, z.B. /var/data/mcp_oauth_store.json.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

# Claude soll moeglichst lange verbunden bleiben. Ein Refresh Token bleibt
# zusaetzlich im Store erhalten, solange der Store nicht geloescht wird.
ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365  # 365 Tage
AUTH_CODE_TTL_SECONDS = 5 * 60  # 5 Minuten


def _model_to_dict(model: Any) -> dict[str, Any]:
    """Pydantic v1/v2 kompatibel serialisieren."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class GarminAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(
        self,
        issuer_url: str,
        password: str | None = None,
        auto_approve: bool = True,
        store_path: str | None = None,
    ):
        self.issuer_url = issuer_url.rstrip("/")
        self.password = password or ""
        self.auto_approve = auto_approve
        self.store_path = Path(store_path) if store_path else None

        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, tuple[str, AuthorizationParams]] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}

        self._load_store()

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------

    def _load_store(self) -> None:
        if not self.store_path or not self.store_path.exists():
            return
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))

            self.clients = {
                item["client_id"]: OAuthClientInformationFull(**item)
                for item in data.get("clients", [])
                if item.get("client_id")
            }
            self.access_tokens = {
                item["token"]: AccessToken(**item)
                for item in data.get("access_tokens", [])
                if item.get("token")
            }
            self.refresh_tokens = {
                item["token"]: RefreshToken(**item)
                for item in data.get("refresh_tokens", [])
                if item.get("token")
            }
        except Exception:
            # Defekter Store soll den Server nicht blockieren.
            self.clients = {}
            self.access_tokens = {}
            self.refresh_tokens = {}

    def _save_store(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "clients": [_model_to_dict(client) for client in self.clients.values()],
            "access_tokens": [_model_to_dict(token) for token in self.access_tokens.values()],
            "refresh_tokens": [_model_to_dict(token) for token in self.refresh_tokens.values()],
            "saved_at": int(time.time()),
        }
        tmp_path = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.store_path)

    # ------------------------------------------------------------------
    # Client-Registrierung
    # ------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info
        self._save_store()

    # ------------------------------------------------------------------
    # Authorization-Code-Flow
    # ------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if self.auto_approve:
            return self._issue_authorization_code(client.client_id, params)

        request_id = secrets.token_urlsafe(24)
        self.pending[request_id] = (client.client_id, params)
        return f"{self.issuer_url}/login?request_id={request_id}"

    def get_pending(self, request_id: str) -> tuple[str, AuthorizationParams] | None:
        return self.pending.get(request_id)

    def complete_login(self, request_id: str) -> str:
        pending = self.pending.pop(request_id, None)
        if pending is None:
            raise ValueError("Unbekannte oder abgelaufene request_id.")
        client_id, params = pending
        return self._issue_authorization_code(client_id, params)

    def _issue_authorization_code(self, client_id: str, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(32)
        self.auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["garmin"],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self.auth_codes.get(authorization_code)
        if code is None or code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            del self.auth_codes[authorization_code]
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self.auth_codes.pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        expires_at = int(time.time() + ACCESS_TOKEN_TTL_SECONDS)

        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=expires_at,
            resource=authorization_code.resource,
        )
        self.refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
        )
        self._save_store()

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes),
        )

    # ------------------------------------------------------------------
    # Refresh-Token-Flow
    # ------------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        token = self.refresh_tokens.get(refresh_token)
        if token is None or token.client_id != client.client_id:
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self.refresh_tokens.pop(refresh_token.token, None)

        granted_scopes = scopes or refresh_token.scopes
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time() + ACCESS_TOKEN_TTL_SECONDS)

        self.access_tokens[new_access] = AccessToken(
            token=new_access,
            client_id=client.client_id,
            scopes=granted_scopes,
            expires_at=expires_at,
        )
        self.refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=granted_scopes,
        )
        self._save_store()

        return OAuthToken(
            access_token=new_access,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=new_refresh,
            scope=" ".join(granted_scopes),
        )

    # ------------------------------------------------------------------
    # Access-Token-Verifikation
    # ------------------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self.access_tokens.get(token)
        if access_token is None:
            return None
        if access_token.expires_at is not None and access_token.expires_at < time.time():
            del self.access_tokens[token]
            self._save_store()
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.access_tokens.pop(token.token, None)
        self.refresh_tokens.pop(token.token, None)
        self._save_store()
