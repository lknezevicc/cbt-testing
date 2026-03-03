from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .intent_test_models import (
    DialogIntentTestCase,
    DialogIntentTestSet,
    IntentExtractor,
    IntentTestReport,
    IntentTestResult,
)
from .intent_test_pdf_report import generate_intent_test_pdf
from .jira import publish_jira_bugs, save_jira_issues
from .logging_utils import use_logging
from .scope_models import Dialog, parse_yaml_to_dialog
from .vamb import JWTVambManager, MetadataManager, VambConversation

logger = use_logging("test_intent_recognition", log_file="logs/test_intent_recognition.log")


@dataclass
class DialogWithSource:
    dialog: Dialog
    file_path: str


@dataclass
class IntentTestRunnerConfig:
    dialogs_dir: str


class DialogTestSetLoader:
    def __init__(self, dialogs_dir: str):
        self.dialogs_dir = dialogs_dir

    def load(self) -> Tuple[List[DialogWithSource], List[DialogIntentTestSet]]:
        dialogs = self._load_dialogs_with_source()
        test_sets = self._load_test_sets(dialogs)
        return dialogs, test_sets

    def _load_dialogs_with_source(self) -> List[DialogWithSource]:
        collected: List[DialogWithSource] = []

        for root, _, files in os.walk(self.dialogs_dir):
            for file_name in files:
                if not file_name.endswith((".yaml", ".yml")):
                    continue

                file_path = os.path.join(root, file_name)
                with open(file_path, "r", encoding="utf-8") as file:
                    try:
                        data = yaml.safe_load(file)
                        if not isinstance(data, dict):
                            continue
                        dialog = parse_yaml_to_dialog(data)
                        collected.append(DialogWithSource(dialog=dialog, file_path=file_path))
                    except Exception as exc:
                        logger.warning("Failed to parse dialog file %s: %s", file_path, exc)

        return collected

    @staticmethod
    def _resolve_test_file_path(dialog_file_path: str, dialog_name: str) -> str:
        dialog_path = Path(dialog_file_path)
        return str(dialog_path.parent / "test" / f"{dialog_name}.json")

    @staticmethod
    def _parse_test_cases(raw: Any, default_expected_intent: str) -> List[DialogIntentTestCase]:
        raw_cases = raw.get("questions") if isinstance(raw, dict) else raw

        if not isinstance(raw_cases, list):
            raise ValueError("Test JSON must contain a list under 'questions' or be a list itself")

        parsed: List[DialogIntentTestCase] = []
        for item in raw_cases:
            if isinstance(item, str):
                parsed.append(
                    DialogIntentTestCase(
                        question=item.strip(),
                        expected_intent=default_expected_intent,
                    )
                )
                continue

            if isinstance(item, dict):
                question = str(item.get("question", "")).strip()
                if not question:
                    continue
                expected_intent = str(item.get("expected_intent", default_expected_intent)).strip()
                parsed.append(DialogIntentTestCase(question=question, expected_intent=expected_intent))
                continue

            raise ValueError("Each question must be either string or object")

        return parsed

    def _load_test_sets(self, dialogs: List[DialogWithSource]) -> List[DialogIntentTestSet]:
        test_sets: List[DialogIntentTestSet] = []

        for wrapped in dialogs:
            dialog = wrapped.dialog
            if not dialog.is_routable:
                logger.debug("Skipping non-routable dialog: %s", dialog.name)
                continue

            test_file_path = self._resolve_test_file_path(wrapped.file_path, dialog.name)
            if not os.path.exists(test_file_path):
                logger.debug("No test JSON for dialog %s at %s", dialog.name, test_file_path)
                continue

            try:
                with open(test_file_path, "r", encoding="utf-8") as file:
                    raw = json.load(file)
                cases = self._parse_test_cases(raw, default_expected_intent=dialog.name)
            except Exception as exc:
                logger.warning(
                    "Invalid test JSON for dialog %s at %s: %s",
                    dialog.name,
                    test_file_path,
                    exc,
                )
                continue

            if not cases:
                continue

            test_sets.append(
                DialogIntentTestSet(
                    dialog_name=dialog.name,
                    topic=dialog.topic,
                    test_file_path=test_file_path,
                    cases=cases,
                )
            )

        return test_sets


