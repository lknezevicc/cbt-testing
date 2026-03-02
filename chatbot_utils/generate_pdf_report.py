import argparse

from .pdf_report import generate_pdf_from_jira_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate readable PDF report from jira-like JSON output"
    )
    parser.add_argument(
        "--input",
        default="jira_issues.json",
        help="Path to jira-like JSON output",
    )
    parser.add_argument(
        "--output",
        default="validation_report.pdf",
        help="Path to output PDF report",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    output = generate_pdf_from_jira_file(args.input, args.output)
    print(f"PDF report generated: {output}")


if __name__ == "__main__":
    main()
