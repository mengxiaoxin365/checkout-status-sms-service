import asyncio
import os

from storefront_updates.campaign_sender import send_campaign
from storefront_updates.infrai_sms import InfraiSms
from storefront_updates.models import CampaignRequest, OrderStage, OrderUpdate


async def main() -> None:
    api_key = os.environ.get("INFRAI_API_KEY")
    phone = os.environ.get("DEMO_SMS_TO")
    if not api_key or not phone:
        raise SystemExit("Set INFRAI_API_KEY and DEMO_SMS_TO")

    request = CampaignRequest(
        campaign_id="weekend-shop-demo",
        updates=[
            OrderUpdate(
                order_id="ORDER-1042",
                phone=phone,
                customer_name="Maya",
                stage=OrderStage.FULFILLMENT_STARTED,
            )
        ],
    )
    gateway = InfraiSms(api_key)
    try:
        result = await send_campaign(request, gateway)
        print(result.model_dump_json(indent=2))
    finally:
        await gateway.close()


if __name__ == "__main__":
    asyncio.run(main())

