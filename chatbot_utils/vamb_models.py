from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None

    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(raw)
    except Exception:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except Exception:
            continue

    return None


class VambMessageSender(str, Enum):
    bot = "bot"
    user = "user"
    agent = "agent"


class VambMessageButtonIcon(str, Enum):
    info = "info"
    person = "person"


class VambMessageConversationClosedReason(str, Enum):
    bot_not_reachable = "bot_not_reachable"
    user_not_reachable = "user_not_reachable"
    agent_not_reachable = "agent_not_reachable"
    user_exited = "user_exited"
    agent_exited = "agent_exited"
    other = "other"


@dataclass
class VambMessageSenderInfo:
    name: Optional[str] = None
    avatar_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["VambMessageSenderInfo"]:
        if data is None:
            return None
        return cls(
            name=data.get("name"),
            avatar_url=data.get("avatar_url"),
        )


@dataclass
class VambMessageButton:
    title: str
    payload: str
    icon: Optional[VambMessageButtonIcon] = None
    auto_disable: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VambMessageButton":
        icon_raw = data.get("icon")
        icon = VambMessageButtonIcon(icon_raw) if isinstance(icon_raw, str) else None
        return cls(
            title=data["title"],
            payload=data["payload"],
            icon=icon,
            auto_disable=data.get("auto_disable"),
        )


@dataclass
class VambMessageDeeplink:
    title: str
    path: str
    automatic_open: bool = False
    open_delay_ms: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["VambMessageDeeplink"]:
        if data is None:
            return None
        return cls(
            title=data["title"],
            path=data["path"],
            automatic_open=bool(data.get("automatic_open", False)),
            open_delay_ms=data.get("open_delay_ms"),
        )


@dataclass
class VambMessage:
    id: str
    timestamp: datetime.datetime
    schema_version: str = "1.0"
    sender: VambMessageSender = VambMessageSender.bot
    sender_info: Optional[VambMessageSenderInfo] = None
    rich_text: str = ""
    plain_text: str = ""
    buttons: Optional[List[VambMessageButton]] = None
    deeplink: Optional[VambMessageDeeplink] = None
    widget: Optional[Dict[str, Any]] = None
    expects_answer: Optional[bool] = None
    conversation_closed: Optional[Union[bool, VambMessageConversationClosedReason]] = None
    ssml_text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VambMessage":
        sender = (
            VambMessageSender(data["sender"])
            if isinstance(data.get("sender"), str)
            else VambMessageSender.bot
        )

        buttons_raw = data.get("buttons")
        buttons = [VambMessageButton.from_dict(b) for b in buttons_raw] if isinstance(buttons_raw, list) else None

        deeplink = VambMessageDeeplink.from_dict(data.get("deeplink"))
        sender_info = VambMessageSenderInfo.from_dict(data.get("sender_info"))

        conv_closed_raw = data.get("conversation_closed")
        if isinstance(conv_closed_raw, str):
            conv_closed: Optional[Union[bool, VambMessageConversationClosedReason]] = (
                VambMessageConversationClosedReason(conv_closed_raw)
            )
        elif isinstance(conv_closed_raw, bool):
            conv_closed = conv_closed_raw
        else:
            conv_closed = None

        timestamp = _parse_iso_dt(data.get("timestamp")) or datetime.datetime.utcnow()

        return cls(
            id=str(data["id"]),
            timestamp=timestamp,
            schema_version=str(data.get("schema_version", "1.0")),
            sender=sender,
            sender_info=sender_info,
            rich_text=str(data.get("rich_text", "")),
            plain_text=str(data.get("plain_text", "")),
            buttons=buttons,
            deeplink=deeplink,
            widget=data.get("widget"),
            expects_answer=data.get("expects_answer"),
            conversation_closed=conv_closed,
            ssml_text=data.get("ssml_text"),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        )


@dataclass
class VambMessageMetadata:
    message_id: str
    maia_metadata_version: str
    maia_metadata: Any

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VambMessageMetadata":
        return cls(
            message_id=str(data.get("message_id", "")),
            maia_metadata_version=str(data.get("maia_metadata_version", "1.0")),
            maia_metadata=data.get("maia_metadata"),
        )


@dataclass
class VambGetConversationMessagesResponse:
    conversation_id: str
    messages: List[VambMessage]
    handed_to_agent: Optional[bool] = None
    mirrored_to_infobip: Optional[bool] = None
    after: Optional[datetime.datetime] = None
    messages_schema_version: str = "1.0"
    messages_metadata: Optional[List[VambMessageMetadata]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VambGetConversationMessagesResponse":
        raw_messages = data.get("new_messages")
        if not isinstance(raw_messages, list):
            raw_messages = data.get("NewMessagesWithVerboseInfo")
        if not isinstance(raw_messages, list):
            raw_messages = []

        messages = [VambMessage.from_dict(m) for m in raw_messages]

        metadata_raw = data.get("new_messages_metadata")
        if not isinstance(metadata_raw, list):
            metadata_raw = data.get("NewMessagesMetadata")

        if isinstance(metadata_raw, list):
            messages_metadata = [VambMessageMetadata.from_dict(m) for m in metadata_raw]
        else:
            messages_metadata = []
            for message in raw_messages:
                if not isinstance(message, dict):
                    continue
                message_metadata = message.get("metadata")
                if not isinstance(message_metadata, dict):
                    continue
                message_id = message_metadata.get("message_id") or message.get("id")
                if not message_id:
                    continue
                messages_metadata.append(
                    VambMessageMetadata(
                        message_id=str(message_id),
                        maia_metadata_version=str(message_metadata.get("maia_metadata_version", "1.0")),
                        maia_metadata=message_metadata.get("maia_metadata"),
                    )
                )

        conversation_id = data.get("conversation_id") or data.get("ConversationId") or ""

        return cls(
            conversation_id=str(conversation_id),
            messages=messages,
            handed_to_agent=data.get("handed_to_agent"),
            mirrored_to_infobip=data.get("mirrored_to_infobip"),
            after=_parse_iso_dt(data.get("after")),
            messages_schema_version=str(data.get("messages_schema_version", "1.0")),
            messages_metadata=messages_metadata or None,
        )
