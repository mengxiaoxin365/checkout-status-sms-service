from collections.abc import Callable
from typing import Protocol

from .models import CampaignRequest, CampaignResult, MessageResult, OrderStage, OrderUpdate


class SmsGateway(Protocol):
    async def send(
        self, to: str, message: str, idempotency_key: str
    ) -> dict[str, object]:
        raise AssertionError("protocol method")

    async def status(self, message_id: str) -> dict[str, object]:
        raise AssertionError("protocol method")


MESSAGE_BUILDERS: dict[OrderStage, Callable[[OrderUpdate], str]] = {
    OrderStage.CHECKOUT_CONFIRMED: lambda u: (
        f"Hi {u.customer_name}, order {u.order_id} is confirmed"
        + (f" for {u.total}." if u.total else ".")
    ),
    OrderStage.FULFILLMENT_STARTED: lambda u: (
        f"Hi {u.customer_name}, we are preparing order {u.order_id}."
    ),
    OrderStage.RECEIPT_READY: lambda u: (
        f"Hi {u.customer_name}, your receipt for order {u.order_id} is ready."
    ),
    OrderStage.ORDER_SHIPPED: lambda u: (
        f"Hi {u.customer_name}, order {u.order_id} has shipped."
        + (f" Track it: {u.tracking_url}" if u.tracking_url else "")
    ),
}


async def send_campaign(request: CampaignRequest, gateway: SmsGateway) -> CampaignResult:
    results: list[MessageResult] = []
    for update in request.updates:
        sent = await gateway.send(
            update.phone,
            MESSAGE_BUILDERS[update.stage](update),
            f"{request.campaign_id}:{update.order_id}:{update.stage.value}",
        )
        message_id = str(sent["message_id"])
        delivery = await gateway.status(message_id)
        results.append(
            MessageResult(
                order_id=update.order_id,
                message_id=message_id,
                status=str(delivery["status"]),
            )
        )
    return CampaignResult(campaign_id=request.campaign_id, messages=results)
