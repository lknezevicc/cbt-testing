import argparse
import logging
from typing import List, Optional

from .dialog_validation_models import (
    DialogSection,
    DialogValidationReport,
    PayloadParser,
    UrlChecker,
)
from .jira import publish_jira_bugs, save_jira_issues
from .logging_utils import use_logging
from .pdf_report import generate_pdf_from_jira_payload
from .scope import get_dialog_scope, load_dialogs_from_dir
from .scope_models import Button, Dialog

logger = use_logging("validate_dialogs", log_file="logs/validate_dialogs.log")


def _validate_text_links(
    dialog_name: str,
    answer_index: int,
    text: str,
    url_checker: UrlChecker,
    report: DialogValidationReport,
) -> None:
    urls = url_checker.extract_urls_from_text(text)
    if not urls:
        return

    logger.debug(
        "Checking text URLs: dialog=%s answer_index=%s count=%s",
        dialog_name,
        answer_index,
        len(urls),
    )

    for url_index, url in enumerate(urls):
        is_valid, status_code, error, response_time_ms = url_checker.check_url(url)
        if is_valid:
            logger.debug(
                "URL ok: dialog=%s answer_index=%s url=%s status=%s time_ms=%s",
                dialog_name,
                answer_index,
                url,
                status_code,
                response_time_ms,
            )
            continue

        report.add_url_failure(
            dialog_name=dialog_name,
            answer_index=answer_index,
            content_source=DialogSection.TEXT,
            content_index=url_index,
            value=url,
            normalized_value=url,
            error_message=error or "URL is not reachable",
            is_resource=url_checker.is_resource_url(url),
            status_code=status_code,
            response_time_ms=response_time_ms,
        )
        logger.warning(
            "URL check failed: dialog=%s answer_index=%s url=%s error=%s",
            dialog_name,
            answer_index,
            url,
            error or "URL is not reachable",
        )


def _validate_button_payload(
    dialog_name: str,
    answer_index: int,
    button_index: int,
    button: Button,
    payload_parser: PayloadParser,
    url_checker: UrlChecker,
    dialog_names: set[str],
    report: DialogValidationReport,
) -> None:
    payload = (button.payload or "").strip()
    if not payload:
        return

    if url_checker.is_url(payload):
        is_valid, status_code, error, response_time_ms = url_checker.check_url(payload)
        if is_valid:
            logger.debug(
                "Button URL ok: dialog=%s answer_index=%s button_index=%s payload=%s status=%s",
                dialog_name,
                answer_index,
                button_index,
                payload,
                status_code,
            )
            return

        report.add_url_failure(
            dialog_name=dialog_name,
            answer_index=answer_index,
            content_source=DialogSection.BUTTON,
            content_index=button_index,
            value=payload,
            normalized_value=payload,
            error_message=error or "URL is not reachable",
            is_resource=url_checker.is_resource_url(payload),
            status_code=status_code,
            response_time_ms=response_time_ms,
        )
        logger.warning(
            "Button URL failed: dialog=%s answer_index=%s button_index=%s payload=%s error=%s",
            dialog_name,
            answer_index,
            button_index,
            payload,
            error or "URL is not reachable",
        )
        return

    dialog_id = payload_parser.extract_dialog_id(payload)
    if dialog_id is None:
        report.add_payload_format_failure(
            dialog_name=dialog_name,
            answer_index=answer_index,
            content_source=DialogSection.BUTTON,
            content_index=button_index,
            value=payload,
        )
        logger.warning(
            "Unsupported payload format: dialog=%s answer_index=%s button_index=%s payload=%s",
            dialog_name,
            answer_index,
            button_index,
            payload,
        )
        return

    if dialog_id not in dialog_names:
        report.add_dialog_reference_failure(
            dialog_name=dialog_name,
            answer_index=answer_index,
            content_source=DialogSection.BUTTON,
            content_index=button_index,
            value=payload,
            normalized_value=dialog_id,
        )
        logger.warning(
            "Dialog reference missing: dialog=%s answer_index=%s button_index=%s target=%s",
            dialog_name,
            answer_index,
            button_index,
            dialog_id,
        )


