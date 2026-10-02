"""Telegram notifier: a bot posts the alert into one or more chats or groups.

Setup (once, in Telegram):

1. Talk to @BotFather, send /newbot and copy the bot token it gives you
   (looks like ``123456789:AAH...``).
2. Add the bot to the group (or start a private chat with it and press Start).
3. Find the chat id: send any message in the group, then open
   ``https://api.telegram.org/bot<token>/getUpdates``; the id is under
   ``"chat": {"id": ...}``. Group ids are negative, e.g. ``-1001234567890``.
   A public channel can also be given as ``@channelname``.

Config:
    {"bot_token": "123456789:AAH...", "chat_ids": ["-1001234567890", "123456789"]}

``chat_ids`` may also be a single id or a comma separated string. The message
goes to every chat; if any of them fails, the error names that chat (the
others still get it).

Errors from Telegram are returned with its own description (e.g. "chat not
found" when the bot is not in the group, "Unauthorized" for a wrong token),
so the alert log says what to fix.
"""
from __future__ import annotations

import httpx

from .base import Notifier, NotifierError

_TIMEOUT = 10.0
API = "https://api.telegram.org"


def chat_list(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(i).strip() for i in items if str(i).strip()]


class TelegramNotifier(Notifier):
    key = "telegram"
    label = "Telegram"
    config_fields = {
        "bot_token": "token from @BotFather, e.g. 123456789:AAH...",
        "chat_ids": "list of chat / group ids (groups are negative, e.g. -1001234567890) or @channelname",
        "silent": "optional: true sends without a notification sound",
    }
    config_example = {"bot_token": "123456789:AAH...", "chat_ids": ["-1001234567890"]}

    def send(self, message: str) -> None:
        token = (self.config.get("bot_token") or "").strip()
        chats = chat_list(self.config.get("chat_ids") or self.config.get("chat_id"))
        if not token or not chats:
            raise NotifierError("telegram requires bot_token and at least one chat id in chat_ids")
        base = (self.config.get("base_url") or API).rstrip("/")
        errors = []
        for chat in chats:
            body = {"chat_id": chat, "text": message,
                    "disable_notification": bool(self.config.get("silent"))}
            try:
                resp = httpx.post(f"{base}/bot{token}/sendMessage", json=body, timeout=_TIMEOUT)
            except httpx.HTTPError as exc:
                raise NotifierError(f"cannot reach Telegram: {exc.__class__.__name__}") from exc
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if resp.status_code != 200 or not data.get("ok"):
                desc = data.get("description") or f"HTTP {resp.status_code}"
                if resp.status_code in (401, 404):  # Telegram's answer to an unknown token
                    raise NotifierError(f"telegram: {desc}. Check the bot token.")
                errors.append(f"chat {chat}: {desc}")
        if errors:
            raise NotifierError("telegram: " + "; ".join(errors))
