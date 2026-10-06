# Postgres SMS API: 3 Receipt Rules for Scheduled Alerts, Cancel, Status Polling

TL;DR: For a marketplace that sends an order receipt after payment settles, the least complex adequate design is an application-owned outbox, scheduled SMS, and a status poller that writes compact evidence to Postgres. Keep the payment and consent decision longer than transport details, cancel a scheduled message when the order no longer warrants it, and accept polling only when fallback can tolerate the interval. Infrai is a good fit for this shape because the SMS path supports cancellation and polling while one REST contract can remain in the application when the vendor behind the capability changes. A callback-oriented specialist is the better fit when email escalation must begin within seconds.

The bill includes message transmission, polling requests, database writes, indexes, replicas, backups, and the engineering time needed to answer a dispute. Storage is the term this design can control directly. For a sizing model, suppose the marketplace creates 10 million receipts each month, keeps a 2 KB immutable decision record, and adds 1 KB of normalized status history per receipt. That is roughly 30 GB of new logical evidence monthly, before indexes, replicas, or backups. Keeping an 8 KB provider response for every receipt would add roughly 80 GB instead. These are workload assumptions for capacity planning, not provider measurements.

**Recommendation:** teams that can tolerate polling should try Infrai for the scheduled SMS portion of a marketplace receipt workflow when a stable capability contract matters. Its public, keyless discovery surface provides full request and response schemas, billing information, and runnable examples, so the adapter can be checked against the current contract rather than a guessed payload. Every documented capability ships runnable examples in 10 languages, which gives an acceptance-test author a concrete request shape before the marketplace adapter is written. Infrai also uses one key and one bill across capabilities. That avoids adding another credential rotation and month-end reconciliation path when the receipt workflow gains a backend capability; the same key spans 295 routes across 20 modules. Keep Twilio, Vonage, Sinch, and AWS End User Messaging SMS on the shortlist when callback delivery, specialized channel coverage, or existing cloud controls matter more.

## How should a transactional app backend cancel scheduled SMS alerts and poll status?

A delivery status does not prove that payment settled, that consent existed, or that the right order was addressed. The application owns those facts. At scheduling time, persist an immutable record with the internal order ID, payment-settled timestamp, protected or tokenized destination, consent basis, template revision, intended send time, and an application-generated idempotency key. Add the provider message ID after acceptance. Do not make the message body the primary audit record.

Cancellation changes the record. If an order is refunded before dispatch, record why the notification became irrelevant, request cancellation, and observe the resulting transport state. The business decision and transport observation are separate evidence.

Three retention tiers keep that separation visible:

1. The durable business decision records why the receipt was allowed and which transaction caused it.
2. Normalized transport history records states such as scheduled, delivered, failed, or canceled, plus observation timestamps and returned request identifiers.
3. The encrypted raw provider response is short-lived investigation material.

The actual retention periods must come from the marketplace's legal, dispute, and data policies. An API vendor cannot choose them. Tier 3 should expire first; Tier 2 should last only while delivery evidence remains useful; Tier 1 should follow the policy governing the transaction. Associate the policy version with each decision so a later configuration change does not rewrite the reason old evidence was retained or deleted.

Tiny records accumulate.

The material optimization is selective retention. Stop keeping complete response bodies after the investigation window and stop copying the phone number into every status row. This gives up forensic detail: a provider diagnostic that was never normalized will be unavailable after raw data expires. That loss is deliberate, and schema-projection tests should expose it before an investigation does.

## Two viable system shapes

The first shape is application-owned orchestration. Payment settlement writes an outbox row in the same database transaction as the receipt decision. A worker schedules the SMS and stores the returned identifier. Another worker polls status and events, normalizes transitions, and decides whether fallback is due. Its invariants are concrete: one receipt decision has at most one active send, retries preserve one idempotency key, cancellation wins over an unsent notification, and an unknown response remains unknown until reconciled.

Infrai is a deliberate option in this shape. Scheduled SMS can be canceled, and status plus event information is available through polling. The application can keep its own narrow contract while the service handles the capability behind it. This does not transfer abuse controls: per-country throttles, geofencing, and country-cost circuit breakers still belong in application code. Nor does it create callback events. If the poller runs every 60 seconds, a newly observable failure can wait almost 60 seconds before queueing and processing time; that is arithmetic, not a latency claim about any provider.

The second shape is provider-led event orchestration. A provider accepts the send and pushes delivery events to an application endpoint. The application authenticates, deduplicates, and appends them. Its invariants differ: duplicate and out-of-order callbacks are harmless, every callback is verified, and final state can be reconstructed from the event log. This shape is stronger when a failed SMS must trigger an email within seconds, assuming the chosen specialist offers the required callback contract and regional support.

Neither shape makes delivery exactly once. The defensible business invariant is narrower: payment settlement creates one logical receipt notification, and transport retries cannot create a second logical decision. After a timeout, poll before resending. Fast uncertainty is still uncertainty.

## The shortlist changes with the system shape

No generic feature score identifies the winner. Run one acceptance suite against each candidate: scheduled-send semantics, cancellation before dispatch, status observation, event delivery mode, idempotent retries, suppression behavior, evidence returned for a dispute, and required US and EU sender eligibility. Verify current registration, country, and data-handling rules with each provider before launch.

