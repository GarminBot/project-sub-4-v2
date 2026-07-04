"""
Minimaler OAuth-2.1-Authorization-Server, eingebettet im MCP-Server selbst.

Gedacht fuer EINEN einzigen Nutzer (dich). Es gibt keine Nutzerverwaltung -
"Login" bedeutet: ein Passwort eingeben (MCP_LOGIN_PASSWORD), das nur du kennst.
Danach bekommt Claude einen Access-Token fuer deinen persoenlichen Garmin-Zugang.

WICHTIG (Speicher-Limitierung): Alle Clients/Codes/Tokens liegen nur im
Prozess-Speicher (RAM). Auf Render Free Tier wird der Prozess nach Inaktivitaet
komplett neu gestartet -> dabei gehen bestehende Sessions verloren und du musst
den Connector in Claude einmal neu verbinden (Settings -> Connectors -> Reconnect).
Fuer ein Hobby-Projekt ist das ein akzeptabler Kompromiss; falls es nervt, hilft
ein bezahlter Render-Plan mit "always on" (kein Spin-down mehr).

Ablauf:
1. Claude ruft GET /authorize auf (macht der SDK-Code automatisch) -> authorize()
   wird aufgerufen -> wir merken uns die Anfrage unter einer request_id und
   schicken den Browser zu unserer eigenen Login-Seite (/login?request_id=...).
2. Du gibst dort das Passwort ein (POST /login in server.py).
3. Bei Erfolg generieren wir einen Authorization Code und leiten zurueck zu
   Claudes redirect_uri (inkl. code + state).
4. Claude tauscht den Code gegen Access-/Refresh-Token (exchange_authorization_code).
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
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 Tage
AUTH_CODE_TTL_SECONDS = 5 * 60  # 5 Minuten zum Login


class GarminAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(self, issuer_url: str, password: str):
        self.issuer_url = issuer_url.rstrip("/")
        self.password = password

        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.pending: dict[str, tuple[str, AuthorizationParams]] = {}  # request_id -> (client_id, params)
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}

    # --- Client-Registrierung (Dynamic Client Registration) ---

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info

    # --- Authorization-Code-Flow ---

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = secrets.token_urlsafe(24)
        self.pending[request_id] = (client.client_id, params)
        return f"{self.issuer_url}/login?request_id={request_id}"

    def get_pending(self, request_id: str) -> tuple[str, AuthorizationParams] | None:
        return self.pending.get(request_id)

    def complete_login(self, request_id: str) -> str:
        """Wird von der /login-POST-Route in server.py aufgerufen, NACHDEM das
        Passwort erfolgreich geprueft wurde. Erzeugt den Authorization Code und
        gibt die fertige Redirect-URL zurueck."""
        pending = self.pending.pop(request_id, None)
        if pending is None:
            raise ValueError("Unbekannte oder abgelaufene request_id.")
        client_id, params = pending

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

        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes),
        )

    # --- Refresh-Token-Flow ---

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
        # Alten Refresh-Token invalidieren, neue Tokens ausstellen (Rotation)
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

        return OAuthToken(
            access_token=new_access,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=new_refresh,
            scope=" ".join(granted_scopes),
        )

    # --- Access-Token-Verifikation ---

    async def load_access_token(self, token: str) -> AccessToken | None:
        access_token = self.access_tokens.get(token)
        if access_token is None:
            return None
        if access_token.expires_at is not None and access_token.expires_at < time.time():
            del self.access_tokens[token]
            return None
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.access_tokens.pop(token.token, None)
        self.refresh_tokens.pop(token.token, None)
