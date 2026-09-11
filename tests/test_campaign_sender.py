import asyncio

from storefront_updates.campaign_sender import send_campaign
from storefront_updates.models import CampaignRequest, OrderStage, OrderUpdate


class RecordingGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, message: str, idempotency_key: str) -> dict[str, object]:
        self.sent.append((to, message, idempotency_key))
        return {"message_id": f"msg-{len(self.sent)}"}

    async def status(self, message_id: str) -> dict[str, object]:
        return {"status": "queued" if message_id == "msg-1" else "delivered"}


def test_campaign_keeps_order_identity_and_per_message_status() -> None:
    gateway = RecordingGateway()
    request = CampaignRequest(
        campaign_id="launch-7",
        updates=[
            OrderUpdate(
                order_id="A-41",
                phone="+14155550101",
                customer_name="Ari",
                stage=OrderStage.CHECKOUT_CONFIRMED,
                total="$42.00",
            ),
            OrderUpdate(
                order_id="A-42",
                phone="+14155550102",
                customer_name="Bea",
                stage=OrderStage.ORDER_SHIPPED,
                tracking_url="https://shop.example/track/A-42",
            ),
        ],
    )

    result = asyncio.run(send_campaign(request, gateway))

    assert [item.status for item in result.messages] == ["queued", "delivered"]
    assert [item.order_id for item in result.messages] == ["A-41", "A-42"]
    assert gateway.sent[0][2] == "launch-7:A-41:checkout_confirmed"
    assert "Track it: https://shop.example/track/A-42" in gateway.sent[1][1]

