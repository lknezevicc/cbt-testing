from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_intent_test_pdf(summary_payload: Dict[str, Any], output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    normal_style = styles["BodyText"]

    doc = SimpleDocTemplate(str(output), pagesize=A4)
    story: List[Any] = []

    story.append(Paragraph("Intent Recognition Test Report", title_style))
    story.append(Spacer(1, 10))

    generated_at = escape(str(summary_payload.get("generated_at", "")))
    total = summary_payload.get("total_tests", 0)
    passed = summary_payload.get("passed_tests", 0)
    failed = summary_payload.get("failed_tests", 0)

    story.append(Paragraph(f"Generated at: {generated_at}", normal_style))
    story.append(Paragraph(f"Total tests: {total}", normal_style))
    story.append(Paragraph(f"Passed tests: {passed}", normal_style))
    story.append(Paragraph(f"Failed tests: {failed}", normal_style))
    story.append(Spacer(1, 12))

    failed_results = [item for item in summary_payload.get("results", []) if not item.get("passed", False)]
    if not failed_results:
        story.append(Paragraph("No intent mismatches found.", normal_style))
        doc.build(story)
        return str(output)

    for index, result in enumerate(failed_results, start=1):
        dialog_name = escape(str(result.get("dialog_name", "")))
        topic = escape(str(result.get("topic", "")))
        question = escape(str(result.get("question", "")))
        expected_intent = escape(str(result.get("expected_intent", "")))
        detected_intent = escape(str(result.get("detected_intent", "N/A")))
        test_file_path = escape(str(result.get("test_file_path", "")))
        conversation_id = escape(str(result.get("conversation_id", "N/A")))
        error_message = escape(str(result.get("error_message", "N/A")))

        story.append(Paragraph(f"{index}. {dialog_name}", heading_style))

        table = Table(
            [
                ["Topic", topic],
                ["Test file", test_file_path],
                ["Question", question],
                ["Expected intent", expected_intent],
                ["Detected intent", detected_intent],
                ["Conversation ID", conversation_id],
                ["Error", error_message],
            ],
            colWidths=[130, 390],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 12))

    doc.build(story)
    return str(output)
