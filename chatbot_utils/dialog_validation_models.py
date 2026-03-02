import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .jira import JiraIssue

class DialogSection(str, Enum):
    TEXT = "TEXT"
    BUTTON = "BUTTON"


class ReferenceType(str, Enum):
    URL = "URL"
    DIALOG = "DIALOG"


class ValidationErrorCode(str, Enum):
    URL_UNREACHABLE = "URL_UNREACHABLE"
    RESOURCE_UNREACHABLE = "RESOURCE_UNREACHABLE"
    DIALOG_REFERENCE_NOT_FOUND = "DIALOG_REFERENCE_NOT_FOUND"
    PAYLOAD_DIALOG_FORMAT_INVALID = "PAYLOAD_DIALOG_FORMAT_INVALID"


@dataclass
class ValidationFailure:
    dialog_name: str
    answer_index: int
    content_source: str
    content_index: int
    reference_type: str
    value: str
    normalized_value: str
    error_code: str
    error_message: str
    status_code: Optional[int] = None
    response_time_ms: Optional[int] = None


class DialogValidationReport:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger
        self.failures: List[ValidationFailure] = []

    @property
    def is_clean(self) -> bool:
        return not self.failures

    def add_failure(self, failure: ValidationFailure) -> None:
        self.failures.append(failure)

    def add_url_failure(
        self,
        dialog_name: str,
        answer_index: int,
        content_source: DialogSection,
        content_index: int,
        value: str,
        normalized_value: str,
        is_resource: bool,
        error_message: str,
        status_code: Optional[int],
        response_time_ms: Optional[int],
    ) -> None:
        self.add_failure(
            ValidationFailure(
                dialog_name=dialog_name,
                answer_index=answer_index,
                content_source=content_source.value,
                content_index=content_index,
                reference_type=ReferenceType.URL.value,
                value=value,
                normalized_value=normalized_value,
                error_code=(
                    ValidationErrorCode.RESOURCE_UNREACHABLE.value
                    if is_resource
                    else ValidationErrorCode.URL_UNREACHABLE.value
                ),
                error_message=error_message,
                status_code=status_code,
                response_time_ms=response_time_ms,
            )
        )

    def add_dialog_reference_failure(
        self,
        dialog_name: str,
        answer_index: int,
        content_source: DialogSection,
        content_index: int,
        value: str,
        normalized_value: str,
    ) -> None:
        self.add_failure(
            ValidationFailure(
                dialog_name=dialog_name,
                answer_index=answer_index,
                content_source=content_source.value,
                content_index=content_index,
                reference_type=ReferenceType.DIALOG.value,
                value=value,
                normalized_value=normalized_value,
                error_code=ValidationErrorCode.DIALOG_REFERENCE_NOT_FOUND.value,
                error_message=f"Referenced dialog does not exist: {normalized_value}",
            )
        )

    def add_payload_format_failure(
        self,
        dialog_name: str,
        answer_index: int,
        content_source: DialogSection,
        content_index: int,
        value: str,
    ) -> None:
        self.add_failure(
            ValidationFailure(
                dialog_name=dialog_name,
                answer_index=answer_index,
                content_source=content_source.value,
                content_index=content_index,
                reference_type=ReferenceType.DIALOG.value,
                value=value,
                normalized_value=value,
                error_code=ValidationErrorCode.PAYLOAD_DIALOG_FORMAT_INVALID.value,
                error_message="Unsupported dialog payload format",
            )
        )

    def failure_by_code(self) -> Dict[str, int]:
        by_code: Dict[str, int] = defaultdict(int)
        for failure in self.failures:
            by_code[failure.error_code] += 1
        return dict(by_code)

    def to_summary_payload(self, dialog_count: int) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        return {
            "generated_at": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "generated_at_iso": now_utc.isoformat(),
            "dialog_count": dialog_count,
            "failure_count": len(self.failures),
            "is_clean": self.is_clean,
            "failure_by_code": self.failure_by_code(),
            "failures": [asdict(failure) for failure in self.failures],
        }

    def write_summary_json(self, dialog_count: int, output_path: str) -> Dict[str, Any]:
        payload = self.to_summary_payload(dialog_count)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

        if self.logger:
            self.logger.info("Summary report written: %s", output_path)

        return payload

    def to_jira_issues(self) -> List[JiraIssue]:
        grouped: dict[tuple[str, str], list[ValidationFailure]] = defaultdict(list)
        for failure in self.failures:
            grouped[(failure.dialog_name, failure.error_code)].append(failure)

        issues: List[JiraIssue] = []
        for (dialog_name, error_code), items in grouped.items():
            values = sorted({item.normalized_value for item in items})[:15]
            summary = f"Dialog validation: {dialog_name} - {error_code}"
            description_lines = [
                f"Dialog: {dialog_name}",
                f"Error code: {error_code}",
                f"Occurrences: {len(items)}",
                "Affected values:",
                *[f"- {value}" for value in values],
            ]

            issues.append(
                JiraIssue(
                    summary=summary,
                    description="\n".join(description_lines),
                    labels=["chatbot", "dialog-validation", error_code.lower()],
                    issue_type="Bug",
                    metadata={
                        "dialog_name": dialog_name,
                        "error_code": error_code,
                        "occurrences": len(items),
                        "items": [asdict(item) for item in items],
                    },
                )
            )

        return issues


