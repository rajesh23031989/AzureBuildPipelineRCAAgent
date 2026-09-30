import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from llm_analyzer import LLMAnalyzer
from models import RCAResult


class LLMAnalyzerTests(unittest.TestCase):
    def test_cs0103_suggestions_are_specific_to_unresolved_name(self):
        result_data = {
            "summary": "The hosted Ubuntu agent failed provisioning.",
            "root_cause": "The Ubuntu image migration broke the build.",
            "confidence": "high",
            "failure_category": "agent/tooling",
            "failed_stage_or_task": "Test",
            "evidence": [],
        }
        analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
        analyzer.model = "test-model"
        analyzer.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content=json.dumps(result_data)
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
        compiler_log = (
            "EmployeeServiceTests.cs(8,6): error CS0103: The name "
            "'InvalidCodeToTestPipeline' does not exist in the current context"
        )

        result = analyzer.analyze(
            {
                "build": {"id": 123},
                "evidence": [compiler_log],
                "changes": [],
            }
        )

        self.assertEqual(result.failure_category, "compilation")
        self.assertIn("InvalidCodeToTestPipeline", result.root_cause)
        self.assertTrue(
            any("spelled exactly" in fix for fix in result.suggested_fixes)
        )
        self.assertTrue(
            any("declare it" in fix for fix in result.suggested_fixes)
        )
        self.assertIn("Ubuntu", result.root_cause) is False

    def test_compiler_diagnostic_overrides_unsupported_agent_cause(self):
        model_response = {
            "summary": "The hosted Ubuntu agent failed during provisioning.",
            "root_cause": "The Ubuntu 26 image migration broke provisioning.",
            "confidence": "high",
            "failure_category": "agent/tooling",
            "failed_stage_or_task": "Build",
            "evidence": ["Hosted agent image migration."],
        }
        analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
        analyzer.model = "test-model"
        analyzer.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content=json.dumps(model_response)
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )

        compiler_log = (
            "/home/vsts/work/1/s/tests/EmployeeManagement.Tests/"
            "EmployeeServiceTests.cs(8,6): error CS0246: The type or namespace "
            "name 'FactAttribute' could not be found (are you missing a using "
            "directive or an assembly reference?)"
        )
        result = analyzer.analyze(
            {
                "build": {"id": 123},
                "evidence": [compiler_log],
                "changes": [],
            }
        )

        self.assertEqual(result.failure_category, "compilation")
        self.assertIn("Fact/FactAttribute", result.root_cause)
        self.assertNotIn("Ubuntu 26", result.root_cause)
        self.assertTrue(any("CS0246" in item for item in result.evidence))

    def test_analyze_returns_validated_rca_result(self):
        result_data = {
            "summary": "The build failed during compilation.",
            "root_cause": "Compiler error CS0246 indicates a missing type.",
            "confidence": "high",
            "failure_category": "compilation",
            "failed_stage_or_task": "Build",
            "evidence": ["error CS0246: type or namespace not found"],
            "suggested_fixes": ["Restore the missing type or dependency."],
            "verification_steps": ["Rerun the build."],
            "preventive_actions": [],
            "uncertainty": [],
        }
        analyzer = LLMAnalyzer.__new__(LLMAnalyzer)
        analyzer.model = "test-model"
        analyzer.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=Mock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content=json.dumps(result_data)
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )

        result = analyzer.analyze(
            {
                "build": {"id": 123},
                "evidence": ["error CS0246: type or namespace not found"],
                "changes": [],
            }
        )

        self.assertIsInstance(result, RCAResult)
        self.assertEqual(result.failure_category, "compilation")
        analyzer.client.chat.completions.create.assert_called_once()