import unittest
from types import SimpleNamespace

from ado_client import AzureDevOpsClient


class AzureDevOpsClientTests(unittest.TestCase):
    def test_build_number_lookup_preserves_dotted_number(self):
        client = AzureDevOpsClient("org", "project", "pat")
        response = SimpleNamespace(
            ok=True,
            json=lambda: {"value": [{"id": 456, "buildNumber": "20260930.1"}]},
        )
        requests = []
        client.session.get = lambda *args, **kwargs: (
            requests.append((args, kwargs)) or response
        )

        build = client.get_build_by_number("20260930.1")

        self.assertEqual(build["id"], 456)
        self.assertEqual(requests[0][1]["params"]["buildNumber"], "20260930.1")

    def test_unauthorized_response_has_actionable_authentication_guidance(self):
        client = AzureDevOpsClient("org", "project", "pat")
        client.session.get = lambda *args, **kwargs: SimpleNamespace(
            ok=False,
            status_code=401,
            reason="Unauthorized",
            text="unauthorized",
        )

        with self.assertRaisesRegex(RuntimeError, "Build: Read access"):
            client.get_build(123)