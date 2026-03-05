"""Azure Function: Alert Webhook → Devin API trigger.

Receives Azure Monitor Common Alert Schema payloads and creates
Devin API sessions to investigate production incidents automatically.
"""

import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func
import requests

app = func.FunctionApp()

logger = logging.getLogger(__name__)

DEVIN_API_URL = os.environ.get("DEVIN_API_URL", "https://api.devin.ai/v1")
DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
GITHUB_ORG = os.environ.get("GITHUB_ORG", "Cognition-Partner-Workshops")
REPOS = os.environ.get(
    "REPOS",
    "app_eventflow-order-service,app_eventflow-payment-service,app_eventflow-infra,app_eventflow-devin-integration",
)


def parse_common_alert_schema(payload: dict) -> dict:
    """Extract relevant fields from the Azure Monitor Common Alert Schema.

    Args:
        payload: The raw alert webhook payload.

    Returns:
        A dict with extracted alert context.
    """
    schema_id = payload.get("schemaId", "")
    data = payload.get("data", {})
    essentials = data.get("essentials", {})
    alert_context = data.get("alertContext", {})

    return {
        "alert_id": essentials.get("alertId", "unknown"),
        "alert_rule": essentials.get("alertRule", "unknown"),
        "severity": essentials.get("severity", "unknown"),
        "description": essentials.get("description", ""),
        "fired_at": essentials.get("firedDateTime", datetime.now(timezone.utc).isoformat()),
        "condition_type": alert_context.get("conditionType", ""),
        "conditions": alert_context.get("conditions", []),
        "schema_id": schema_id,
    }


def build_devin_prompt(alert_info: dict) -> str:
    """Build the investigation prompt for the Devin API session.

    Args:
        alert_info: Parsed alert information.

    Returns:
        A structured prompt string for the Devin agent.
    """
    repos_list = "\n".join(
        f"  - https://github.com/{GITHUB_ORG}/{repo.strip()}"
        for repo in REPOS.split(",")
    )

    return f"""## Production Incident Investigation

**Alert**: {alert_info['alert_rule']}
**Severity**: {alert_info['severity']}
**Fired at**: {alert_info['fired_at']}
**Description**: {alert_info['description']}

### Context

An alert has fired on the EventFlow payment processing stack. The Payment Service
(System 2) is experiencing errors after the Order Service (System 1) recently
passed CI and was deployed.

### Repositories in this stack

{repos_list}

### Investigation Steps

1. Connect to Azure Log Analytics using the MCP server to query recent exceptions
   from the `eventflow-payment-service` application.
2. Identify the root cause from the exception stack traces and log entries.
3. Trace the issue across the Order Service and Payment Service codebases.
4. Open a Pull Request on the affected repository with:
   - The bug fix
   - A new test case that covers the failing scenario
   - A clear description of the root cause and fix
5. Verify the fix passes CI before marking the investigation complete.

### MCP Server

Use the Azure Log Analytics MCP server to query logs. Key queries:
- Recent exceptions: `exceptions | where cloud_RoleName == "eventflow-payment-service" | order by timestamp desc | take 20`
- Error context: `traces | where cloud_RoleName == "eventflow-payment-service" | where severityLevel >= 3 | order by timestamp desc | take 50`
"""


def create_devin_session(prompt: str, alert_info: dict) -> dict:
    """Call the Devin API to create a new investigation session.

    Args:
        prompt: The investigation prompt.
        alert_info: Parsed alert info for metadata.

    Returns:
        The Devin API response.
    """
    if not DEVIN_API_KEY:
        logger.error("DEVIN_API_KEY is not set — cannot create session")
        return {"error": "DEVIN_API_KEY not configured"}

    headers = {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt,
        "metadata": {
            "source": "azure-monitor-alert",
            "alert_id": alert_info["alert_id"],
            "alert_rule": alert_info["alert_rule"],
            "severity": alert_info["severity"],
        },
    }

    try:
        response = requests.post(
            f"{DEVIN_API_URL}/sessions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Devin session created: %s",
            result.get("session_id", "unknown"),
        )
        return result

    except requests.RequestException:
        logger.exception("Failed to create Devin session")
        return {"error": "Failed to call Devin API"}


@app.function_name("alert_webhook")
@app.route(route="alert-webhook", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def alert_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP trigger that receives Azure Monitor alert webhooks.

    Parses the Common Alert Schema, builds an investigation prompt,
    and creates a Devin API session to investigate the incident.
    """
    logger.info("Alert webhook triggered")

    try:
        payload = req.get_json()
    except ValueError:
        logger.error("Invalid JSON in request body")
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    # Parse the alert
    alert_info = parse_common_alert_schema(payload)
    logger.info(
        "Alert received: rule=%s severity=%s",
        alert_info["alert_rule"],
        alert_info["severity"],
    )

    # Build the investigation prompt
    prompt = build_devin_prompt(alert_info)

    # Create a Devin session
    result = create_devin_session(prompt, alert_info)

    response_body = {
        "status": "investigation_started" if "error" not in result else "error",
        "alert_id": alert_info["alert_id"],
        "alert_rule": alert_info["alert_rule"],
        "devin_session": result.get("session_id"),
        "devin_url": result.get("url"),
    }

    status_code = 200 if "error" not in result else 500
    return func.HttpResponse(
        json.dumps(response_body),
        status_code=status_code,
        mimetype="application/json",
    )
