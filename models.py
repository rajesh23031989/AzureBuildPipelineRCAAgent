from typing import List, Optional
from pydantic import BaseModel, Field

class BuildSummary(BaseModel):
    id: int
    build_number: str = ""
    status: str = ""
    result: str = ""
    definition_name: str = ""
    source_branch: str = ""
    source_version: str = ""
    queue_time: str = ""
    start_time: str = ""
    finish_time: str = ""

class RCAResult(BaseModel):
    summary: str
    root_cause: str
    confidence: str
    failure_category: str
    failed_stage_or_task: str
    evidence: List[str] = Field(default_factory=list)
    suggested_fixes: List[str] = Field(default_factory=list)
    verification_steps: List[str] = Field(default_factory=list)
    preventive_actions: List[str] = Field(default_factory=list)
    uncertainty: List[str] = Field(default_factory=list)
