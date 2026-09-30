import json
import re
from typing import Any

from pydantic import BaseModel, Field

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None


# ============================================================
# RCA RESULT MODEL
# ============================================================

class RCAResult(BaseModel):
    summary: str
    root_cause: str
    failure_category: str
    confidence: str
    failed_stage_or_task: str

    evidence: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    preventive_actions: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


# ============================================================
# LLM ANALYZER
# ============================================================

class LLMAnalyzer:
    def __init__(self, settings):
        self.settings = settings

        provider = (
            getattr(settings, "llm_provider", "groq")
            or "groq"
        ).strip().lower()

        self.provider = provider

        if provider == "groq":
            self._init_groq()

        elif provider in ("azure_openai", "azure", "azureopenai"):
            self._init_azure_openai()

        else:
            raise ValueError(
                f"Unsupported LLM_PROVIDER: {provider}. "
                "Use 'groq' or 'azure_openai'."
            )

    # ========================================================
    # GROQ
    # ========================================================

    def _init_groq(self):
        if Groq is None:
            raise RuntimeError(
                "The 'groq' package is not installed. "
                "Install it with: pip install groq"
            )

        api_key = (
            getattr(self.settings, "groq_api_key", "")
            or ""
        ).strip()

        if not api_key:
            raise ValueError(
                "GROQ_API_KEY is required for Groq."
            )

        self.groq_model = (
            getattr(
                self.settings,
                "groq_model",
                "openai/gpt-oss-120b",
            )
            or "openai/gpt-oss-120b"
        ).strip()

        self.client = Groq(api_key=api_key)

    # ========================================================
    # AZURE OPENAI
    # ========================================================

    def _init_azure_openai(self):
        if AzureOpenAI is None:
            raise RuntimeError(
                "The 'openai' package is not installed. "
                "Install it with: pip install openai"
            )

        endpoint = (
            getattr(
                self.settings,
                "azure_openai_endpoint",
                "",
            )
            or ""
        ).strip()

        api_key = (
            getattr(
                self.settings,
                "azure_openai_api_key",
                "",
            )
            or ""
        ).strip()

        deployment = (
            getattr(
                self.settings,
                "azure_openai_deployment",
                "",
            )
            or ""
        ).strip()

        api_version = (
            getattr(
                self.settings,
                "azure_openai_api_version",
                "2025-04-14",
            )
            or "2025-04-14"
        ).strip()

        if not endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is required for Azure OpenAI."
            )

        if not api_key:
            raise ValueError(
                "AZURE_OPENAI_API_KEY is required for Azure OpenAI."
            )

        if not deployment:
            raise ValueError(
                "AZURE_OPENAI_DEPLOYMENT is required for Azure OpenAI."
            )

        self.azure_deployment = deployment

        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    # ========================================================
    # RCA PROMPT
    # ========================================================

    def _build_system_prompt(self) -> str:
        return """
You are an expert Azure DevOps CI/CD pipeline root-cause-analysis agent.

Analyze the supplied pipeline build, timeline, task and log evidence.

Your job is to identify the most likely root cause using ONLY the supplied
evidence.

IMPORTANT RCA RULES:

1. Return ONLY valid JSON.
2. Do not return Markdown.
3. Do not wrap the JSON in ```json or ``` blocks.
4. Every required field must be present.
5. Do not invent evidence.
6. Every root-cause claim must be supported by the supplied evidence.
7. Prefer concrete ERROR and FAILED records over warnings or informational
   messages.
8. Do not identify a warning as the root cause unless the evidence clearly
   demonstrates that the warning caused the failure.
9. Distinguish application/build/test failures from infrastructure failures.
10. If the evidence is insufficient, explain the uncertainty instead of
    guessing.
11. The "evidence" field MUST contain strings.
12. Do NOT return evidence objects with "source" and "detail" fields.
13. Keep the response concise but useful.

The response MUST follow exactly this structure:

{
  "summary": "string",
  "root_cause": "string",
  "failure_category": "string",
  "confidence": "string",
  "failed_stage_or_task": "string",
  "evidence": [
    "string"
  ],
  "suggested_fixes": [
    "string"
  ],
  "verification_steps": [
    "string"
  ],
  "preventive_actions": [
    "string"
  ],
  "uncertainty": [
    "string"
  ]
}

Field requirements:

summary:
A concise executive summary of what happened.

root_cause:
The concrete technical cause supported by the evidence.

failure_category:
Examples include:
- build/compilation
- test failure
- dependency
- configuration
- infrastructure
- agent/tooling
- authentication
- deployment
- network
- unknown

confidence:
Use one of:
- high
- medium
- low

failed_stage_or_task:
The first concrete pipeline stage/task that failed.

evidence:
An array of plain strings. Each string should explain the relevant evidence
and, where useful, identify its source.

suggested_fixes:
Concrete technical actions to address the root cause.

verification_steps:
Steps that can confirm the fix.

preventive_actions:
Actions that can reduce recurrence.

uncertainty:
Missing evidence, ambiguity or assumptions. Use [] when there is no material
uncertainty.
""".strip()

    # ========================================================
    # PAYLOAD SERIALIZATION
    # ========================================================

    def _serialize_payload(self, payload: Any) -> str:
        try:
            return json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        except Exception:
            return str(payload)

    # ========================================================
    # EXTRACT JSON
    # ========================================================

    def _extract_json(self, content: str) -> dict:
        if not content:
            raise RuntimeError(
                "The LLM returned an empty response."
            )

        content = content.strip()

        # Remove Markdown fences if the model ignored instructions.
        if content.startswith("```"):
            content = re.sub(
                r"^```(?:json)?\s*",
                "",
                content,
                flags=re.IGNORECASE,
            )

            content = re.sub(
                r"\s*```$",
                "",
                content,
            )

            content = content.strip()

        # First attempt: complete response is JSON.
        try:
            parsed = json.loads(content)

            if not isinstance(parsed, dict):
                raise RuntimeError(
                    "The LLM returned JSON, but the top-level value "
                    "was not an object."
                )

            return parsed

        except json.JSONDecodeError:
            pass

        # Second attempt: find JSON object inside surrounding text.
        start = content.find("{")
        end = content.rfind("}")

        if start >= 0 and end > start:
            candidate = content[start:end + 1]

            try:
                parsed = json.loads(candidate)

                if not isinstance(parsed, dict):
                    raise RuntimeError(
                        "The LLM returned JSON, but the top-level value "
                        "was not an object."
                    )

                return parsed

            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "The LLM response contained JSON-like content, "
                    "but it could not be parsed."
                ) from exc

        raise RuntimeError(
            "The LLM did not return a valid JSON object."
        )

    # ========================================================
    # NORMALIZE LLM RESPONSE
    # ========================================================

    def _normalize_result(self, result_data: dict) -> dict:
        """
        Normalize minor LLM formatting differences before Pydantic
        validation.

        This specifically handles evidence returned as:
            {"source": "...", "detail": "..."}
        instead of:
            "source: detail"
        """

        # ----------------------------------------------------
        # Required scalar fields
        # ----------------------------------------------------

        if not result_data.get("summary"):
            result_data["summary"] = (
                "The pipeline failure was analyzed from the "
                "available build evidence."
            )

        if not result_data.get("root_cause"):
            result_data["root_cause"] = (
                "The available evidence does not provide enough "
                "information to establish a definitive root cause."
            )

        if not result_data.get("failure_category"):
            result_data["failure_category"] = "unknown"

        if not result_data.get("confidence"):
            result_data["confidence"] = "low"

        if not result_data.get("failed_stage_or_task"):
            result_data["failed_stage_or_task"] = "Unknown"

        # ----------------------------------------------------
        # Evidence
        # ----------------------------------------------------

        evidence = result_data.get("evidence", [])

        if evidence is None:
            evidence = []

        if not isinstance(evidence, list):
            evidence = [str(evidence)]

        normalized_evidence = []

        for item in evidence:
            if isinstance(item, str):
                normalized_evidence.append(item)

            elif isinstance(item, dict):
                source = str(
                    item.get("source", "")
                ).strip()

                detail = str(
                    item.get("detail", "")
                ).strip()

                if source and detail:
                    normalized_evidence.append(
                        f"{source}: {detail}"
                    )
                elif detail:
                    normalized_evidence.append(detail)
                elif source:
                    normalized_evidence.append(source)
                else:
                    # Last resort for an unknown object shape.
                    normalized_evidence.append(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                        )
                    )

            else:
                normalized_evidence.append(str(item))

        result_data["evidence"] = normalized_evidence

        # ----------------------------------------------------
        # List fields
        # ----------------------------------------------------

        list_fields = [
            "suggested_fixes",
            "verification_steps",
            "preventive_actions",
            "uncertainty",
        ]

        for field in list_fields:
            value = result_data.get(field, [])

            if value is None:
                value = []

            if not isinstance(value, list):
                value = [value]

            normalized = []

            for item in value:
                if isinstance(item, str):
                    normalized.append(item)

                elif isinstance(item, dict):
                    # Convert accidental structured output into text.
                    normalized.append(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                        )
                    )

                else:
                    normalized.append(str(item))

            result_data[field] = normalized

        return result_data

    # ========================================================
    # VALIDATE RESULT
    # ========================================================

    def _validate_result(self, result_data: dict) -> RCAResult:
        normalized = self._normalize_result(result_data)

        try:
            return RCAResult.model_validate(normalized)

        except Exception as exc:
            raise RuntimeError(
                "The LLM returned JSON matching the expected top-level "
                "RCA structure, but it does not match the application's "
                "RCAResult Pydantic model.\n\n"
                f"Pydantic validation error:\n{exc}\n\n"
                f"Normalized response:\n"
                f"{json.dumps(normalized, indent=2, ensure_ascii=False)}"
            ) from exc

    # ========================================================
    # GROQ REQUEST
    # ========================================================

    def _analyze_with_groq(self, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.groq_model,
            temperature=0,
            response_format={
                "type": "json_object"
            },
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        if not response.choices:
            raise RuntimeError(
                "Groq returned no choices."
            )

        message = response.choices[0].message

        content = getattr(message, "content", None)

        if not content:
            raise RuntimeError(
                "Groq returned an empty message."
            )

        return content

    # ========================================================
    # AZURE OPENAI REQUEST
    # ========================================================

    def _analyze_with_azure_openai(
        self,
        user_prompt: str,
    ) -> str:

        response = self.client.chat.completions.create(
            model=self.azure_deployment,
            temperature=0,
            response_format={
                "type": "json_object"
            },
            messages=[
                {
                    "role": "system",
                    "content": self._build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        if not response.choices:
            raise RuntimeError(
                "Azure OpenAI returned no choices."
            )

        message = response.choices[0].message

        content = getattr(message, "content", None)

        if not content:
            raise RuntimeError(
                "Azure OpenAI returned an empty message."
            )

        return content

    # ========================================================
    # PUBLIC ANALYZE METHOD
    # ========================================================

    def analyze(self, payload: Any) -> RCAResult:
        payload_text = self._serialize_payload(payload)

        user_prompt = f"""
Analyze the following Azure DevOps pipeline evidence.

Do not invent facts.

Identify the actual technical root cause and distinguish it from warnings,
informational messages, or unrelated records.

PIPELINE EVIDENCE:

{payload_text}

Return ONLY the required JSON RCA structure.
""".strip()

        # ----------------------------------------------------
        # Call selected provider
        # ----------------------------------------------------

        if self.provider == "groq":
            raw_response = self._analyze_with_groq(
                user_prompt
            )

        else:
            raw_response = self._analyze_with_azure_openai(
                user_prompt
            )

        # ----------------------------------------------------
        # Parse JSON
        # ----------------------------------------------------

        try:
            result_data = self._extract_json(
                raw_response
            )

        except Exception as exc:
            raise RuntimeError(
                "The LLM did not return valid RCA JSON.\n\n"
                f"Raw response:\n{raw_response}"
            ) from exc

        # ----------------------------------------------------
        # Validate / normalize
        # ----------------------------------------------------

        return self._validate_result(result_data)
