"""Alert Webhook — Container App replacement for Azure Function.

Receives Azure Monitor alert webhooks and creates Devin API sessions
to automatically investigate production incidents. Deployed as an
Azure Container App for zero-cost operation at demo scale.
"""

import json
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="EventFlow Alert Webhook", version="1.0.0")

# Allow storefront origins to call the proxy endpoint
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://ef-store-team\d+\..*\.azurecontainerapps\.io",
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEVIN_API_BASE = os.environ.get("DEVIN_API_BASE", "https://api.devin.ai")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
DEVIN_ORG_ID = os.environ.get("DEVIN_ORG_ID", "")
GITHUB_ORG = "Cognition-Partner-Workshops"


def _devin_sessions_url() -> str:
    """Build the Devin API sessions URL (v3 with org ID)."""
    return f"{DEVIN_API_BASE}/v3/organizations/{DEVIN_ORG_ID}/sessions"

REPOS = [
    "app_eventflow-order-service",
    "app_eventflow-payment-service",
    "app_eventflow-infra",
    "app_eventflow-storefront",
]


def extract_team_id(payload: dict) -> str:
    """Extract team ID from Azure Monitor Common Alert Schema payload."""
    data = payload.get("data", {})
    alert_context = data.get("alertContext", {})
    conditions = alert_context.get("conditions", [])

    for condition in conditions:
        dimensions = condition.get("dimensions", [])
        for dim in dimensions:
            if dim.get("name") == "cloud_RoleName":
                role_name = dim.get("value", "")
                if "team" in role_name:
                    parts = role_name.split("team")
                    if len(parts) > 1:
                        return f"team{parts[-1]}"
    return ""


def build_prompt(team_id: str, alert_payload: dict) -> str:
    """Build the Devin investigation prompt.

    Describes operational symptoms only — does NOT reveal the root cause.
    Devin must investigate the code and services to figure out what's wrong.
    """
    data = alert_payload.get("data", {})
    essentials = data.get("essentials", {})

    fired_at = essentials.get("firedDateTime", datetime.now(timezone.utc).isoformat())

    repos_list = "\n".join(
        f"  - https://github.com/{GITHUB_ORG}/{repo}" for repo in REPOS
    )

    branch = team_id if team_id else "main"
    order_url = f"https://ef-order-{team_id}.salmonbush-13ada168.eastus.azurecontainerapps.io" if team_id else "https://ef-order-team1.salmonbush-13ada168.eastus.azurecontainerapps.io"
    payment_url = order_url.replace("ef-order-", "ef-payment-")

    return f"""## Production Incident — Service Outage

**Team**: {team_id}
**Severity**: Critical — customer-facing failure
**Time detected**: {fired_at}

### What We Know

Our e-commerce platform has two backend services: an **Order Service** that accepts
customer orders and publishes events, and a **Payment Service** that consumes those
events and processes payments.

**Operational symptoms:**
- Customers placing orders in certain currencies see a long delay followed by a generic "Unable to Process Order" error
- Orders in USD complete successfully with no issues
- The Payment Service appears to be crashing or failing intermittently — health checks are failing
- Affected orders remain stuck in "pending" status and never complete
- The Order Service is healthy and accepting orders normally — the problem is downstream

### Production Log Access

You have Azure CLI access to query production logs. Use these commands to investigate:

```bash
# Login to Azure (credentials are pre-configured as environment variables)
az login --service-principal -u $AZURE_CLIENT_ID -p $AZURE_CLIENT_SECRET --tenant $AZURE_TENANT_ID -o none

# Query payment service logs for errors (excluding health checks)
az monitor log-analytics query \\
  --workspace "4cf2afba-136e-4018-9f2d-42b3dbafc3a8" \\
  --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(2h) | where ContainerAppName_s contains 'payment' | where Log_s !contains 'GET /health' | order by TimeGenerated desc | take 30 | project TimeGenerated, ContainerAppName_s, Log_s" \\
  -o table

# Query order service logs
az monitor log-analytics query \\
  --workspace "4cf2afba-136e-4018-9f2d-42b3dbafc3a8" \\
  --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(2h) | where ContainerAppName_s contains 'order' | where Log_s !contains 'GET /health' | order by TimeGenerated desc | take 30 | project TimeGenerated, ContainerAppName_s, Log_s" \\
  -o table

# Search for specific error patterns
az monitor log-analytics query \\
  --workspace "4cf2afba-136e-4018-9f2d-42b3dbafc3a8" \\
  --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(2h) | where Log_s contains 'ERROR' or Log_s contains 'Exception' or Log_s contains 'Traceback' | order by TimeGenerated desc | take 30 | project TimeGenerated, ContainerAppName_s, Log_s" \\
  -o table
```

**IMPORTANT**: Start your investigation by querying these production logs FIRST before looking at the code. The logs will show you exactly what is happening at runtime.

**Azure credentials** (set these as env vars before running az commands):
- `AZURE_CLIENT_ID`: `634896cd-4b23-401e-88fe-fd6d56862295`
- `AZURE_CLIENT_SECRET`: `fwH8Q~5yzs0XcE1qqg0MSd6_gPDlevdOFrLsDa7D`
- `AZURE_TENANT_ID`: `0aade1a4-add3-468e-8198-ad96545fc0da`

### Live Environment

- **Order Service**: {order_url}
- **Payment Service**: {payment_url}
- Both services have Swagger docs at `/docs` and health endpoints at `/health`
- Orders can be viewed at `GET /api/orders` on the Order Service

### Repositories in this stack

{repos_list}

All repos use the `{branch}` branch for this team's deployment.

### Your Task

1. **Query production logs** — Use the Azure CLI commands above to pull error logs from the payment service and order service. Identify the exception/crash pattern.
2. **Investigate** — Based on what the logs reveal, examine the source code to understand the root cause.
3. **Fix** — Open a Pull Request on the appropriate repository against the `{branch}` branch with the bug fix and a new test case that covers the failure scenario.
4. **Verify** — Make sure the fix passes CI before marking the investigation complete.

IMPORTANT: Open your fix PR against the `{branch}` branch, not `main`. This team has its own isolated deployment.
"""


