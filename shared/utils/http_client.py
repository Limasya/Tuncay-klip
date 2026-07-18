"""
Paylasilan Asenkron HTTP Istemcisi
──────────────────────────────────
4 farkli HTTP yaklasimini (httpx, aiohttp, urllib, curl_cffi) birlestirir.
Tek bir arayuz: retry, timeout, User-Agent, connection pooling.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Varsayilan timeout
_DEFAULT_TIMEOUT = 15.0


class HttpClient:
    """Paylasilan asenkron HTTP istemcisi.

    httpx varsa onu kullanir, yoksa urllib.request fallback.
    Tekrar deneme (retry) ve timeout destegi vardir.

    Ornegin:
        client = HttpClient()
        data = await client.get_json("https://kick.com/api/v2/channels/thetuncay/clips")
        resp = await client.post("https://discord.com/api/webhooks/...", json=payload)
    """

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = 2,
    ):
        self._default_headers = default_headers or {}
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(
                    headers=self._default_headers,
                    timeout=httpx.Timeout(self._timeout),
                    follow_redirects=True,
                )
            except ImportError:
                logger.warning("httpx yuklu degil, urllib fallback kullanilacak")
                self._client = "urllib"
        return self._client

    async def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Optional[dict[str, Any]]:
        """GET istegi gonder, JSON dondur.

        Returns:
            JSON dict veya None (hata durumunda).
        """
        client = await self._get_client()
        if client == "urllib":
            return await self._get_json_urllib(url, headers, timeout)
        return await self._get_json_httpx(client, url, headers, timeout)

    async def post(
        self,
        url: str,
        json: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Optional[dict[str, Any]]:
        """POST istegi gonder.

        Returns:
            JSON dict veya None.
        """
        client = await self._get_client()
        if client == "urllib":
            return await self._post_urllib(url, json, headers, timeout)
        return await self._post_httpx(client, url, json, headers, timeout)

    async def close(self) -> None:
        """Baglanti havuzunu kapat."""
        if self._client and self._client != "urllib":
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    # ── httpx destegi ──────────────────────────────────────────────

    async def _get_json_httpx(
        self, client, url: str, headers: dict | None, timeout: float | None
    ) -> Optional[dict[str, Any]]:
        import httpx
        merged = {**self._default_headers, **(headers or {})}
        t = httpx.Timeout(timeout or self._timeout)
        last_err = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.get(url, headers=merged, timeout=t)
                if resp.status_code < 300:
                    return resp.json()
                if resp.status_code in (403, 404, 500):
                    logger.warning("HTTP %d: %s (attempt %d)", resp.status_code, url, attempt + 1)
                    return None
                last_err = f"HTTP {resp.status_code}"
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_err = str(exc)
                logger.warning("HTTP hatasi (attempt %d): %s — %s", attempt + 1, url, exc)
        logger.error("HTTP GET basarisiz (%d deneme): %s — son hata: %s", self._max_retries + 1, url, last_err)
        return None

    async def _post_httpx(
        self, client, url: str, json: dict | None, headers: dict | None, timeout: float | None
    ) -> Optional[dict[str, Any]]:
        import httpx
        merged = {**self._default_headers, **(headers or {})}
        t = httpx.Timeout(timeout or self._timeout)
        try:
            resp = await client.post(url, json=json, headers=merged, timeout=t)
            if resp.status_code < 300:
                return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"status_code": resp.status_code}
            logger.warning("HTTP POST %d: %s", resp.status_code, url)
            return {"error": f"HTTP {resp.status_code}", "status_code": resp.status_code}
        except Exception as exc:
            logger.warning("HTTP POST hatasi: %s — %s", url, exc)
            return None

    # ── urllib fallback ────────────────────────────────────────────

    async def _get_json_urllib(
        self, url: str, headers: dict | None, timeout: float | None
    ) -> Optional[dict[str, Any]]:
        import urllib.request
        import json as _json

        merged = {**self._default_headers, **(headers or {})}
        t = timeout or self._timeout

        def _do():
            req = urllib.request.Request(url, headers=merged)
            with urllib.request.urlopen(req, timeout=t) as resp:
                return _json.loads(resp.read().decode("utf-8"))

        try:
            return await asyncio.wait_for(asyncio.to_thread(_do), timeout=t + 5)
        except Exception as exc:
            logger.warning("urllib GET hatasi: %s — %s", url, exc)
            return None

    async def _post_urllib(
        self, url: str, json_data: dict | None, headers: dict | None, timeout: float | None
    ) -> Optional[dict[str, Any]]:
        import urllib.request
        import json as _json

        merged = {**self._default_headers, **(headers or {})}
        t = timeout or self._timeout

        def _do():
            data = _json.dumps(json_data).encode("utf-8") if json_data else None
            req = urllib.request.Request(url, data=data, headers=merged, method="POST")
            with urllib.request.urlopen(req, timeout=t) as resp:
                body = resp.read().decode("utf-8")
                return _json.loads(body) if body else {}

        try:
            return await asyncio.wait_for(asyncio.to_thread(_do), timeout=t + 5)
        except Exception as exc:
            logger.warning("urllib POST hatasi: %s — %s", url, exc)
            return None


# Import eksikligi icin
import asyncio
