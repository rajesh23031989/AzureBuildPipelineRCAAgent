# Azure DevOps Pipeline RCA AI Agent

An AI agent that:
1. Finds a build by ID or the latest failed build.
2. Reads build metadata.
3. Reads the Azure DevOps build timeline.
4. Identifies failed timeline records/tasks.
5. Downloads relevant build logs.
6. Extracts error-focused log windows.
7. Sends structured evidence to an LLM.
8. Produces root-cause analysis and actionable fixes.
9. Displays the result in Streamlit.

See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the component architecture,
analysis flow, data boundaries, and current scope.

## Run

    py -3.12 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

Copy `.env.example` to `.env`, configure it, then:

    .venv\Scripts\python.exe -m streamlit run streamlit_app.py

For Azure DevOps access, set `ADO_ORGANIZATION`, `ADO_PROJECT`, and `ADO_PAT`
in the local `.env` file. The PAT must be valid and unexpired, with at least
`Build: Read` scope. Keep real credentials out of `.env.example` and source
control; revoke and replace any credential that has been committed or shared.

## LLM provider

The project is configured for the Azure AI Foundry OpenAI-compatible v1 API.
Set `LLM_PROVIDER=azure_openai` and provide the endpoint, API key, and
deployment name in `.env`.

For production/team use, keep credentials server-side and do not expose a personal PAT in browser code.

## Next production step

Put this agent behind FastAPI and use Microsoft Entra ID/service identity for Azure DevOps access. Then add an Azure DevOps service hook so a failed build automatically triggers RCA.
