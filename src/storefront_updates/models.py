from enum import StrEnum

from pydantic import BaseModel, Field


class OrderStage(StrEnum):
    CHECKOUT_CONFIRMED = "checkout_confirmed"
    FULFILLMENT_STARTED = "fulfillment_started"
    RECEIPT_READY = "receipt_ready"
    ORDER_SHIPPED = "order_shipped"


class OrderUpdate(BaseModel):
    order_id: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    customer_name: str = Field(min_length=1, max_length=80)
    stage: OrderStage
    total: str | None = None
    tracking_url: str | None = None


class CampaignRequest(BaseModel):
    campaign_id: str = Field(min_length=1, max_length=80)
    updates: list[OrderUpdate] = Field(min_length=1, max_length=100)


class MessageResult(BaseModel):
    order_id: str
    message_id: str
    status: str


class CampaignResult(BaseModel):
    campaign_id: str
    messages: list[MessageResult]

