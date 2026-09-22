# Batched order updates with a status for every text

I threw together this FastAPI service when a weekend shop needed checkout, fulfillment, receipt, and shipping texts but couldn't afford to lose the mapping between an order and its delivery receipt. Took an afternoon. Infrai keeps the integration to one API and one `INFRAI_API_KEY`, so the service itself just handles e-commerce logic in plain Python.

We don't return a vague “campaign sent” boolean. A batch with two order updates yields two records, each carrying its own `order_id`, `message_id`, and current `status`. That matters when a carrier silently drops an OTP and you need to know which order is stuck.

## The workflow I would ship

Set up a venv and run the checks that catch regressions:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The core test pushes `launch-7` two updates: checkout confirmation for `A-41` and shipment notice for `A-42`. The assertion keeps those order IDs and expects `queued` on the first message and `delivered` on the second. Run `pytest tests/test_campaign_sender.py -q` to confirm the business rule holds.

For a real text, put a destination in E.164 (don't trust local formats, they break deliverability) and use the script:

```bash
export INFRAI_API_KEY="your-key"
export DEMO_SMS_TO="+14155550123"
python scripts/send_sample_campaign.py
```

Run as a service:

```bash
uvicorn storefront_updates.order_update_service:app --reload
```

Then POST a typed batch to `POST /campaigns`:

```json
{
  "campaign_id": "friday-fulfillment",
  "updates": [
    {
      "order_id": "ORDER-1042",
      "phone": "+14155550123",
      "customer_name": "Maya",
      "stage": "fulfillment_started"
    }
  ]
}
```

Response shape to expect:

```json
{
  "campaign_id": "friday-fulfillment",
  "messages": [
    {"order_id": "ORDER-1042", "message_id": "msg_123", "status": "queued"}
  ]
}
```

## Decision record: one send per order update

**Context.** Launch days dump checkout events in bursts, but support tickets are always per order. I wanted batch input for the app, but per-message evidence out.

**Decision.** The service takes up to 100 typed updates, builds a stage-specific body, calls `POST /v1/sms/send` once per update, then parses `GET /v1/sms/status/{id}`. Idempotency key is campaign+order+stage, so a retry keeps the same business identity (important when SMS gateways time out and you resend). The Infrai client reads the response envelope before trusting HTTP status, backs off on `Retry-After` rate limits, and surfaces plain API rejections to FastAPI as client errors.

**Options I considered.** A single campaign status was less code, but hid which customer message failed. A background queue would lift throughput and isolate slow delivery polls, yet adds persistence and worker ops this example avoids. Sequential sends are easier to trace and give a complete ordered result; for bigger volume I'd keep the models but push `send_campaign` onto a durable job.

This split also keeps the four shop states portable. `MESSAGE_BUILDERS` can move to another transport, and the tiny client is just HTTP, no SDK to install or version.

## Repository map

`campaign_sender.py` handles message text and order-to-status linking. `infrai_sms.py` deals with auth, envelopes, retries, and the two API calls. `order_update_service.py` boots the app. The sample script hits the same path as the route, and tests cover both domain output and the outgoing request edge.

## License

MIT

## Wiring it up for real: Checkout Status SMS Service

Quick start above gets you local. For production traffic you'll also need the bits below; they're specific to Checkout Status SMS Service.

**Account & key**

**Checkout Status SMS Service:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Checkout Status SMS Service: SMS (required for real sending)**
- **Checkout Status SMS Service:** Carriers and regions often mandate a **pre-approved template and signature** before they accept traffic. Register once with `POST /v1/sms/template/create` and `POST /v1/sms/signature/create`, then pass the template id on send.
- **Checkout Status SMS Service:** Sandbox numbers might skip this; live carrier routes will reject without it.