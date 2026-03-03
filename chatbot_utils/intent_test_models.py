from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .jira import JiraIssue


@dataclass
class DialogIntentTestCase:
    question: str
    expected_intent: Optional[str] = None


@dataclass
class DialogIntentTestSet:
    dialog_name: str
    topic: str
    test_file_path: str
    cases: List[DialogIntentTestCase]


@dataclass
class IntentTestResult:
    dialog_name: str
    topic: str
    test_file_path: str
    question_index: int
    question: str
    expected_intent: str
    detected_intent: Optional[str]
    passed: bool
    conversation_id: Optional[str] = None
    metadata_raw: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


@dataclass
class IntentTestReport:
    results: List[IntentTestResult] = field(default_factory=list)

    def add_result(self, result: IntentTestResult) -> None:
        self.results.append(result)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if not result.passed)

    @property
    def total_count(self) -> int:
        return len(self.results)

    def to_summary_dict(self) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        return {
            "generated_at": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "generated_at_iso": now_utc.isoformat(),
            "total_tests": self.total_count,
            "passed_tests": self.passed_count,
            "failed_tests": self.failed_count,
            "results": [
                {
                    "dialog_name": result.dialog_name,
                    "topic": result.topic,
                    "test_file_path": result.test_file_path,
                    "question_index": result.question_index,
                    "question": result.question,
                    "expected_intent": result.expected_intent,
                    "detected_intent": result.detected_intent,
                    "passed": result.passed,
                    "conversation_id": result.conversation_id,
                    "error_message": result.error_message,
                    "metadata_raw": result.metadata_raw,
                }
                for result in self.results
            ],
        }

    def write_summary_json(self, output_path: str) -> Dict[str, Any]:
        payload = self.to_summary_dict()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        return payload

    def to_jira_issues(self) -> List[JiraIssue]:
        grouped: Dict[str, List[IntentTestResult]] = {}
        for result in self.results:
            if result.passed:
                continue
            grouped.setdefault(result.dialog_name, []).append(result)

        issues: List[JiraIssue] = []
        for dialog_name, dialog_failures in grouped.items():
            first = dialog_failures[0]
            details: List[str] = []
            for item in dialog_failures:
                details.extend(
                    [
                        f"- Topic: {item.topic}",
                        f"- Test file: {item.test_file_path}",
                        f"- Question index: {item.question_index}",
                        f"- Question: {item.question}",
                        f"- Expected intent: {item.expected_intent}",
                        f"- Detected intent: {item.detected_intent or 'N/A'}",
                        f"- Conversation ID: {item.conversation_id or 'N/A'}",
                        f"- Error: {item.error_message or 'N/A'}",
                        "",
                    ]
                )

            description = "\n".join(
                [
                    "Intent recognition test mismatch detected.",
                    "",
                    f"Dialog: {dialog_name}",
                    f"Topic: {first.topic}",
                    f"Failed test cases: {len(dialog_failures)}",
                    "",
                    "Details:",
                    *details,
                ]
            )

            metadata_items = [
                {
                    "topic": item.topic,
                    "test_file_path": item.test_file_path,
                    "question_index": item.question_index,
                    "question": item.question,
                    "expected_intent": item.expected_intent,
                    "detected_intent": item.detected_intent,
                    "conversation_id": item.conversation_id,
                    "error_message": item.error_message,
                }
                for item in dialog_failures
            ]

            issues.append(
                JiraIssue(
                    summary=f"Intent mismatch in dialog '{dialog_name}'",
                    description=description,
                    labels=["chatbot", "intent-test", "automated-validation"],
                    issue_type="Bug",
                    priority="Medium",
                    metadata={
                        "dialog_name": dialog_name,
                        "topic": first.topic,
                        "failure_count": len(dialog_failures),
                        "items": metadata_items,
                    },
                )
            )

        return issues


class IntentExtractor:
    KEY_CANDIDATES = {
        "detected_route",
        "route",
        "intent",
        "intent_name",
        "detected_intent",
        "predicted_intent",
        "top_intent",
    }

    def extract(self, metadata: Any) -> Optional[str]:
        if not isinstance(metadata, dict):
            return None

        maia_metadata = metadata.get("maia_metadata")
        if maia_metadata is None:
            maia_metadata = metadata.get("maina_metadata")

        intent = self._extract_from_payload(maia_metadata)
        if intent:
            return intent

        return self._extract_from_payload(metadata)

    def _extract_from_payload(self, payload: Any) -> Optional[str]:
        candidates = list(self._yield_key_values(payload))
        if not candidates:
            return None

        ranked = sorted(candidates, key=self._candidate_score, reverse=True)
        return ranked[0][1]

    def _yield_key_values(self, payload: Any) -> Iterable[tuple[str, str]]:
        if isinstance(payload, dict):
            for key, value in payload.items():
                lowered = str(key).strip().lower()

                if lowered in self.KEY_CANDIDATES and isinstance(value, str) and value.strip():
                    yield lowered, value.strip()

                if lowered == "intents" and isinstance(value, list):
                    top_name = self._extract_top_intent_from_list(value)
                    if top_name:
                        yield "top_intent", top_name

                yield from self._yield_key_values(value)

        elif isinstance(payload, list):
            for item in payload:
                yield from self._yield_key_values(item)

    @staticmethod
    def _candidate_score(candidate: tuple[str, str]) -> int:
        key, value = candidate
        score = 0
        if key == "detected_route":
            score += 200
        elif key == "route":
            score += 160
        if key in {"intent", "intent_name", "detected_intent", "predicted_intent", "top_intent"}:
            score += 100
        if value:
            score += 10
        return score

    @staticmethod
    def _extract_top_intent_from_list(intents: List[Any]) -> Optional[str]:
        ranked: List[tuple[float, str]] = []
        for item in intents:
            if not isinstance(item, dict):
                continue

            name = item.get("name") or item.get("intent")
            if not isinstance(name, str) or not name.strip():
                continue

            score_raw = item.get("score", item.get("confidence", 0.0))
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = 0.0

            ranked.append((score, name.strip()))

        if not ranked:
            return None

        ranked.sort(key=lambda row: row[0], reverse=True)
        return ranked[0][1]