@app.get("/health")
async def health():
    """Health check endpoint for Container App probes."""
    return {"status": "healthy", "service": "eventflow-alert-webhook"}


@app.post("/alert-webhook")
async def alert_webhook(request: Request):
    """Receive Azure Monitor alert webhook and create Devin session."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    team_id = extract_team_id(payload)
    logger.info("Alert received for team: %s", team_id or "unknown")

    if not DEVIN_API_KEY:
        logger.error("DEVIN_API_KEY not configured")
        return JSONResponse(
            {"error": "DEVIN_API_KEY not configured", "team_id": team_id},
            status_code=500,
        )

    prompt = build_prompt(team_id, payload)

    # Call Devin API (v3)
    try:
        url = _devin_sessions_url()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {DEVIN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt},
            )
            response.raise_for_status()
            result = response.json()

        logger.info("Devin session created: %s", result.get("session_id", "unknown"))
        return JSONResponse({
            "status": "investigation_started",
            "team_id": team_id,
            "devin_session_id": result.get("session_id"),
            "devin_url": result.get("url"),
        })

    except httpx.HTTPStatusError as e:
        logger.error("Devin API error: %s %s", e.response.status_code, e.response.text)
        return JSONResponse(
            {"error": f"Devin API returned {e.response.status_code}", "team_id": team_id},
            status_code=502,
        )
    except Exception as e:
        logger.exception("Failed to create Devin session")
        return JSONResponse(
            {"error": str(e), "team_id": team_id},
            status_code=500,
        )


class InvestigateRequest(BaseModel):
    """Request body for the ops dashboard proxy endpoint."""
    team_id: str
    prompt: str


@app.post("/investigate")
async def investigate_proxy(body: InvestigateRequest):
    """Proxy endpoint for the ops dashboard — accepts a prompt from the
    storefront UI and forwards it to the Devin API server-side,
    avoiding browser CORS restrictions."""

    if not DEVIN_API_KEY:
        return JSONResponse(
            {"error": "DEVIN_API_KEY not configured", "team_id": body.team_id},
            status_code=500,
        )

    try:
        url = _devin_sessions_url()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {DEVIN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"prompt": body.prompt},
            )
            response.raise_for_status()
            result = response.json()

        logger.info("Devin session created via proxy for %s: %s", body.team_id, result.get("session_id", "unknown"))
        return JSONResponse({
            "status": "investigation_started",
            "team_id": body.team_id,
            "devin_session_id": result.get("session_id"),
            "devin_url": result.get("url"),
        })

    except httpx.HTTPStatusError as e:
        logger.error("Devin API error (proxy): %s %s", e.response.status_code, e.response.text)
        return JSONResponse(
            {"error": f"Devin API returned {e.response.status_code}", "detail": e.response.text, "team_id": body.team_id},
            status_code=502,
        )
    except Exception as e:
        logger.exception("Failed to create Devin session (proxy)")
        return JSONResponse(
            {"error": str(e), "team_id": body.team_id},
            status_code=500,
        )


@app.post("/trigger/{team_id}")
async def manual_trigger(team_id: str):
    """Manual trigger endpoint — creates a Devin session for a specific team
    without requiring an Azure Monitor alert payload. Useful for testing."""

    if not DEVIN_API_KEY:
        return JSONResponse(
            {"error": "DEVIN_API_KEY not configured", "team_id": team_id},
            status_code=500,
        )

    mock_payload = {
        "data": {
            "essentials": {
                "alertRule": "Payment Processing Failure",
                "severity": "Sev1",
                "description": f"Payment service errors detected for {team_id}",
                "firedDateTime": datetime.now(timezone.utc).isoformat(),
            },
            "alertContext": {
                "conditions": [{
                    "dimensions": [{
                        "name": "cloud_RoleName",
                        "value": f"ef-payment-{team_id}",
                    }]
                }]
            },
        }
    }

    prompt = build_prompt(team_id, mock_payload)

    try:
        url = _devin_sessions_url()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {DEVIN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt},
            )
            response.raise_for_status()
            result = response.json()

        return JSONResponse({
            "status": "investigation_started",
            "team_id": team_id,
            "devin_session_id": result.get("session_id"),
            "devin_url": result.get("url"),
        })

    except Exception as e:
        logger.exception("Failed to create Devin session")
        return JSONResponse(
            {"error": str(e), "team_id": team_id},
            status_code=500,
        )
