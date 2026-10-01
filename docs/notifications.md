# Notifications

Alerts are configured on the *Notifications* tab in two parts: **rules** decide
when to alert, **providers** decide where the message goes.

## Rules

| Condition | Fires when |
|---|---|
| `scrap_rate` | The current job's scrap rate (fail / total) reaches the threshold, e.g. `0.05` for 5% |
| `fail_count` | The current job's fail count reaches the threshold |
| `disconnected` | The camera can't be read or has gone offline |

A rule can apply to one camera or to all of them. Its **cooldown** (default
300 seconds) stops the same rule from firing again too soon.

Scrap-rate and fail-count rules are suppressed while a camera is idle or
manually stopped (see [Production state](user-guide.md#production-state)).
Disconnect alerts are always sent.

Every alert and its delivery result is recorded in the alert log.

## Providers

The WhatsApp provider lives in `app/notifiers/whatsapp.py` and has three
transports. Use **Test send** after adding one to confirm delivery.

### Important: WhatsApp groups need a gateway you run

Meta's official WhatsApp Cloud API **cannot post into a normal WhatsApp group
chat**; there is no official API for that. To alert a group you need a
WhatsApp gateway service that is logged into a WhatsApp account that is a
member of the group. **You have to set up and run that gateway yourself**
(or rent one); this app does not include one.

### `webhook` (recommended)

POSTs the message as JSON to any HTTP endpoint. Point it at your self-hosted
gateway (for example one built on whatsapp-web.js, Baileys or WAHA).

```json
{"transport": "webhook", "url": "http://gateway:3000/send",
 "headers": {"Authorization": "Bearer ..."},
 "payload_key": "message", "extra": {"chatId": "1234567890-123456@g.us"}}
```

### `greenapi`

Uses the third-party [Green API](https://green-api.com) group-send endpoint.

```json
{"transport": "greenapi", "id_instance": "...", "api_token": "...",
 "group_id": "1234567890-123456@g.us"}
```

### `cloud_api`

Meta's official Cloud API. Sends to **one phone number only**, not a group.

```json
{"transport": "cloud_api", "token": "...", "phone_number_id": "...",
 "to": "<recipient number>"}
```

Provider credentials are stored in the app's database. Protect database
access and backups accordingly.

## Adding a provider

Notifiers follow the same one-file pattern as protocols: add a file in
`app/notifiers/` implementing the `Notifier` base class and register it in
`app/notifiers/__init__.py`.
