# Drug Email QA Prototype

A simple healthcare email QA prototype for drug awareness campaigns.

It generates an email draft, evaluates the output against campaign rules, and retries until the draft passes the review checks. The project includes both a CLI mode and two UI options:
- lightweight browser UI (`ui/server.py` + `ui/index.html`)
- Streamlit UI (`ui/app.py`)

## What this project includes
- `app.py`: CLI entry point for campaign verification
- `graph.py`: verification loop orchestration, feedback retry, and structured logs
- `agents/generator.py`: model selection + prompt builder + fallback behavior
- `agents/reviewers.py`: reviewer logic for medical, brand, email, compliance, and image checks
- `agents/image_analyzer.py`: image metadata analysis for uploaded assets
- `knowledge/`: campaign documentation, brand guidance, compliance rules, and image metadata
- `ui/index.html`: browser interface for local HTML UI
- `ui/server.py`: HTTP server for the browser UI
- `ui/app.py`: Streamlit frontend alternative
- `tests/test_verification_loop.py`: basic regression test for the review loop
- `.gitignore`: files to keep out of version control

## Rule coverage and reviewer checks
The review logic in `agents/reviewers.py` uses an LLM-as-a-judge pattern to enforce:

### Medical accuracy
- disallows unsupported claims such as `cure`, `guarantee`, `prevent`, `eliminate`, `miracle`, `instant`
- requires the drug name to appear in the email text

### Brand and CTA guidelines
- flags overly promotional CTA wording such as `buy now` or `act now`
- requires educational/friendly CTA wording like `learn more` or `speak with`

### Email structure
- requires a `Subject:` line
- requires a `Body:` or `Message:` section
- requires a `CTA:` or `Call to Action:` section
- checks for professional guidance language such as `professional` / `healthcare professional`
- checks that the email is not excessively long

### Compliance
- checks text against compliance guidance loaded from `knowledge/compliance_rules.md`
- if the compliance text mentions safety, it requires the email to mention safety
- if the compliance text mentions disclaimers, it requires the email to mention disclaimer language

### Image review
- if an image is uploaded, it checks whether the detected caption supports the awareness message
- if no image is uploaded, the flow continues without an image failure

## Setup
1. Activate your virtual environment.

PowerShell:
```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt:
```cmd
.\.venv\Scripts\activate.bat
```

2. Install dependencies:
```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration
Create a local `.env` file in the project root with Azure or OpenAI credentials.

### Azure OpenAI example
```ini
AZURE_OPENAI_API_KEY=your_key_here
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
```

### Azure AI Services example
```ini
AZURE_OPENAI_ENDPOINT=https://<your-resource>.services.ai.azure.com/openai/v1
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
```

> For Azure AI Services, the code can use `AZURE_OPENAI_API_KEY` if present, or `DefaultAzureCredential` from `azure-identity` when running in an authenticated Azure environment.

> For classic Azure OpenAI, do not include `/openai/v1` in `AZURE_OPENAI_ENDPOINT`. Use the base resource URL only.

### OpenAI example
```ini
OPENAI_API_KEY=your_key_here
```

## Running the project

### CLI mode
```powershell
python app.py
```

### Browser UI (FastAPI)
```powershell
python ui/server.py
```
open your browser at `http://127.0.0.1:8000`

The browser UI uses FastAPI and exposes:
- `GET /` — main UI
- `GET /health` — readiness check
- `POST /run` — same verification loop as `app.py`
- `POST /export/html` and `POST /export/text` — download generated emails

### Streamlit UI
```powershell
streamlit run ui/app.py
```

## Project flow
1. `app.py` or the UI builds the campaign payload.
2. `graph.py` calls `run_verification_loop()`.
3. `agents/generator.py` selects either Azure OpenAI or OpenAI and sends the prompt.
4. `agents/reviewers.py` applies review checks to the email.
5. If the draft fails, the loop retries using review issues as feedback.
6. The final result includes the email, review summary, and structured logs.

## Troubleshooting
- `404 Resource not found`: usually wrong Azure endpoint or deployment name in `.env`
- `OpenAI` / `AzureOpenAI` import failure: missing dependencies or bad virtual environment
- If you use `ui/app.py`, install `streamlit` and run `streamlit run ui/app.py`
- Configuration errors will surface immediately at startup via `pydantic-settings` validation.

## Notes
- The project includes two UI options; `ui/server.py` is the lightweight browser server, and `ui/app.py` is the Streamlit frontend.
- `.gitignore` already excludes `.venv`, `.env`, `__pycache__`, `uploads/`, and VS Code settings.
