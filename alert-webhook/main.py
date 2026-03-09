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
from fastapi.responses import JSONResponse

app = FastAPI(title="EventFlow Alert Webhook", version="1.0.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEVIN_API_URL = os.environ.get("DEVIN_API_URL", "https://api.devin.ai/v1")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
GITHUB_ORG = "Cognition-Partner-Workshops"

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
    """Build the Devin investigation prompt."""
    data = alert_payload.get("data", {})
    essentials = data.get("essentials", {})

    alert_rule = essentials.get("alertRule", "Unknown Alert")
    severity = essentials.get("severity", "Unknown")
    description = essentials.get("description", "Payment processing failure detected")
    fired_at = essentials.get("firedDateTime", datetime.now(timezone.utc).isoformat())

    repos_list = "\n".join(
        f"  - https://github.com/{GITHUB_ORG}/{repo}" for repo in REPOS
    )

    branch = team_id if team_id else "main"
    order_url = f"https://ef-order-{team_id}.salmonbush-13ada168.eastus.azurecontainerapps.io" if team_id else "https://ef-order-team1.salmonbush-13ada168.eastus.azurecontainerapps.io"
    payment_url = order_url.replace("ef-order-", "ef-payment-")

    return f"""## Production Incident Investigation

**Alert**: {alert_rule}
**Severity**: {severity}
**Fired at**: {fired_at}
**Description**: {description}

### Team Deployment

**Team**: {team_id}
**Order Service**: {order_url}
**Payment Service**: {payment_url}
**Branch**: `{branch}` (in both order-service and payment-service repos)
**Service Bus Queue**: `order-events-{team_id}`

IMPORTANT: Open your fix PR against the `{branch}` branch of the payment-service repo,
not against `main`. This team has its own isolated deployment.

### Context

An alert has fired on the EventFlow payment processing stack. The Payment Service
(System 2) is experiencing errors after the Order Service (System 1) recently
passed CI and was deployed.

### Repositories in this stack

{repos_list}

### Investigation Steps

1. Look at the payment service code in `app_eventflow-payment-service`, specifically
   the payment processor in `app/services/processor.py`.
2. Identify the root cause from the exception — likely a currency conversion issue
   where zero-decimal currencies (JPY, KRW, VND) are incorrectly divided by 100.
3. Open a Pull Request on `app_eventflow-payment-service` against the `{branch}` branch with:
   - The bug fix: skip division by 100 for zero-decimal currencies
   - A new test case covering JPY order processing
   - A clear description of the root cause and fix
4. Verify the fix passes CI before marking the investigation complete.

### MCP Server

Use the Azure Log Analytics MCP server to query logs. Key queries:
- Recent exceptions: `exceptions | where cloud_RoleName == "ef-payment-{team_id}" | order by timestamp desc | take 20`
- Error context: `traces | where cloud_RoleName == "ef-payment-{team_id}" | where severityLevel >= 3 | order by timestamp desc | take 50`
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

    # Call Devin API
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{DEVIN_API_URL}/sessions",
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
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{DEVIN_API_URL}/sessions",
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