class PayloadParser:
    DIALOG_PAYLOAD_REGEX = re.compile(
        r'^/dialog\{\{\s*"dialog_id"\s*:\s*"([^"]+)"\s*\}\}$'
    )

    def extract_dialog_id(self, payload: str) -> Optional[str]:
        if not payload:
            return None

        match = self.DIALOG_PAYLOAD_REGEX.match(payload.strip())
        if not match:
            return None

        return match.group(1).strip()


class UrlChecker:
    MARKDOWN_URL_REGEX = re.compile(r"\[.*?\]\((https?://[^\s)]+)\)")
    PLAIN_URL_REGEX = re.compile(r"https?://[^\s)]+")
    RESOURCE_URL_REGEX = re.compile(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx)$")

    def __init__(self, timeout_seconds: int = 7, logger: Optional[logging.Logger] = None):
        self.timeout_seconds = timeout_seconds
        self.logger = logger
        self._cache: Dict[str, tuple[bool, Optional[int], Optional[str], int]] = {}

    @staticmethod
    def is_url(value: str) -> bool:
        return isinstance(value, str) and (
            value.startswith("http://") or value.startswith("https://")
        )

    def extract_urls_from_text(self, text: str) -> List[str]:
        if not text:
            return []

        markdown_urls = self.MARKDOWN_URL_REGEX.findall(text)
        plain_urls = self.PLAIN_URL_REGEX.findall(text)

        unique: List[str] = []
        seen: set[str] = set()
        for url in markdown_urls + plain_urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        return unique

    def is_resource_url(self, url: str) -> bool:
        path = url.lower().split("?", 1)[0]
        return bool(self.RESOURCE_URL_REGEX.search(path))

    def check_url(self, url: str) -> tuple[bool, Optional[int], Optional[str], int]:
        cached = self._cache.get(url)
        if cached is not None:
            return cached

        start = time.perf_counter()
        try:
            response = requests.head(url, allow_redirects=True, timeout=self.timeout_seconds)
            if response.status_code >= 400 or response.status_code in (405, 501):
                response = requests.get(url, allow_redirects=True, timeout=self.timeout_seconds)

            elapsed = int((time.perf_counter() - start) * 1000)
            if response.status_code >= 400:
                result = (False, response.status_code, f"HTTP {response.status_code}", elapsed)
            else:
                result = (True, response.status_code, None, elapsed)
        except requests.RequestException as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            result = (False, None, str(exc), elapsed)
            if self.logger:
                self.logger.debug("URL check request exception for %s: %s", url, exc)

        self._cache[url] = result
        return result