class IntentDetectionService:
    def __init__(self, extractor: Optional[IntentExtractor] = None):
        self.extractor = extractor or IntentExtractor()

    def extract_detected_intent(self, response: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        messages_metadata = list(getattr(response, "messages_metadata", None) or [])

        for metadata in messages_metadata:
            raw = self._metadata_object_to_raw(metadata)
            extracted = self.extractor.extract(raw)
            if extracted:
                return extracted.strip(), raw

        for message in getattr(response, "messages", []) or []:
            message_metadata = getattr(message, "metadata", None)
            if not isinstance(message_metadata, dict):
                continue

            maia_metadata = message_metadata.get("maia_metadata")
            raw = {
                "message_id": message_metadata.get("message_id") or getattr(message, "id", None),
                "maia_metadata": maia_metadata,
                "maina_metadata": maia_metadata,
                "maia_metadata_version": message_metadata.get("maia_metadata_version", "1.0"),
                "raw_message_metadata": message_metadata,
            }
            extracted = self.extractor.extract(raw)
            if extracted:
                return extracted.strip(), raw

        return None, None

    @staticmethod
    def intents_match(expected: Optional[str], detected: Optional[str]) -> bool:
        return IntentDetectionService._normalize(expected) == IntentDetectionService._normalize(detected)

    @staticmethod
    def _normalize(value: Optional[str]) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _metadata_object_to_raw(metadata: Any) -> Dict[str, Any]:
        maia_metadata = getattr(metadata, "maia_metadata", None)
        return {
            "message_id": getattr(metadata, "message_id", None),
            "maia_metadata": maia_metadata,
            "maina_metadata": maia_metadata,
            "maia_metadata_version": getattr(metadata, "maia_metadata_version", None),
        }


class IntentTestRunner:
    def __init__(self, config: IntentTestRunnerConfig):
        self.config = config
        self.loader = DialogTestSetLoader(config.dialogs_dir)
        self.detection_service = IntentDetectionService()
        self.jwt_manager = JWTVambManager()
        self.metadata_manager = MetadataManager()

    def run(self) -> IntentTestReport:
        dialogs, test_sets = self.loader.load()
        logger.info("Loaded %s dialogs and %s test sets", len(dialogs), len(test_sets))

        report = IntentTestReport()
        for test_set in test_sets:
            for index, case in enumerate(test_set.cases):
                report.add_result(self._run_case(test_set, index, case))

        return report

    def _run_case(
        self,
        test_set: DialogIntentTestSet,
        question_index: int,
        case: DialogIntentTestCase,
    ) -> IntentTestResult:
        expected_intent = (case.expected_intent or test_set.dialog_name).strip()
        detected_intent: Optional[str] = None
        metadata_raw: Optional[Dict[str, Any]] = None
        error_message: Optional[str] = None
        conversation_id: Optional[str] = None

        try:
            conversation = VambConversation(self.jwt_manager, self.metadata_manager)
            conversation.initiate_conversation()
            conversation_id = conversation.conversation_id
            response = conversation.send_message(case.question)
            detected_intent, metadata_raw = self.detection_service.extract_detected_intent(response)
        except Exception as exc:
            error_message = str(exc)

        passed = (
            not error_message
            and bool(detected_intent)
            and self.detection_service.intents_match(expected_intent, detected_intent)
        )

        logger.info(
            "Intent test: dialog=%s question_index=%s passed=%s expected=%s detected=%s",
            test_set.dialog_name,
            question_index,
            passed,
            expected_intent,
            detected_intent,
        )

        return IntentTestResult(
            dialog_name=test_set.dialog_name,
            topic=test_set.topic,
            test_file_path=test_set.test_file_path,
            question_index=question_index,
            question=case.question,
            expected_intent=expected_intent,
            detected_intent=detected_intent,
            passed=passed,
            conversation_id=conversation_id,
            metadata_raw=metadata_raw,
            error_message=error_message,
        )


def run_intent_tests(dialogs_dir: str) -> IntentTestReport:
    return IntentTestRunner(IntentTestRunnerConfig(dialogs_dir=dialogs_dir)).run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run intent-recognition tests against VAMB")
    parser.add_argument("--dialogs-dir", default="dialogs", help="Path to dialogs root")
    parser.add_argument(
        "--summary-output",
        default="intent_test_summary.json",
        help="Path for intent test summary JSON",
    )
    parser.add_argument(
        "--jira-output",
        default="intent_test_jira_issues.json",
        help="Path for JIRA-like issues JSON",
    )
    parser.add_argument(
        "--pdf-output",
        default="intent_test_report.pdf",
        help="Path for PDF report",
    )
    parser.add_argument(
        "--jira-project-key",
        default=None,
        help="Optional JIRA project key used in generated payload and bug publishing",
    )
    parser.add_argument(
        "--create-jira-bugs",
        action="store_true",
        help="Actually create Jira bugs (optional; default is off)",
    )
    parser.add_argument("--jira-base-url", default=None, help="Jira base URL or env JIRA_BASE_URL")
    parser.add_argument("--jira-email", default=None, help="Jira email or env JIRA_EMAIL")
    parser.add_argument("--jira-api-token", default=None, help="Jira API token or env JIRA_API_TOKEN")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    logger.setLevel(getattr(logging, args.log_level))

    report = run_intent_tests(args.dialogs_dir)

    summary_payload = report.write_summary_json(args.summary_output)

    jira_issues = report.to_jira_issues()
    save_jira_issues(
        issues=jira_issues,
        output_path=args.jira_output,
        project_key=args.jira_project_key,
        source="test_intent_recognition",
    )

    pdf_path = generate_intent_test_pdf(summary_payload, args.pdf_output)

    logger.info(
        "Intent test finished. total=%s passed=%s failed=%s pdf=%s jira_issues=%s",
        report.total_count,
        report.passed_count,
        report.failed_count,
        pdf_path,
        len(jira_issues),
    )

    if args.create_jira_bugs:
        publish_result = publish_jira_bugs(
            issues=jira_issues,
            jira_project_key=args.jira_project_key,
            jira_base_url=args.jira_base_url,
            jira_email=args.jira_email,
            jira_api_token=args.jira_api_token,
        )
        logger.info(
            "Jira publish finished. created=%s skipped=%s failed=%s",
            publish_result.get("created_count", 0),
            publish_result.get("skipped_count", 0),
            publish_result.get("failed_count", 0),
        )

if __name__ == "__main__":
    main()
