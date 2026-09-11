import asyncio
import json

import httpx

from storefront_updates.infrai_sms import InfraiSms


def test_send_uses_bearer_envelope_and_idempotency_key() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["authorization"] = request.headers["Authorization"]
        observed["idempotency"] = request.headers["Idempotency-Key"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "data": {"message_id": "msg-9"}})

    async def exercise() -> dict[str, object]:
        client = InfraiSms("test-key", transport=httpx.MockTransport(handler))
        try:
            return await client.send("+14155550103", "Order B-7 is ready.", "campaign:B-7")
        finally:
            await client.close()

    assert asyncio.run(exercise()) == {"message_id": "msg-9"}
    assert observed == {
        "method": "POST",
        "path": "/v1/sms/send",
        "authorization": "Bearer test-key",
        "idempotency": "campaign:B-7",
        "body": {"to": "+14155550103", "body": "Order B-7 is ready."},
    }
