"""Shared owner-delivery settings for WhatsApp-backed tools."""

from __future__ import annotations

from typing import Any


SUPPORTED_WHATSAPP_TOOL_DELIVERY_CHANNELS = ("whatsapp", "telegram")
DEFAULT_WHATSAPP_TOOL_DELIVERY_CHANNELS: tuple[str, ...] = ()


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_whatsapp_tool_delivery_channels(
    value: Any,
    *,
    fallback: tuple[str, ...] = DEFAULT_WHATSAPP_TOOL_DELIVERY_CHANNELS,
) -> list[str]:
    explicit_iterable = isinstance(value, (list, tuple, set))
    if explicit_iterable:
        raw_channels = list(value)
    elif isinstance(value, str):
        lowered = normalize_text(value).lower()
        if lowered in {"both", "all", "whatsapp+telegram", "whatsapp_telegram"}:
            raw_channels = ["whatsapp", "telegram"]
        else:
            raw_channels = [part.strip() for part in lowered.replace("+", ",").split(",")]
    else:
        raw_channels = []

    channels: list[str] = []
    for channel in raw_channels:
        normalized = normalize_text(channel).lower()
        if normalized in SUPPORTED_WHATSAPP_TOOL_DELIVERY_CHANNELS and normalized not in channels:
            channels.append(normalized)

    if explicit_iterable:
        return channels
    if channels:
        return channels
    return [channel for channel in fallback if channel in SUPPORTED_WHATSAPP_TOOL_DELIVERY_CHANNELS]


def normalize_whatsapp_tool_delivery_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    channels_source = source.get("deliveryChannels")
    if channels_source in (None, ""):
        channels_source = source.get("delivery_channels")
    if channels_source in (None, ""):
        channels_source = source.get("deliveryChannel")
    if channels_source in (None, ""):
        channels_source = source.get("delivery_channel")

    return {
        "deliveryChannels": normalize_whatsapp_tool_delivery_channels(channels_source),
        "telegramChatId": normalize_text(source.get("telegramChatId") or source.get("telegram_chat_id")),
    }


def whatsapp_tool_delivery_uses_whatsapp(settings: dict[str, Any] | None = None) -> bool:
    return "whatsapp" in normalize_whatsapp_tool_delivery_settings(settings)["deliveryChannels"]


def whatsapp_tool_delivery_uses_telegram(settings: dict[str, Any] | None = None) -> bool:
    return "telegram" in normalize_whatsapp_tool_delivery_settings(settings)["deliveryChannels"]


__all__ = [
    "DEFAULT_WHATSAPP_TOOL_DELIVERY_CHANNELS",
    "SUPPORTED_WHATSAPP_TOOL_DELIVERY_CHANNELS",
    "normalize_whatsapp_tool_delivery_channels",
    "normalize_whatsapp_tool_delivery_settings",
    "whatsapp_tool_delivery_uses_telegram",
    "whatsapp_tool_delivery_uses_whatsapp",
]
