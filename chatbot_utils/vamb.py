from __future__ import annotations

import os
import pickle
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from .vamb_models import (
    VambGetConversationMessagesResponse,
    VambMessage,
    VambMessageMetadata,
)


class JWTVambManager:
    _instance: Optional["JWTVambManager"] = None
    _token_file: str = "tokens.pkl"
    _base_url: str = "https://rbhr-raia.maia-staging.rbigroup.cloud/vamb-channel"

    def __new__(cls) -> "JWTVambManager":
        if cls._instance is None:
            cls._instance = super(JWTVambManager, cls).__new__(cls)
            cls._instance._tokens = cls._load_tokens()
        return cls._instance

    @staticmethod
    def _load_tokens() -> Dict[str, Any]:
        if not os.path.exists(JWTVambManager._token_file):
            return {}

        file_age_seconds = time.time() - os.path.getmtime(JWTVambManager._token_file)
        if file_age_seconds >= 3600:
            try:
                os.remove(JWTVambManager._token_file)
            except OSError:
                pass
            return {}

        try:
            with open(JWTVambManager._token_file, "rb") as file:
                tokens: Dict[str, Any] = pickle.load(file)
        except Exception:
            try:
                os.remove(JWTVambManager._token_file)
            except OSError:
                pass
            return {}

        expires_at = tokens.get("expires_at")
        if isinstance(expires_at, (int, float)) and time.time() >= float(expires_at):
            try:
                os.remove(JWTVambManager._token_file)
            except OSError:
                pass
            return {}

        return tokens

    @staticmethod
    def _save_tokens(tokens: Dict[str, Any]) -> None:
        with open(JWTVambManager._token_file, "wb") as file:
            pickle.dump(tokens, file)

    def _get_anonymous_token(self) -> None:
        response = requests.get(f"{self._base_url}/anonymous-token", timeout=20)
        if response.status_code == 200:
            token_data = response.json()
            self._tokens = {
                "access_token": token_data["token"],
                "refresh_token": token_data.get("refresh_token"),
                "expires_at": time.time() + 3600,
            }
            self._save_tokens(self._tokens)
            return

        raise Exception(f"Failed to get anonymous token: HTTP {response.status_code}")

    def _refresh_anonymous_token(self) -> None:
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise Exception("No refresh token available to refresh anonymous token.")

        headers = {"x-anonymous-refresh-token": refresh_token}
        response = requests.get(f"{self._base_url}/refreshed-anonymous-token", headers=headers, timeout=20)
        if response.status_code == 200:
            token_data = response.json()
            self._tokens["access_token"] = token_data["token"]
            self._tokens["expires_at"] = time.time() + 3600
            self._save_tokens(self._tokens)
            return

        raise Exception(f"Failed to refresh anonymous token: HTTP {response.status_code}")

    def get_access_token(self) -> str:
        expires_at = self._tokens.get("expires_at")
        token_missing_or_expired = (
            "access_token" not in self._tokens
            or not isinstance(expires_at, (int, float))
            or time.time() >= float(expires_at)
        )

        if token_missing_or_expired:
            try:
                if self._tokens.get("refresh_token"):
                    self._refresh_anonymous_token()
                else:
                    self._get_anonymous_token()
            except Exception:
                self._get_anonymous_token()

        return str(self._tokens["access_token"])


class ConversationLog:
    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.messages: List[VambMessage] = []
        self.metadata: List[VambMessageMetadata] = []

    def add(self, message: VambMessage, metadata: Optional[VambMessageMetadata]) -> None:
        self.messages.append(message)
        if metadata:
            self.metadata.append(metadata)

    def __repr__(self) -> str:
        return (
            f"ConversationLog(conversation_id={self.conversation_id}, "
            f"messages={len(self.messages)}, metadata={len(self.metadata)})"
        )


class MetadataManager:
    def __init__(self):
        self.conversation_logs: Dict[str, ConversationLog] = {}

    def store_conversation(self, response: VambGetConversationMessagesResponse) -> None:
        conversation_id = response.conversation_id
        log = self.conversation_logs.setdefault(conversation_id, ConversationLog(conversation_id))

        metadata_by_id: Dict[str, VambMessageMetadata] = {}
        if response.messages_metadata:
            metadata_by_id = {item.message_id: item for item in response.messages_metadata}

        for message in response.messages:
            log.add(message, metadata_by_id.get(message.id))

    def get_conversation_log(self, conversation_id: str) -> Optional[ConversationLog]:
        return self.conversation_logs.get(conversation_id)

    def __repr__(self) -> str:
        return f"MetadataManager(conversations={len(self.conversation_logs)})"


class VambConversationObserver(ABC):
    @abstractmethod
    def on_conversation_initiated(self, conversation_id: str) -> None:
        pass

    @abstractmethod
    def on_message_sent(self, message: str) -> None:
        pass


class VambConversation:
    def __init__(self, jwt_manager: JWTVambManager, metadata_manager: MetadataManager):
        self.jwt_manager = jwt_manager
        self.metadata_manager = metadata_manager
        self.observers: List[VambConversationObserver] = []
        self.conversation_id: Optional[str] = None

    def add_observer(self, observer: VambConversationObserver) -> None:
        self.observers.append(observer)

    def _notify_conversation_initiated(self) -> None:
        for observer in self.observers:
            observer.on_conversation_initiated(self.conversation_id or "")

    def _notify_message_sent(self, message: str) -> None:
        for observer in self.observers:
            observer.on_message_sent(message)

    def initiate_conversation(self) -> None:
        url = f"{JWTVambManager._base_url}/conversation"
        headers = {
            "x-anonymous-token": self.jwt_manager.get_access_token(),
            "Content-Type": "application/json",
        }
        payload = {"mirror_to_infobip": False}

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            self.conversation_id = data["conversation_id"]
            self._notify_conversation_initiated()
            return

        raise Exception(f"Failed to initiate conversation: HTTP {response.status_code}")

    def send_message(self, message: str) -> VambGetConversationMessagesResponse:
        if not self.conversation_id:
            raise Exception("No conversation initiated")

        url = f"{JWTVambManager._base_url}/conversation-messages/{self.conversation_id}"
        headers = {
            "x-anonymous-token": self.jwt_manager.get_access_token(),
            "Content-Type": "application/json",
        }
        payload = {
            "text": message,
            "input_type": "text",
            "mirror_to_infobip": False,
        }

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            parsed = VambGetConversationMessagesResponse.from_dict(response.json())
            self.metadata_manager.store_conversation(parsed)
            self._notify_message_sent(message)
            return parsed

        try:
            server_msg = response.json()
        except Exception:
            server_msg = response.text

        raise Exception(
            f"Failed to send message: HTTP {response.status_code}, server response: {server_msg}"
        )
