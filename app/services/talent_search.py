import logging
import time

import httpx

from services.inhire_client import InHireClient

logger = logging.getLogger("agente-inhire.talent-search")

# Typesense host for InHire (tenant demo — confirmed working 2026-04-07)
TYPESENSE_HOST = "https://i7cjbwaez4p8lktdp-1.a1.typesense.net"

# Searchable fields in the talents collection (confirmed via schema probing)
# - name: talent's full name
# - resume: full CV text (contains skills, experience, education)
# - location: city/state/country
DEFAULT_QUERY_BY = "name,resume,location"


class TalentSearchService:
    """Full-text talent search via Typesense scoped keys from InHire API."""

    def __init__(self, inhire: InHireClient):
        self.inhire = inhire
        self._key: str | None = None
        self._index_name: str | None = None
        self._app_id: str | None = None
        self._expires_at: float = 0
        self._client = httpx.AsyncClient(timeout=15)

    async def _ensure_key(self):
        """Fetch or refresh the Typesense scoped key (cached for 23h)."""
        if self._key and time.time() < self._expires_at:
            return

        logger.info("Buscando nova chave Typesense...")
        data = await self.inhire.get_typesense_key()
        self._key = data["key"]
        self._index_name = data["indexName"]
        self._app_id = data.get("appId", "")
        # Refresh 1h before expiry (key lasts 24h)
        ttl_ms = data.get("validForInMilliseconds", 86400000)
        self._expires_at = time.time() + (ttl_ms / 1000) - 3600
        logger.info("Chave Typesense obtida. Index: %s, expira em %dh",
                     self._index_name, ttl_ms // 3600000)

    async def search(self, query: str, max_results: int = 10,
                     query_by: str = DEFAULT_QUERY_BY) -> dict:
        """Search talents using Typesense full-text search.

        Args:
            query: Search text (e.g., "python backend São Paulo")
            max_results: Max results to return (default 10)
            query_by: Comma-separated fields to search in

        Returns:
            dict with 'found' (total count) and 'hits' (list of talent docs)
        """
        await self._ensure_key()

        url = f"{TYPESENSE_HOST}/collections/{self._index_name}/documents/search"

        try:
            resp = await self._client.get(
                url,
                params={
                    "q": query,
                    "query_by": query_by,
                    "per_page": max_results,
                    "sort_by": "_text_match:desc",
                },
                headers={
                    "X-TYPESENSE-API-KEY": self._key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            found = data.get("found", 0)
            hits = []
            for hit in data.get("hits", []):
                doc = hit.get("document", {})
                # Extract a headline from the first line of resume
                resume = doc.get("resume", "") or ""
                headline = ""
                for line in resume.split("\n"):
                    line = line.strip()
                    if line and len(line) > 10 and line != doc.get("name", ""):
                        headline = line[:120]
                        break
                hits.append({
                    "id": doc.get("id", ""),
                    "name": doc.get("name", "Sem nome"),
                    "email": doc.get("email", ""),
                    "headline": headline,
                    "location": doc.get("location", ""),
                    "linkedin": doc.get("linkedinUsername", ""),
                    "score": hit.get("text_match_info", {}).get("score", 0),
                })

            logger.info("Busca '%s': %d encontrados, %d retornados", query, found, len(hits))
            return {"found": found, "hits": hits}

        except httpx.HTTPStatusError as e:
            logger.error("Typesense search error %d: %s", e.response.status_code, e.response.text)
            # If 403/401, key may be invalid — clear cache
            if e.response.status_code in (401, 403):
                self._key = None
                self._expires_at = 0
            raise
        except Exception as e:
            logger.error("Typesense search failed: %s", e)
            raise

    async def close(self):
        await self._client.aclose()
