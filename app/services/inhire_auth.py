import asyncio
import logging
import time

import httpx

from config import Settings

logger = logging.getLogger("agente-inhire.auth")


class InHireAuth:
    """Manages JWT authentication with InHire API, auto-refreshing tokens."""

    def __init__(self, settings: Settings):
        self.auth_url = settings.inhire_auth_url
        self.email = settings.inhire_email
        self.password = settings.inhire_password
        self.tenant = settings.inhire_tenant
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0
        self._client = httpx.AsyncClient(timeout=30)
        self._lock = asyncio.Lock()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "X-Tenant": self.tenant,
            "Content-Type": "application/json",
        }

    async def login(self):
        """Authenticate with email/password, with retry."""
        for attempt in range(3):
            try:
                logger.info("Autenticando na API InHire (tentativa %d)...", attempt + 1)
                resp = await self._client.post(
                    f"{self.auth_url}/login",
                    json={"email": self.email, "password": self.password},
                    headers={"X-Tenant": self.tenant, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                self._set_tokens(resp.json())
                logger.info("Autenticação InHire OK.")
                return
            except Exception as e:
                logger.error("Falha na autenticação (tentativa %d): %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        logger.error("Todas as tentativas de autenticação falharam. Servidor inicia sem token.")

    async def ensure_valid_token(self):
        """Refresh the token if it's about to expire. Thread-safe with lock."""
        if time.time() < self._expires_at - 300:
            return

        async with self._lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if time.time() < self._expires_at - 300:
                return

            logger.info("Renovando token InHire...")

            # Try refresh first
            if self._refresh_token:
                try:
                    resp = await self._client.post(
                        f"{self.auth_url}/refresh",
                        json={"refreshToken": self._refresh_token},
                        headers={"X-Tenant": self.tenant},
                    )
                    if resp.status_code == 200:
                        self._set_tokens(resp.json())
                        logger.info("Token renovado via refresh.")
                        return
                except Exception as e:
                    logger.warning("Refresh falhou: %s", e)

            # Fallback: full re-login
            logger.info("Refresh falhou, re-autenticando...")
            await self.login()

    def _set_tokens(self, data: dict):
        self._access_token = data.get("accessToken") or data.get("access_token")
        self._refresh_token = data.get("refreshToken") or data.get("refresh_token")
        self._expires_at = time.time() + data.get("expiresIn", 3600)

    async def close(self):
        await self._client.aclose()
