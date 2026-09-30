import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    ado_organization: str
    ado_project: str
    ado_pat: str

    llm_provider: str

    # Groq
    groq_api_key: str
    groq_model: str

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str

    context_lines: int
    max_log_chars: int


def get_settings() -> Settings:
    return Settings(
        ado_organization=os.getenv("ADO_ORGANIZATION", "").strip(),
        ado_project=os.getenv("ADO_PROJECT", "").strip(),
        ado_pat=os.getenv("ADO_PAT", "").strip(),

        llm_provider=os.getenv(
            "LLM_PROVIDER",
            "azure_openai"
        ).strip().lower(),

        # Groq
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-120b"
        ).strip(),

        # Azure OpenAI
        azure_openai_endpoint=os.getenv(
            "AZURE_OPENAI_ENDPOINT",
            ""
        ).strip(),
        azure_openai_api_key=os.getenv(
            "AZURE_OPENAI_API_KEY",
            ""
        ).strip(),
        azure_openai_deployment=os.getenv(
            "AZURE_OPENAI_DEPLOYMENT",
            ""
        ).strip(),
        azure_openai_api_version=os.getenv(
            "AZURE_OPENAI_API_VERSION",
            ""
        ).strip(),

        context_lines=int(
            os.getenv("CONTEXT_LINES", "12")
        ),
        max_log_chars=int(
            os.getenv("MAX_LOG_CHARS", "50000")
        ),
    )
