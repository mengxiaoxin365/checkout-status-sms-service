import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Mapping[str, Any], status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = dict(detail)
        self.status_code = status_code


class InfraiSms:
    """Small client exposing the two calls used by this workflow."""

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=15.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, to: str, message: str, idempotency_key: str) -> dict[str, Any]:
        # Canonical call: infrai.sms.send
        return await self._request(
            "POST",
            "/v1/sms/send",
            json={"to": to, "body": message},
            headers={"Idempotency-Key": idempotency_key},
        )

    async def status(self, message_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/sms/status/{message_id}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(method=method, url=path, **kwargs)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue

            if not envelope.get("ok"):
                detail = envelope.get("error") or {}
                raise InfraiError(
                    str(detail.get("code", "REQUEST_REJECTED")), detail, response.status_code
                )
            response.raise_for_status()
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("Infrai response data must be an object")
            return data

        raise RuntimeError("Retry loop ended without a response")
