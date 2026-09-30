import json
from typing import Any, Dict, List, Optional, Tuple

from ado_client import AzureDevOpsClient
from log_analyzer import LogAnalyzer
from llm_analyzer import LLMAnalyzer
from models import BuildSummary, RCAResult


class PipelineRCAAgent:
    """
    Agent orchestration:

        Azure DevOps
            -> build metadata
            -> timeline
            -> failed task detection
            -> task log retrieval
            -> evidence extraction
            -> LLM reasoning
            -> RCAResult

    Evidence is aggressively bounded before being sent to the LLM so that
    providers with strict tokens-per-minute limits are not exceeded.
    """

    # ------------------------------------------------------------------
    # SIZE LIMITS
    # ------------------------------------------------------------------

    # These are character limits, not token limits.
    #
    # The LLMAnalyzer applies a second, final request-size guard.
    MAX_EVIDENCE_CHARS = 12000
    MAX_RAW_LOG_CHARS_PER_TASK = 3500
    MAX_TIMELINE_TASKS = 15

    MAX_CHANGES = 10
    MAX_CHANGE_MESSAGE_CHARS = 300

    def __init__(
        self,
        ado_client: AzureDevOpsClient,
        llm: LLMAnalyzer,
        log_analyzer: LogAnalyzer,
    ):
        self.ado = ado_client
        self.llm = llm
        self.log_analyzer = log_analyzer

    # ------------------------------------------------------------------
    # BUILD NORMALIZATION
    # ------------------------------------------------------------------

    def _normalize_build(
        self,
        build: Dict[str, Any],
    ) -> BuildSummary:
        definition = build.get("definition") or {}

        return BuildSummary(
            id=build.get("id"),
            build_number=build.get("buildNumber", ""),
            status=build.get("status", ""),
            result=build.get("result", ""),
            definition_name=definition.get("name", ""),
            source_branch=build.get("sourceBranch", ""),
            source_version=build.get("sourceVersion", ""),
            queue_time=build.get("queueTime", ""),
            start_time=build.get("startTime", ""),
            finish_time=build.get("finishTime", ""),
        )

    # ------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------

    def analyze_build(
        self,
        build_id: int,
    ) -> RCAResult:
        build = self.ado.get_build(build_id)

        return self._analyze_build(build)

    def analyze_build_number(
        self,
        build_number: str,
    ) -> RCAResult:
        build = self.ado.get_build_by_number(build_number)

        return self._analyze_build(build)

    def analyze_latest_failed(self) -> RCAResult:
        build = self.ado.get_latest_failed_build()

        return self.analyze_build(
            int(build["id"])
        )

    # ------------------------------------------------------------------
    # TEXT HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate_text(
        value: Any,
        max_chars: int,
    ) -> str:
        """
        Safely convert arbitrary values to text and truncate them.

        Keeps both beginning and end because:
        - beginning often contains useful setup/error information
        - end often contains the final task failure
        """

        if value is None:
            return ""

        if not isinstance(value, str):
            try:
                value = json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )
            except Exception:
                value = str(value)

        text = str(value)

        if len(text) <= max_chars:
            return text

        marker = "\n\n...[TRUNCATED]...\n\n"

        available = max_chars - len(marker)

        if available <= 0:
            return text[:max_chars]

        head = available * 2 // 3
        tail = available - head

        return (
            text[:head]
            + marker
            + text[-tail:]
        )

    # ------------------------------------------------------------------
    # TIMELINE HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _timeline_record_name(
        record: Dict[str, Any],
    ) -> str:
        return (
            record.get("name")
            or record.get("taskName")
            or record.get("displayName")
            or record.get("identifier")
            or "Unknown task"
        )

    @staticmethod
    def _timeline_record_state(
        record: Dict[str, Any],
    ) -> str:
        return str(
            record.get("state")
            or ""
        ).strip().lower()

    @staticmethod
    def _timeline_record_result(
        record: Dict[str, Any],
    ) -> str:
        return str(
            record.get("result")
            or ""
        ).strip().lower()

    @staticmethod
    def _timeline_record_log_id(
        record: Dict[str, Any],
    ) -> Optional[int]:
        """
        Extract a log ID from common Azure DevOps timeline shapes.
        """

        candidates = [
            record.get("log_id"),
            record.get("logId"),
        ]

        log_value = record.get("log")

        if isinstance(log_value, dict):
            candidates.extend(
                [
                    log_value.get("id"),
                    log_value.get("logId"),
                ]
            )

        elif isinstance(log_value, int):
            candidates.append(log_value)

        elif isinstance(log_value, str):
            try:
                candidates.append(int(log_value))
            except (TypeError, ValueError):
                pass

        for value in candidates:
            if value is None:
                continue

            try:
                return int(value)
            except (TypeError, ValueError):
                continue

        return None

    @classmethod
    def _is_failed_timeline_record(
        cls,
        record: Dict[str, Any],
    ) -> bool:
        result = cls._timeline_record_result(record)
        state = cls._timeline_record_state(record)

        return (
            result in {
                "failed",
                "failure",
            }
            or (
                state == "completed"
                and result == "failed"
            )
        )

    @classmethod
    def _extract_failed_timeline_records(
        cls,
        timeline: Any,
    ) -> List[Dict[str, Any]]:
        if not isinstance(timeline, list):
            return []

        failed = []

        for record in timeline:
            if not isinstance(record, dict):
                continue

            if cls._is_failed_timeline_record(record):
                failed.append(record)

        return failed

    @classmethod
    def _select_first_failed_records(
        cls,
        timeline: Any,
        failed_records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Preserve the first failed task/stage/job.

        Timeline order is normally chronological.
        """

        if not failed_records:
            return []

        timeline_records = (
            timeline
            if isinstance(timeline, list)
            else []
        )

        ordered = []

        for record in timeline_records:
            if not isinstance(record, dict):
                continue

            if record in failed_records:
                ordered.append(record)

        for record in failed_records:
            if record not in ordered:
                ordered.append(record)

        return ordered[: cls.MAX_TIMELINE_TASKS]

    # ------------------------------------------------------------------
    # EVIDENCE COMPACTION
    # ------------------------------------------------------------------

    def _compact_dict(
        self,
        value: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compact a dictionary while retaining RCA-relevant fields.
        """

        compact: Dict[str, Any] = {}

        priority_fields = (
            "type",
            "task",
            "stage",
            "job",
            "name",
            "state",
            "result",
            "log_id",
            "logId",
            "source",
            "detail",
            "error",
            "message",
            "resultCode",
            "issues",
            "log_status",
            "first_error",
        )

        # First retain known useful fields.
        for key in priority_fields:
            if key not in value:
                continue

            item = value[key]

            if item in (None, "", [], {}):
                continue

            if isinstance(item, str):
                compact[key] = self._truncate_text(
                    item,
                    1800,
                )
            elif isinstance(item, list):
                compact[key] = item[:8]
            elif isinstance(item, dict):
                compact[key] = self._compact_dict(item)
            else:
                compact[key] = item

        # Retain a small number of other scalar fields.
        for key, item in value.items():
            if key in compact:
                continue

            if key in priority_fields:
                continue

            if isinstance(item, (str, int, float, bool)):
                compact[key] = (
                    self._truncate_text(item, 500)
                    if isinstance(item, str)
                    else item
                )

        return compact

    def _compact_evidence(
        self,
        evidence: Any,
    ) -> Any:
        """
        Aggressively compact evidence.

        The LLM needs the failure signal, not every byte of the ADO
        response. Large nested Azure DevOps objects are deliberately
        excluded.
        """

        if evidence is None:
            return []

        if isinstance(evidence, str):
            return self._truncate_text(
                evidence,
                self.MAX_EVIDENCE_CHARS,
            )

        if isinstance(evidence, dict):
            compact = self._compact_dict(evidence)

            serialized = json.dumps(
                compact,
                ensure_ascii=False,
                default=str,
            )

            if len(serialized) <= self.MAX_EVIDENCE_CHARS:
                return compact

            return self._truncate_text(
                serialized,
                self.MAX_EVIDENCE_CHARS,
            )

        if not isinstance(evidence, list):
            return evidence

        compact: List[Any] = []

        for item in evidence:
            if isinstance(item, dict):
                compact.append(
                    self._compact_dict(item)
                )

            elif isinstance(item, str):
                compact.append(
                    self._truncate_text(
                        item,
                        1800,
                    )
                )

            else:
                compact.append(item)

        # Hard serialized-size limit.
        result: List[Any] = []
        current_size = 2

        for item in compact:
            item_text = json.dumps(
                item,
                ensure_ascii=False,
                default=str,
            )

            item_size = len(item_text) + 1

            if (
                current_size + item_size
                > self.MAX_EVIDENCE_CHARS
            ):
                break

            result.append(item)
            current_size += item_size

        return result

    # ------------------------------------------------------------------
    # CHANGE COMPACTION
    # ------------------------------------------------------------------

    def _compact_changes(
        self,
        changes: Any,
    ) -> List[Dict[str, Any]]:
        """
        Keep only useful fields from recent source-control changes.
        """

        if not isinstance(changes, list):
            return []

        compact = []

        for change in changes[: self.MAX_CHANGES]:
            if not isinstance(change, dict):
                continue

            compact.append(
                {
                    "id": change.get("id"),
                    "message": self._truncate_text(
                        change.get("message", ""),
                        self.MAX_CHANGE_MESSAGE_CHARS,
                    ),
                    "type": change.get("type"),
                    "location": self._truncate_text(
                        change.get("location", ""),
                        250,
                    ),
                }
            )

        return compact

    # ------------------------------------------------------------------
    # FAILED TASK EXTRACTION
    # ------------------------------------------------------------------

    def _get_failed_tasks(
        self,
        timeline: Any,
    ) -> List[Dict[str, Any]]:
        """
        Get failed tasks using LogAnalyzer first, then direct timeline
        inspection as a fallback.
        """

        failed_tasks: List[Dict[str, Any]] = []

        try:
            result = self.log_analyzer.failed_tasks(
                timeline
            )

            if isinstance(result, list):
                failed_tasks = [
                    item
                    for item in result
                    if isinstance(item, dict)
                ]

        except Exception:
            failed_tasks = []

        direct_failed = (
            self._extract_failed_timeline_records(
                timeline
            )
        )

        merged: List[Dict[str, Any]] = []

        for task in failed_tasks + direct_failed:
            if task not in merged:
                merged.append(task)

        return self._select_first_failed_records(
            timeline,
            merged,
        )

    # ------------------------------------------------------------------
    # LOG RETRIEVAL
    # ------------------------------------------------------------------

    def _retrieve_task_logs(
        self,
        build_id: int,
        failed_tasks: List[Dict[str, Any]],
    ) -> Tuple[
        Dict[int, Any],
        List[Dict[str, Any]],
    ]:
        """
        Retrieve bounded logs for failed timeline records.
        """

        logs_by_id: Dict[int, Any] = {}

        retrieval_evidence: List[
            Dict[str, Any]
        ] = []

        for task in failed_tasks:
            task_name = (
                self._timeline_record_name(task)
            )

            log_id = (
                self._timeline_record_log_id(task)
            )

            if log_id is None:
                retrieval_evidence.append(
                    {
                        "type": "failed_task",
                        "task": task_name,
                        "result": self._timeline_record_result(
                            task
                        ),
                        "log_status": (
                            "No log ID was present "
                            "on this timeline record."
                        ),
                    }
                )
                continue

            try:
                log_content = (
                    self.ado.get_build_log(
                        build_id,
                        log_id,
                    )
                )

                logs_by_id[log_id] = (
                    self._truncate_text(
                        log_content,
                        self.MAX_RAW_LOG_CHARS_PER_TASK,
                    )
                )

                retrieval_evidence.append(
                    {
                        "type": "failed_task_log",
                        "task": task_name,
                        "log_id": log_id,
                        "log_status": "retrieved",
                    }
                )

            except Exception as exc:
                error_text = (
                    f"Log retrieval failed: {exc}"
                )

                logs_by_id[log_id] = error_text

                retrieval_evidence.append(
                    {
                        "type": "failed_task_log",
                        "task": task_name,
                        "log_id": log_id,
                        "log_status": error_text,
                    }
                )

        return (
            logs_by_id,
            retrieval_evidence,
        )

    # ------------------------------------------------------------------
    # FALLBACK TIMELINE EVIDENCE
    # ------------------------------------------------------------------

    @classmethod
    def _build_timeline_fallback_evidence(
        cls,
        failed_tasks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build explicit evidence directly from failed timeline records.
        """

        evidence = []

        for task in failed_tasks:
            name = cls._timeline_record_name(task)
            result = cls._timeline_record_result(task)
            state = cls._timeline_record_state(task)
            log_id = cls._timeline_record_log_id(task)

            record_evidence: Dict[str, Any] = {
                "type": "timeline_failure",
                "task": name,
                "state": state,
                "result": result,
            }

            if log_id is not None:
                record_evidence["log_id"] = log_id

            for field in (
                "error",
                "message",
                "issues",
                "resultCode",
                "type",
                "parentId",
                "order",
            ):
                if field not in task:
                    continue

                value = task[field]

                if value in (
                    None,
                    "",
                    [],
                ):
                    continue

                if isinstance(value, str):
                    value = cls._truncate_text(
                        value,
                        1200,
                    )

                elif isinstance(value, list):
                    value = value[:5]

                record_evidence[field] = value

            evidence.append(record_evidence)

        return evidence

    # ------------------------------------------------------------------
    # TIMELINE OVERVIEW
    # ------------------------------------------------------------------

    @classmethod
    def _build_timeline_overview(
        cls,
        timeline: Any,
    ) -> List[Dict[str, Any]]:
        """
        Create a small timeline representation when no other evidence
        exists.
        """

        if not isinstance(timeline, list):
            return []

        preview = []

        for record in timeline[: cls.MAX_TIMELINE_TASKS]:
            if not isinstance(record, dict):
                continue

            preview.append(
                {
                    "name": cls._timeline_record_name(
                        record
                    ),
                    "state": cls._timeline_record_state(
                        record
                    ),
                    "result": cls._timeline_record_result(
                        record
                    ),
                    "type": record.get("type"),
                }
            )

        return preview

    # ------------------------------------------------------------------
    # MAIN ANALYSIS
    # ------------------------------------------------------------------

    def _analyze_build(
        self,
        build: Dict[str, Any],
    ) -> RCAResult:

        build_id = int(build["id"])

        # --------------------------------------------------------------
        # 1. Fetch timeline.
        # --------------------------------------------------------------

        timeline = self.ado.get_timeline(
            build_id
        )

        if timeline is None:
            timeline = []

        # --------------------------------------------------------------
        # 2. Identify failed tasks.
        # --------------------------------------------------------------

        failed_tasks = self._get_failed_tasks(
            timeline
        )

        # --------------------------------------------------------------
        # 3. Retrieve logs for failed tasks.
        # --------------------------------------------------------------

        (
            logs_by_id,
            log_retrieval_evidence,
        ) = self._retrieve_task_logs(
            build_id,
            failed_tasks,
        )

        # --------------------------------------------------------------
        # 4. Ask LogAnalyzer to build evidence.
        # --------------------------------------------------------------

        try:
            evidence_result = (
                self.log_analyzer.build_evidence(
                    timeline,
                    logs_by_id,
                )
            )

            if isinstance(
                evidence_result,
                tuple,
            ):
                evidence = (
                    evidence_result[0]
                    if len(evidence_result) >= 1
                    else []
                )

                first_error = (
                    evidence_result[1]
                    if len(evidence_result) >= 2
                    else None
                )
            else:
                evidence = evidence_result
                first_error = None

        except Exception as exc:
            evidence = []
            first_error = (
                f"LogAnalyzer failed: {exc}"
            )

        if evidence is None:
            evidence = []

        # --------------------------------------------------------------
        # 5. Combine evidence.
        # --------------------------------------------------------------

        fallback_evidence = (
            self._build_timeline_fallback_evidence(
                failed_tasks
            )
        )

        combined_evidence: List[Any] = []

        if isinstance(evidence, list):
            combined_evidence.extend(evidence)

        elif evidence:
            combined_evidence.append(evidence)

        # Put explicit timeline failure information first.
        # This gives the LLM the most important RCA signal first.
        combined_evidence = (
            fallback_evidence
            + combined_evidence
        )

        combined_evidence.extend(
            log_retrieval_evidence
        )

        if first_error:
            combined_evidence.append(
                {
                    "type": "log_analyzer_result",
                    "detail": first_error,
                }
            )

        # --------------------------------------------------------------
        # 6. Fallback timeline overview.
        # --------------------------------------------------------------

        if not combined_evidence:
            timeline_preview = (
                self._build_timeline_overview(
                    timeline
                )
            )

            if timeline_preview:
                combined_evidence.append(
                    {
                        "type": "timeline_overview",
                        "records": timeline_preview,
                    }
                )

        # --------------------------------------------------------------
        # 7. Fetch recent changes.
        # --------------------------------------------------------------

        try:
            changes = self.ado.get_changes(
                build_id
            )

        except Exception as exc:
            changes = []

            combined_evidence.append(
                {
                    "type": "changes_retrieval_error",
                    "detail": str(exc),
                }
            )

        # --------------------------------------------------------------
        # 8. Compact evidence and changes.
        # --------------------------------------------------------------

        compact_evidence = (
            self._compact_evidence(
                combined_evidence
            )
        )

        compact_changes = (
            self._compact_changes(
                changes
            )
        )

        # --------------------------------------------------------------
        # 9. Build final LLM payload.
        # --------------------------------------------------------------

        normalized_build = (
            self._normalize_build(
                build
            ).model_dump()
        )

        payload = {
            "build": normalized_build,
            "evidence": compact_evidence,
            "changes": compact_changes,
        }

        # --------------------------------------------------------------
        # 10. Send to LLM.
        # --------------------------------------------------------------

        return self.llm.analyze(
            payload
        )