def validate_dialogs(dialogs: List[Dialog]) -> DialogValidationReport:
    dialog_names = {dialog.name for dialog in dialogs}
    report = DialogValidationReport(logger=logger)
    payload_parser = PayloadParser()
    url_checker = UrlChecker(logger=logger)

    logger.info("Validation started for %s dialogs", len(dialogs))

    for dialog in dialogs:
        logger.info("Validating dialog: %s", dialog.name)
        for answer_index, answer in enumerate(dialog.answers):
            if answer.text:
                _validate_text_links(
                    dialog.name,
                    answer_index,
                    answer.text,
                    url_checker,
                    report,
                )

            for button_index, button in enumerate(answer.buttons):
                _validate_button_payload(
                    dialog_name=dialog.name,
                    answer_index=answer_index,
                    button_index=button_index,
                    button=button,
                    payload_parser=payload_parser,
                    url_checker=url_checker,
                    dialog_names=dialog_names,
                    report=report,
                )

    logger.info("Validation finished. failures=%s", len(report.failures))
    return report


def validate_all_dialogs(
    dialogs_dir: str,
    pull_latest_from_github: bool,
    summary_output: str = "validation_summary.json",
    jira_output: str = "jira_issues.json",
    jira_project_key: Optional[str] = None,
    pdf_output: Optional[str] = "validation_report.pdf",
    create_jira_bugs: bool = False,
    jira_base_url: Optional[str] = None,
    jira_email: Optional[str] = None,
    jira_api_token: Optional[str] = None,
) -> None:
    dialogs = get_dialog_scope() if pull_latest_from_github else load_dialogs_from_dir(dialogs_dir)
    report = validate_dialogs(dialogs)
    jira_issues = report.to_jira_issues()

    report.write_summary_json(len(dialogs), summary_output)
    jira_payload = save_jira_issues(
        issues=jira_issues,
        output_path=jira_output,
        project_key=jira_project_key,
        source="validate_dialogs",
    )

    logger.info("JIRA issues report written: %s (issues=%s)", jira_output, len(jira_issues))

    pdf_path: Optional[str] = None
    if pdf_output:
        pdf_path = generate_pdf_from_jira_payload(jira_payload, pdf_output)
        logger.info("PDF report written: %s", pdf_path)

    if create_jira_bugs:
        jira_publish_result = publish_jira_bugs(
            issues=jira_issues,
            jira_project_key=jira_project_key,
            jira_base_url=jira_base_url,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
        )
        logger.info(
            "Jira publish finished. created=%s skipped=%s failed=%s",
            jira_publish_result.get("created_count", 0),
            jira_publish_result.get("skipped_count", 0),
            jira_publish_result.get("failed_count", 0),
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate dialog links and payload dialog references")
    parser.add_argument("--dialogs-dir", default="dialogs", help="Path to local dialogs directory")
    parser.add_argument(
        "--pull-latest-from-github",
        action="store_true",
        help="Use repository dialogs instead of local directory",
    )
    parser.add_argument(
        "--summary-output",
        default="validation_summary.json",
        help="Path for concise validation summary JSON",
    )
    parser.add_argument(
        "--jira-output",
        default="jira_issues.json",
        help="Path for JIRA-ready issues JSON",
    )
    parser.add_argument(
        "--jira-project-key",
        default=None,
        help="Optional JIRA project key used in generated payload and bug publishing",
    )
    parser.add_argument(
        "--pdf-output",
        default="validation_report.pdf",
        help="Path for readable PDF report generated from jira-like output (default: validation_report.pdf)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Disable PDF generation",
    )
    parser.add_argument(
        "--create-jira-bugs",
        action="store_true",
        help="Actually create/update Jira bugs (optional; default is off)",
    )
    parser.add_argument(
        "--jira-base-url",
        default=None,
        help="Jira base URL (or env JIRA_BASE_URL)",
    )
    parser.add_argument(
        "--jira-email",
        default=None,
        help="Jira account email (or env JIRA_EMAIL)",
    )
    parser.add_argument(
        "--jira-api-token",
        default=None,
        help="Jira API token (or env JIRA_API_TOKEN)",
    )
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

    pdf_output = None if args.no_pdf else args.pdf_output

    validate_all_dialogs(
        dialogs_dir=args.dialogs_dir,
        pull_latest_from_github=args.pull_latest_from_github,
        summary_output=args.summary_output,
        jira_output=args.jira_output,
        jira_project_key=args.jira_project_key,
        pdf_output=pdf_output,
        create_jira_bugs=args.create_jira_bugs,
        jira_base_url=args.jira_base_url,
        jira_email=args.jira_email,
        jira_api_token=args.jira_api_token,
    )


if __name__ == "__main__":
    main()
