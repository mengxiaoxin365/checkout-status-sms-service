import os

from fastapi import FastAPI, HTTPException

from .campaign_sender import send_campaign
from .infrai_sms import InfraiError, InfraiSms
from .models import CampaignRequest, CampaignResult

app = FastAPI(title="Checkout status SMS service")


@app.post("/campaigns", response_model=CampaignResult)
async def create_campaign(request: CampaignRequest) -> CampaignResult:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="INFRAI_API_KEY is required")

    gateway = InfraiSms(api_key)
    try:
        return await send_campaign(request, gateway)
    except InfraiError as exc:
        caller_status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(
            status_code=caller_status,
            detail={"code": exc.code, "error": exc.detail},
        ) from exc
    finally:
        await gateway.close()

