import base64
from typing import Any, Dict, List, Optional
import requests

class AzureDevOpsClient:
    API_VERSION = "7.1"

    def __init__(self, organization: str, project: str, pat: str):
        if not organization or not project or not pat:
            raise ValueError("ADO_ORGANIZATION, ADO_PROJECT and ADO_PAT are required.")

        token = base64.b64encode(f":{pat}".encode()).decode()

        self.base_url = f"https://dev.azure.com/{organization}/{project}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "User-Agent": "ADO-Pipeline-RCA-Agent/1.0",
        })

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None):
        params = params or {}
        params.setdefault("api-version", self.API_VERSION)

        response = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            timeout=60,
        )

        if not response.ok:
            raise RuntimeError(
                f"Azure DevOps API failed: {response.status_code} "
                f"{response.reason}\n{response.text[:1000]}"
            )
        return response

    def get_build(self, build_id: int) -> Dict[str, Any]:
        return self._get(f"_apis/build/builds/{build_id}").json()

    def get_build_by_number(self, build_number: str) -> Dict[str, Any]:
        builds = self._get(
            "_apis/build/builds",
            params={"buildNumber": build_number, "$top": 1},
        ).json().get("value", [])

        if not builds:
            raise RuntimeError(
                f"No build was found with build number {build_number!r}."
            )

        return builds[0]

    def list_builds(
        self,
        result_filter: Optional[str] = None,
        top: int = 20,
    ) -> List[Dict[str, Any]]:
        params = {"$top": top}
        if result_filter:
            params["resultFilter"] = result_filter

        return self._get("_apis/build/builds", params).json().get("value", [])

    def get_latest_failed_build(self) -> Dict[str, Any]:
        builds = self.list_builds(result_filter="failed", top=20)
        if not builds:
            raise RuntimeError("No failed builds were found.")
        return builds[0]

    def get_timeline(self, build_id: int) -> Dict[str, Any]:
        return self._get(f"_apis/build/builds/{build_id}/timeline").json()

    def get_build_logs_metadata(self, build_id: int) -> List[Dict[str, Any]]:
        return self._get(f"_apis/build/builds/{build_id}/logs").json().get("value", [])

    def get_build_log(self, build_id: int, log_id: int) -> str:
        return self._get(f"_apis/build/builds/{build_id}/logs/{log_id}").text

    def get_changes(self, build_id: int, top: int = 20) -> List[Dict[str, Any]]:
        return self._get(
            f"_apis/build/builds/{build_id}/changes",
            params={"$top": top},
        ).json().get("value", [])
