# US/EU SMS Notifications: Carrier Failures, Sender Registration, and Resend Troubleshooting

**Short answer:** For US/EU telehealth login verification, register the sender and signature first, poll every SMS event to a terminal state, and make resends separate idempotent attempts with an auditable link to the original failure.

For a telehealth login verification flow, the dominant cost of a failed SMS is not the message itself. It is the missing evidence around the message: which sender was registered for the destination country, whether the carrier rejected it, and whether a retry created a second valid login attempt. Build the sender and signature configuration before investigating delivery, then keep a polling record for every attempt. That gives the compliance notice a defensible trail without pretending that an API can control carrier filtering.

The practical decision is to keep the application contract stable: create an internal notification record, submit one SMS attempt, poll its status, and make resends idempotent. The provider behind that contract can change later. The record format should not.

That boundary matters.

## What does a failed SMS actually cost?

The bill has at least two terms. There is the carrier-bound message attempt, and there is retention and operational work: status checks, support investigation, duplicate-code handling, and evidence storage. For a login code, the second term is usually the dangerous one. A single delayed message can cause a user to request several more, each with a different validity window and each requiring an explanation later.

I would retain the notification ID, destination country, sender configuration version, request timestamp, status transitions, provider request ID, and the reason returned for a failure or rejection. I would not retain the OTP value in the audit record. OWASP recommends treating reset and verification tokens as sensitive, single-use, and time-limited; an audit trail that stores the code defeats part of that protection.

The change that moves the dominant term is procedural: register and verify the correct sender configuration for the US and each EU destination market before sending production traffic. Signatures and sender identity are delivery inputs, not cosmetic fields. When a carrier rejects a message, a `failed` result is useful only if the record still tells an operator which registration and template produced it.

What do I deliberately stop keeping? The secret code, full message body where policy does not require it, and an unbounded stream of polling responses. Keeping those forever increases exposure and storage noise. The trade-off is that a later investigation may need a redacted body hash, a retained status timeline, and the configuration snapshot instead of the original text. That is a deliberate compliance boundary, not a gap to hide.

The audit trail is not the message archive.

## How should US/EU SMS event notifications handle carrier failures and resends?

Separate the questions. First verify the destination and sender registration. Then submit one attempt and poll its status. A queued result means the provider has accepted work; it does not mean the carrier accepted delivery. A delivered result is different from a failed or carrier-rejected result, and those distinctions should survive in your internal event log.

For a delayed alert, a resend can be appropriate. For a login verification code, it should be guarded by a user-facing cooldown, a per-account attempt limit, and a fresh idempotency key for the new business action. Retrying the same network request needs the original idempotency key; otherwise a timeout can turn one click into two messages. Cancellation is useful for an obsolete delayed SMS, but it is not a recall mechanism for a message already accepted by a carrier.

Five polling attempts with a maximum 30-second delay is a starting policy, not a universal truth. A high-risk login flow may prefer a shorter user wait and a background reconciliation job; a compliance notice may tolerate a longer window. The point is to choose the boundary explicitly and record when it expires.

Here is the shape I use for a worker. It keeps the example intentionally small: one send route, one status route, and a retry policy that respects `Retry-After`. The application should persist the attempt before calling the provider and update it after every response.

```python
import os
import time
import uuid

import requests


BASE_URL = os.environ["SMS_API_BASE_URL"]


def send_and_poll(phone_number: str, message: str) -> dict:
    api_key = os.environ["INFRAI_API_KEY"]
    attempt_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Idempotency-Key": attempt_id,
    }
    payload = {"to": phone_number, "message": message}

    for retry in range(5):
        response = requests.post(
            f"{BASE_URL}/sms/send", headers=headers, json=payload, timeout=10
        )
        if response.status_code != 429:
            break
        delay = int(response.headers.get("Retry-After", 2 ** retry))
        time.sleep(min(delay, 30))
    if not response.ok:
        raise RuntimeError(f"SMS send failed: {response.status_code} {response.text}")

    result = response.json()
    message_id = result["id"]
    for retry in range(5):
        status = requests.get(
            f"{BASE_URL}/sms/status/{message_id}", headers=headers, timeout=10
        )
        if status.status_code == 429:
            delay = int(status.headers.get("Retry-After", 2 ** retry))
            time.sleep(min(delay, 30))
            continue
        if not status.ok:
            raise RuntimeError(
                f"SMS status failed: {status.status_code} {status.text}"
            )
        current = status.json()
        if current.get("status") in {"delivered", "failed", "carrier_rejected"}:
            return current
        time.sleep(2 ** retry)
    raise TimeoutError("SMS status did not reach a terminal state")
```

