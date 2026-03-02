from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def load_jira_like_payload(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def generate_pdf_from_jira_payload(payload: Dict[str, Any], output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    normal_style = styles["BodyText"]

    doc = SimpleDocTemplate(str(output), pagesize=A4)
    story: List[Any] = []

    story.append(Paragraph("Dialog Validation Report", title_style))
    story.append(Spacer(1, 10))

    generated_at_value = payload.get("generated_at") or payload.get("generated_at_iso", "")
    generated_at = escape(str(generated_at_value))
    source = escape(str(payload.get("source", "")))
    issue_count = payload.get("issue_count", 0)

    story.append(Paragraph(f"Generated at: {generated_at}", normal_style))
    story.append(Paragraph(f"Source: {source}", normal_style))
    story.append(Paragraph(f"Issue count: {issue_count}", normal_style))
    story.append(Spacer(1, 12))

    issues = payload.get("issues", [])
    if not issues:
        story.append(Paragraph("No issues found.", normal_style))
        doc.build(story)
        return str(output)

    for index, wrapped_issue in enumerate(issues, start=1):
        issue = wrapped_issue.get("issue", {})
        summary = escape(str(issue.get("summary", "Untitled Issue")))
        issue_type = escape(str(issue.get("issue_type", "Bug")))
        priority = escape(str(issue.get("priority", "N/A")))
        labels = ", ".join(issue.get("labels", []))
        labels = escape(labels if labels else "N/A")

        story.append(Paragraph(f"{index}. {summary}", heading_style))

        meta_table = Table(
            [
                ["Type", issue_type],
                ["Priority", priority],
                ["Labels", labels],
            ],
            colWidths=[110, 410],
        )
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(meta_table)
        story.append(Spacer(1, 8))

        raw_description = str(issue.get("description", ""))
        for line in raw_description.splitlines():
            clean_line = line.strip()
            if not clean_line:
                story.append(Spacer(1, 2))
                continue

            if clean_line.startswith("- "):
                clean_line = f"• {clean_line[2:]}"

            story.append(Paragraph(escape(clean_line), normal_style))
        story.append(Spacer(1, 8))

        metadata = issue.get("metadata", {})
        items = metadata.get("items", [])
        if items:
            table_rows = [["Content Source", "Error", "Value"]]
            for item in items[:20]:
                table_rows.append(
                    [
                        escape(str(item.get("content_source", item.get("section", "")))),
                        escape(str(item.get("error_code", ""))),
                        escape(str(item.get("normalized_value", item.get("value", "")))),
                    ]
                )

            details_table = Table(table_rows, colWidths=[90, 180, 250])
            details_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(details_table)
            if len(items) > 20:
                story.append(Paragraph(f"Showing first 20 of {len(items)} items.", normal_style))

        story.append(Spacer(1, 14))

    doc.build(story)
    return str(output)


def generate_pdf_from_jira_file(input_path: str, output_path: str) -> str:
    payload = load_jira_like_payload(input_path)
    return generate_pdf_from_jira_payload(payload, output_path)
