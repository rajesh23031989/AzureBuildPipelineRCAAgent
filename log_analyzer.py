import re
from typing import Any, Dict, List, Tuple

ERROR_PATTERNS = [
    r"\berror\b",
    r"\bfailed\b",
    r"\bexception\b",
    r"\bfatal\b",
    r"\bunauthorized\b",
    r"\bforbidden\b",
    r"\bnot found\b",
    r"\btimeout\b",
    r"\bconnection refused\b",
    r"\bno such file\b",
    r"\bexit code\b",
    r"\bcommand failed\b",
    r"\bMSB\d+\b",
    r"\bCS\d{4}\b",
    r"\bNU\d{4}\b",
]

class LogAnalyzer:
    def __init__(self, context_lines: int = 12, max_log_chars: int = 50000):
        self.context_lines = context_lines
        self.max_log_chars = max_log_chars

    def failed_tasks(self, timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
        result = []

        for record in timeline.get("records", []):
            if str(record.get("result", "")).lower() != "failed":
                continue

            issues = [
                issue.get("message", "")
                for issue in record.get("issues", [])
                if issue.get("message")
            ]

            log_id = None
            if isinstance(record.get("log"), dict):
                log_id = record["log"].get("id")

            result.append({
                "id": record.get("id", ""),
                "name": record.get("name", ""),
                "type": record.get("type", ""),
                "state": record.get("state", ""),
                "result": record.get("result", ""),
                "result_code": record.get("resultCode", ""),
                "order": record.get("order"),
                "issues": issues,
                "log_id": log_id,
            })

        return result

    def relevant_windows(self, log_text: str) -> List[str]:
        lines = log_text.splitlines()
        windows = []

        for index, line in enumerate(lines):
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in ERROR_PATTERNS):
                start = max(0, index - self.context_lines)
                end = min(len(lines), index + self.context_lines + 1)

                windows.append(
                    "\n".join(
                        f"{i + 1:>6}: {lines[i]}"
                        for i in range(start, end)
                    )
                )

        unique = []
        seen = set()

        for block in windows:
            key = block[:1000]
            if key not in seen:
                seen.add(key)
                unique.append(block)

        return unique

    def build_evidence(
        self,
        timeline: Dict[str, Any],
        logs_by_id: Dict[int, str],
    ) -> Tuple[List[Dict[str, Any]], str]:

        failed_tasks = self.failed_tasks(timeline)
        evidence = []

        for task in failed_tasks:
            evidence.append({
                "failed_task": task,
                "log_evidence": self.relevant_windows(
                    logs_by_id.get(task["log_id"], "")
                )[:8],
            })

        raw = str(evidence)

        if len(raw) > self.max_log_chars:
            raw = raw[:self.max_log_chars] + "\n...[evidence truncated]"

        return evidence, raw
