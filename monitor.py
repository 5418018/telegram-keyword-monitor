"""Poll subscribed Telegram channels and send keyword alerts through a bot."""

from __future__ import annotations

import asyncio
import html
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

from matching import match_message


@dataclass(frozen=True)
class Settings:
    channels: list[str]
    keywords: list[str]
    urgent_keywords: list[str]
    exclude_keywords: list[str]
    regex_patterns: list[str]
    match_mode: str
    max_messages_per_channel: int


def _string_list(data: dict[str, Any], name: str) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON list")
    return [str(item).strip() for item in value if str(item).strip()]


def load_settings() -> Settings:
    raw = os.getenv("CONFIG_JSON", "").strip()
    if raw:
        data = json.loads(raw)
    else:
        path = Path(os.getenv("CONFIG_FILE", "config.json"))
        data = json.loads(path.read_text(encoding="utf-8"))

    channels = _string_list(data, "channels")
    if not channels:
        raise ValueError("At least one channel is required")

    max_messages = int(data.get("max_messages_per_channel", 100))
    if not 1 <= max_messages <= 500:
        raise ValueError("max_messages_per_channel must be between 1 and 500")

    return Settings(
        channels=channels,
        keywords=_string_list(data, "keywords"),
        urgent_keywords=_string_list(data, "urgent_keywords"),
        exclude_keywords=_string_list(data, "exclude_keywords"),
        regex_patterns=_string_list(data, "regex_patterns"),
        match_mode=str(data.get("match_mode", "any")),
        max_messages_per_channel=max_messages,
    )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "channels": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("channels"), dict):
            raise ValueError("invalid channels state")
        return data
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise RuntimeError(f"State file is damaged: {path}") from exc


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def message_link(entity: Any, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    return f"https://t.me/c/{int(entity.id)}/{message_id}"


def display_name(entity: Any, fallback: str) -> str:
    return str(
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or fallback
    )


def post_bot_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram Bot API error: {result}")


async def send_bot_message(token: str, chat_id: str, text: str) -> None:
    await asyncio.to_thread(post_bot_message, token, chat_id, text)


def alert_text(channel_name: str, message: Any, reasons: tuple[str, ...], link: str) -> str:
    body = (message.message or "").strip()
    if len(body) > 2600:
        body = body[:2597] + "..."
    reason_text = ", ".join(reasons)
    return (
        "🚨 <b>키워드 뉴스 알림</b>\n\n"
        f"<b>채널:</b> {html.escape(channel_name)}\n"
        f"<b>감지:</b> {html.escape(reason_text)}\n"
        f"<b>시간:</b> {html.escape(message.date.astimezone().strftime('%Y-%m-%d %H:%M'))}\n\n"
        f"{html.escape(body)}\n\n"
        f'<a href="{html.escape(link, quote=True)}">원문 열기</a>'
    )


async def run() -> int:
    settings = load_settings()
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session = require_env("TELEGRAM_SESSION")
    bot_token = require_env("BOT_TOKEN")
    chat_id = require_env("ALERT_CHAT_ID")
    state_path = Path(os.getenv("STATE_FILE", ".state/state.json"))
    state = load_state(state_path)
    channel_state: dict[str, int] = state["channels"]

    initialized: list[str] = []
    errors: list[str] = []
    alerts_sent = 0

    client = TelegramClient(StringSession(session), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is no longer authorized")

        for channel in settings.channels:
            try:
                entity = await client.get_entity(channel)
                key = str(entity.id)
                name = display_name(entity, channel)
                latest = await client.get_messages(entity, limit=1)
                latest_id = int(latest[0].id) if latest else 0

                if key not in channel_state:
                    channel_state[key] = latest_id
                    initialized.append(name)
                    continue

                last_id = int(channel_state[key])
                highest_seen = last_id
                messages = []
                async for message in client.iter_messages(
                    entity,
                    min_id=last_id,
                    reverse=True,
                    limit=settings.max_messages_per_channel,
                ):
                    messages.append(message)

                for message in messages:
                    highest_seen = max(highest_seen, int(message.id))
                    result = match_message(
                        message.message or "",
                        keywords=settings.keywords,
                        urgent_keywords=settings.urgent_keywords,
                        exclude_keywords=settings.exclude_keywords,
                        regex_patterns=settings.regex_patterns,
                        match_mode=settings.match_mode,
                    )
                    if not result.matched:
                        continue
                    link = message_link(entity, int(message.id))
                    await send_bot_message(
                        bot_token,
                        chat_id,
                        alert_text(name, message, result.reasons, link),
                    )
                    alerts_sent += 1
                    await asyncio.sleep(0.15)

                channel_state[key] = max(highest_seen, latest_id if not messages else 0)
            except Exception as exc:  # Continue other channels, then report failures.
                errors.append(f"{channel}: {type(exc).__name__}: {exc}")

        save_state(state_path, state)

        if initialized:
            names = "\n".join(f"• {html.escape(name)}" for name in initialized)
            await send_bot_message(
                bot_token,
                chat_id,
                "✅ <b>채널 감시 기준점 저장 완료</b>\n\n"
                "과거 글은 알리지 않고 다음 실행부터 새 글을 검사합니다.\n\n"
                + names,
            )
        if errors:
            details = "\n".join(html.escape(item) for item in errors[:10])
            await send_bot_message(
                bot_token,
                chat_id,
                f"⚠️ <b>일부 채널 확인 실패</b>\n\n<code>{details}</code>",
            )
            print("\n".join(errors), file=sys.stderr)

        print(
            f"Checked {len(settings.channels)} channel(s); "
            f"sent {alerts_sent} alert(s); {len(errors)} error(s)."
        )
        return 1 if errors and len(errors) == len(settings.channels) else 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except Exception as exc:
        print(f"Fatal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