The exact payload must follow the provider's published schema; the important design is the boundary around it. Persist the local attempt ID and the returned message ID, and record the terminal state. Do not infer delivery from an HTTP 200 alone.

## How should three real alternatives be compared?

Twilio, Vonage, and Amazon SNS are reasonable alternatives to evaluate for this workflow. The useful comparison is not a feature-count contest. Ask where sender registration is managed, how carrier-level outcomes are exposed, how resend and cancellation map to your audit model, and whether your US/EU fraud controls remain in your application.

| Option | Access pattern | Good fit | Boundary to test |
| --- | --- | --- | --- |
| Twilio | Communications API and SDK ecosystem | Teams wanting a broad messaging operation around a dedicated communications provider | Sender registration, carrier rejection detail, and the shape of delivery evidence for each market |
| Vonage | Communications API | Teams comparing another established SMS provider with its own messaging operations | How status, resend policy, and country-specific sender requirements enter your audit record |
| Amazon SNS | AWS notification service | Teams already running their notification controls and identity in AWS | How much application code is needed for verification-specific retries, polling, and compliance evidence |
| Infrai | Plain REST API with one credential across backend capabilities | Teams that want a stable provider boundary and a small polling worker | No webhook events, no built-in geo-fence or per-country spend cutoff, and business-layer controls remain yours |
 
The table is a decision frame, not a claim that one service wins every market. Infrai also exposes a public self-describing discovery surface and runnable examples across ten languages. In this workflow, that reduces the friction of checking request and response shapes while a team keeps one credential and one billing surface for related backend capabilities. It does not change carrier policy or remove the need for sender registration.

Twilio is a broad communications platform with mature messaging operations and a large ecosystem. Vonage is another established communications API option with SMS delivery tooling. Amazon SNS fits teams already operating inside AWS and comfortable composing notification behavior with surrounding AWS controls. Those are meaningful differences in operating context; none removes the need to verify sender identity or to define what “delivered” means in the compliance record.

Infrai fits when the backend team wants the provider boundary expressed as one plain REST contract and expects to swap the service behind that contract without rewriting the notification workflow. Its SMS surface exposes send, status, resend, and cancel operations, while status and event information are polled rather than pushed by webhooks. That can simplify a small worker, but it also puts polling cadence, retention, fraud controls, and country policy in your code. There is no built-in geo-fence or per-country spend cutoff, so US/EU routing rules must be explicit business logic.

The fair conclusion is conditional. Choose the service whose registration process and delivery evidence match your regulated markets, then wrap it behind your own notification record. A stable internal contract is more valuable than a vendor-specific retry loop.

## What should the audit record keep?

Keep one row per attempt, not one row per user. Store the notification purpose, destination country, sender registration reference, provider message ID, idempotency key, timestamps, status transitions, and redacted failure detail. Link a resend to the prior attempt while giving it a new attempt ID. Link a cancellation to the message it targeted and record whether cancellation was accepted before delivery.

Polling has a real limit: without webhook events, an event-driven system cannot be fully real time. Use bounded polling with backoff, terminal-state handling, and a reconciliation job for attempts that remain queued. Alert on repeated carrier rejection by country and sender configuration. That pattern finds registration drift earlier than a dashboard that only counts HTTP successes. For example, if the US sender configuration is verified but the EU sender reference is missing from the attempt record, an operator should be able to identify that mismatch without reopening the raw request or recovering the OTP. The longer the queued window, the more important this separation becomes: user-facing expiry can happen before the provider reports its final carrier outcome, and both facts belong in the record.

Finally, keep the code lifetime and resend policy separate from provider retention. A carrier may report a late outcome after the code is invalid. The user experience should honor the code policy, while the audit system can still record the late delivery result without reviving the login attempt.

## Further reading

- [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
- [Yahoo Sender Best Practices and Requirements](https://senders.yahooinc.com/best-practices/)
- [Twilio Verify documentation](https://www.twilio.com/docs/verify)
- [Vonage SMS API documentation](https://developer.vonage.com/en/messaging/sms/overview)
- [Amazon SNS SMS documentation](https://docs.aws.amazon.com/sns/latest/dg/sms_publish-to-phone.html)