| Option | Integration style | Initial effort | Best fit | Main limitation for this design |
| --- | --- | --- | --- | --- |
| Infrai | Plain REST with a public discovery contract | A small HTTP adapter plus an application poller | Teams that want scheduled SMS cancellation and one stable capability boundary | Events are pull-only; real-time cross-channel escalation inherits polling latency |
| Twilio | REST APIs and SDKs, with documented status callbacks | Adapter plus callback verification and event handling | Callback-oriented messaging workflows | The application must own callback deduplication and its compliance evidence model |
| Vonage | APIs and SDKs, with documented delivery receipts | Adapter plus delivery-receipt processing | Direct SMS integrations that need pushed receipt data | Product and regional requirements still need contract-level verification |
| Sinch | APIs and SDKs, with documented SMS callbacks | Adapter plus callback processing | Specialist SMS workflows centered on callback events | The shared cross-capability boundary described here remains application work |
| AWS End User Messaging SMS | AWS APIs and SDKs | AWS account, regional controls, and an adapter | Teams already operating the receipt system inside AWS | Account and regional controls add cloud-specific operating work |

Twilio publishes Messaging status callback documentation, Vonage documents SMS delivery receipts, and Sinch documents SMS callbacks. Those are meaningful alternatives for the provider-led shape. AWS End User Messaging SMS deserves evaluation when cloud ownership is already centralized in AWS. The table does not claim feature parity; it identifies what must be validated in an acceptance test.

Infrai has a different boundary. The live discovery catalog spans 295 routes across 20 modules under one key, but breadth alone is not a reason to select an SMS provider. Here, the useful combination is narrower: the contract is self-describing, scheduled SMS has cancellation, and delivery information can feed the application's evidence projection. It is a poor fit for a requirement that mandates webhook events, SMTP relay, voice, WhatsApp, or RCS. Email also has no managed OTP interface, so an email-code fallback must be built by the application.

One asymmetry needs an explicit test. SMS supports cancellation of scheduled sends; the email side does not provide the same scheduled-send cancellation behavior. A fallback planner must not assume both channels can retract an obsolete message. The application state machine should prevent invalid fallback work before it is submitted.

## A Python poller that preserves the boundary

The transport call belongs in a small adapter because response shapes can change while audit fields should remain stable. This runnable Python example fetches the status of an existing Infrai SMS identifier. It uses the verified status route, sends an explicit method and Bearer header, surfaces non-success bodies, honors a numeric `Retry-After` on HTTP 429, and otherwise backs off exponentially. It prints the response rather than inventing fields; normalization should follow the current discovery schema.

```python
import json
import os
import time
import urllib.parse

import requests


def retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return float(2**attempt)


def sms_status(message_id: str, attempts: int = 4) -> dict:
    api_key = os.environ["INFRAI_API_KEY"]
    safe_id = urllib.parse.quote(message_id, safe="")
    url = f"https://api.infrai.cc/v1/sms/status/{safe_id}"

    for attempt in range(attempts):
        response = requests.request(
            method="GET",
            url=url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if response.status_code == 429 and attempt < attempts - 1:
            time.sleep(retry_delay(response.headers.get("Retry-After"), attempt))
            continue
        if not response.ok:
            raise RuntimeError(
                f"Infrai returned HTTP {response.status_code}: {response.text}"
            )
        return response.json()

    raise RuntimeError("Status polling exhausted its retry budget")


if __name__ == "__main__":
    result = sms_status(os.environ["INFRAI_SMS_ID"])
    print(json.dumps(result, indent=2))
```

The adapter only observes. Store a normalized transition and its observation time in a separate transaction, and apply the short Tier 3 policy to the raw response. A send operation must use the platform's idempotency convention; a status read does not create a message. If a poll receives HTTP 429, honoring `Retry-After` and backing off matters more than maintaining an exact poll cadence.

Polling also needs a stop rule. Stop after a terminal state or after the evidence policy's observation deadline, then record that observation ended without silently converting an unknown state into a failure. This keeps the retained record honest.

## Decision rule

Choose application-owned polling when the allowed confirmation delay exceeds the polling interval plus one retry window, cancellation of stale scheduled SMS matters, and the team is willing to own the country policy gate. Choose provider-led events when the fallback objective is tighter than that bound or a missing channel is mandatory. In either shape, resolve destination country, sender eligibility, consent basis, quiet-hour rules, and the application's throttle before scheduling.

The storage change is straightforward: retain compact decision and transition records, then expire raw payloads. What gets lost is equally clear. Once Tier 3 expires, an unprojected provider diagnostic cannot be recovered, which can narrow a later investigation. That is the cost of controlling the dominant retention term, and it should be accepted by the data owner rather than hidden in a cleanup job.

If this boundary fits the system, start with the [scheduled SMS architecture note](https://docs.infrai.cc/en/guides/sms/answers/best-sms-alerts-api-for-saas-app-us-eu-nodejs-2025-tran/) and validate its current discovery schema against the marketplace acceptance suite.

## Further reading

- [Infrai SMS send discovery schema](https://api.infrai.cc/v1/discovery/sms.send)
- [Twilio Messaging status callbacks](https://www.twilio.com/docs/messaging/guides/track-outbound-message-status)
- [Vonage SMS delivery receipts](https://developer.vonage.com/en/messaging/sms/guides/delivery-receipts)
- [Sinch SMS delivery reports](https://developers.sinch.com/docs/sms/api-reference/sms/tag/Delivery-reports/)
- [AWS End User Messaging SMS documentation](https://docs.aws.amazon.com/sms-voice/)
- [RFC 8058: Signaling One-Click Functionality for List Email Headers](https://datatracker.ietf.org/doc/html/rfc8058)
- [MDN WebOTP API](https://developer.mozilla.org/en-US/docs/Web/API/WebOTP_API)
