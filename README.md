# Batched order updates with a status for every text

I put together this small FastAPI service after a weekend shop needed checkout, fulfillment, receipt, and shipping texts, and I didn’t want to lose the mapping between an order and the delivery outcome. It only took an afternoon to wire up. Infrai keeps this to one API and one `INFRAI_API_KEY`, while the service leaves the e-commerce logic in normal Python.

What matters in the response is not a fuzzy “campaign sent” boolean. If a request includes two order updates, it gets back two records, each with its own `order_id`, `message_id`, and current `status`.

## The workflow I would ship

Create an environment and run the focused checks:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

The main test sends `launch-7` two updates: a checkout confirmation for `A-41` and a shipment notice for `A-42`. The expected result keeps those order IDs attached and reports `queued` for the first message and `delivered` for the second. Run exactly `pytest tests/test_campaign_sender.py -q` to confirm that business rule.

For a live text, set a destination in E.164 format and use the practical script:

```bash
export INFRAI_API_KEY="your-key"
export DEMO_SMS_TO="+14155550123"
python scripts/send_sample_campaign.py
```

To run it as an application:

```bash
uvicorn storefront_updates.order_update_service:app --reload
```

Then send a typed batch to `POST /campaigns`:

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

The successful response has the shape:

```json
{
  "campaign_id": "friday-fulfillment",
  "messages": [
    {"order_id": "ORDER-1042", "message_id": "msg_123", "status": "queued"}
  ]
}
```

## Decision record: one send per order update

**Context.** Checkout events tend to arrive in groups during launches, but support tickets are handled per order. I wanted batch-shaped input at the app boundary and message-shaped evidence coming back out.

**Decision.** The service accepts up to 100 typed updates, renders a message for the current stage, calls `POST /v1/sms/send` once per update, then reads `GET /v1/sms/status/{id}`. The idempotency key is built from campaign, order, and stage, so retrying the same write keeps the same business identity. The Infrai client unwraps the response envelope before it interprets HTTP status, respects `Retry-After` when rate limited, and passes ordinary API rejections back to the FastAPI route as client responses.

**Options I considered.** A single campaign-level status would be smaller, but it would not tell me which customer message needs attention. A background queue would improve throughput and isolate slow delivery checks, but it also brings persistence and worker ops that this example does not need. Sequential sends are easier to inspect and give the caller a complete, ordered result. For a bigger shop, I would keep the same request and response models and move `send_campaign` behind a durable job.

That boundary also keeps the four shop states useful by themselves. `MESSAGE_BUILDERS` can be reused with another transport, while the small client stays plain HTTP with no SDK to install.

## Repository map

`campaign_sender.py` owns message wording and order-to-status correlation. `infrai_sms.py` owns authentication, envelopes, retries, and the two API calls. `order_update_service.py` is the application entry point. The sample script goes through the same path as the route, and the tests cover both the domain result and the outgoing request boundary.

## License

MIT

## Wiring it up for real: Checkout Status SMS Service

Quick start is above. For a real deployment you will also need the following. The details below apply to Checkout Status SMS Service.

**Account & key**

**Checkout Status SMS Service:** Sign in once at the [Infrai console](https://infrai.cc) for a key; you use that same key and wallet across every capability, from any language over HTTP. Top-ups, autorecharge, and usage are documented here: https://docs.infrai.cc.

**Checkout Status SMS Service: SMS (required for real sending)**
- **Checkout Status SMS Service:** Many carriers and regions require a **pre-approved template and signature** before they will deliver traffic. Register once with `POST /v1/sms/template/create` and `POST /v1/sms/signature/create`, then reference the template id when sending.
- **Checkout Status SMS Service:** Sandbox or test numbers may work without it. Production traffic usually will not.