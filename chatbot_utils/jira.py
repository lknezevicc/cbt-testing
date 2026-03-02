from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jira import JIRA
from jira.exceptions import JIRAError


@dataclass
class JiraIssue:
    summary: str
    description: str
    labels: List[str] = field(default_factory=list)
    issue_type: str = "Bug"
    priority: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> str:
        fingerprint_source = {
            "summary": self.summary,
            "issue_type": self.issue_type,
            "metadata": self.metadata,
        }
        canonical = json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_create_payload(self, project_key: str) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "project": {"key": project_key},
            "summary": self.summary,
            "description": self.description,
            "issuetype": {"name": self.issue_type},
            "labels": self.labels,
        }

        if self.priority:
            fields["priority"] = {"name": self.priority}

        return {"fields": fields}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JiraClientConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    verify_ssl: bool = True
    timeout_seconds: int = 15


class JiraClient:
    def __init__(self, config: JiraClientConfig):
        self.config = config

        options = {
            "server": self.config.base_url.rstrip("/"),
            "verify": self.config.verify_ssl,
        }
        self.client = JIRA(
            options=options,
            basic_auth=(self.config.email, self.config.api_token),
            timeout=self.config.timeout_seconds,
        )

    @staticmethod
    def _dedup_label(dedup_key: str) -> str:
        return f"chatbot-dedup-{dedup_key[:16]}"

    def _find_existing_open_issue_key_by_label(self, dedup_label: str) -> Optional[str]:
        jql = (
            f'project = "{self.config.project_key}" '
            f'AND labels = "{dedup_label}" '
            "AND statusCategory != Done "
            "ORDER BY created DESC"
        )
        matches = self.client.search_issues(jql, maxResults=1)
        if not matches:
            return None
        return getattr(matches[0], "key", None)

    def create_issue(self, issue: JiraIssue) -> Dict[str, Any]:
        dedup_label = self._dedup_label(issue.dedup_key())
        labels = list(dict.fromkeys([*issue.labels, dedup_label]))

        issue_for_create = JiraIssue(
            summary=issue.summary,
            description=issue.description,
            labels=labels,
            issue_type=issue.issue_type,
            priority=issue.priority,
            metadata=issue.metadata,
        )

        created = self.client.create_issue(
            fields=issue_for_create.to_create_payload(self.config.project_key)["fields"]
        )
        return {
            "key": getattr(created, "key", None),
            "id": getattr(created, "id", None),
            "self": getattr(created, "self", None),
            "dedup_label": dedup_label,
        }

    def create_issues(
        self,
        issues: List[JiraIssue],
        continue_on_error: bool = True,
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        dedup_seen_in_run: set[str] = set()

        for issue in issues:
            try:
                dedup_key = issue.dedup_key()
                dedup_label = self._dedup_label(dedup_key)

                if deduplicate:
                    if dedup_label in dedup_seen_in_run:
                        skipped.append(
                            {
                                "summary": issue.summary,
                                "reason": "duplicate-in-current-run",
                                "dedup_label": dedup_label,
                            }
                        )
                        continue

                    existing_key = self._find_existing_open_issue_key_by_label(dedup_label)
                    if existing_key:
                        skipped.append(
                            {
                                "summary": issue.summary,
                                "reason": "already-exists-in-jira",
                                "existing_key": existing_key,
                                "dedup_label": dedup_label,
                            }
                        )
                        dedup_seen_in_run.add(dedup_label)
                        continue

                created = self.create_issue(issue)
                results.append(
                    {
                        "summary": issue.summary,
                        "key": created.get("key"),
                        "id": created.get("id"),
                        "self": created.get("self"),
                        "dedup_label": created.get("dedup_label"),
                    }
                )
                dedup_seen_in_run.add(dedup_label)
            except JIRAError as exc:
                error_text = f"HTTP {exc.status_code}: {exc.text}" if exc.status_code else str(exc)
                error_entry = {"summary": issue.summary, "error": error_text}
                errors.append(error_entry)
                if not continue_on_error:
                    break
            except Exception as exc:
                error_entry = {"summary": issue.summary, "error": str(exc)}
                errors.append(error_entry)
                if not continue_on_error:
                    break

        return {
            "created_count": len(results),
            "skipped_count": len(skipped),
            "failed_count": len(errors),
            "created": results,
            "skipped": skipped,
            "errors": errors,
        }


def save_jira_issues(
    issues: List[JiraIssue],
    output_path: str,
    project_key: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    serialized_issues = []
    for issue in issues:
        dedup_key = issue.dedup_key()
        serialized_issues.append(
            {
                "issue": issue.to_dict(),
                "dedup_key": dedup_key,
                "dedup_label": JiraClient._dedup_label(dedup_key),
                "jira_payload": issue.to_create_payload(project_key) if project_key else None,
            }
        )

    payload = {
        "generated_at": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "generated_at_iso": now_utc.isoformat(),
        "project_key": project_key,
        "source": source,
        "issue_count": len(issues),
        "issues": serialized_issues,
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    return payload


def publish_jira_bugs(
    issues: List[JiraIssue],
    jira_project_key: Optional[str],
    jira_base_url: Optional[str] = None,
    jira_email: Optional[str] = None,
    jira_api_token: Optional[str] = None,
) -> Dict[str, Any]:
    base_url = jira_base_url or os.getenv("JIRA_BASE_URL")
    email = jira_email or os.getenv("JIRA_EMAIL")
    api_token = jira_api_token or os.getenv("JIRA_API_TOKEN")

    missing = [
        name
        for name, value in {
            "jira_project_key": jira_project_key,
            "jira_base_url": base_url,
            "jira_email": email,
            "jira_api_token": api_token,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Cannot publish Jira bugs. Missing required config: " + ", ".join(missing)
        )

    client = JiraClient(
        JiraClientConfig(
            base_url=base_url,
            email=email,
            api_token=api_token,
            project_key=jira_project_key,
        )
    )

    return client.create_issues(issues, deduplicate=True)
