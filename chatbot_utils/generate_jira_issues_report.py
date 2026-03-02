import argparse
import json
from collections import defaultdict
from typing import Any, Dict, List

from .jira import JiraIssue, save_jira_issues


def _load_summary_report(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _group_failures_for_jira(failures: List[Dict[str, Any]]) -> List[JiraIssue]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for failure in failures:
        grouped[(failure["dialog_name"], failure["error_code"])].append(failure)

    jira_issues: List[JiraIssue] = []
    for (dialog_name, error_code), group in grouped.items():
        sample_values = sorted({str(item.get("value", "")) for item in group})[:10]
        title = f"Dialog validation: {dialog_name} - {error_code}"
        description_lines = [
            f"Dialog: {dialog_name}",
            f"Error code: {error_code}",
            f"Occurrences: {len(group)}",
            "Affected values:",
        ] + [f"- {value}" for value in sample_values]

        jira_issues.append(
            JiraIssue(
                summary=title,
                description="\n".join(description_lines),
                labels=["chatbot", "dialog-validation", error_code.lower()],
                metadata={
                    "dialog_name": dialog_name,
                    "error_code": error_code,
                    "occurrences": len(group),
                    "items": group,
                },
            )
        )

    return jira_issues


def generate_jira_issues_report(
    input_path: str,
    output_path: str,
    project_key: str | None = None,
) -> Dict[str, Any]:
    report = _load_summary_report(input_path)
    failures = report.get("failures", [])
    jira_issues = _group_failures_for_jira(failures)
    return save_jira_issues(
        issues=jira_issues,
        output_path=output_path,
        project_key=project_key,
        source=input_path,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate JIRA-ready issue JSON from validation summary report"
    )
    parser.add_argument(
        "--input",
        default="validation_summary.json",
        help="Path to validation summary report JSON",
    )
    parser.add_argument(
        "--output",
        default="jira_issues.json",
        help="Path where JIRA issues JSON should be written",
    )
    parser.add_argument(
        "--project-key",
        default=None,
        help="Optional JIRA project key for direct issue create payload",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    payload = generate_jira_issues_report(args.input, args.output, args.project_key)
    print(f"Generated {payload['issue_count']} JIRA issue entries -> {args.output}")


if __name__ == "__main__":
    main()
