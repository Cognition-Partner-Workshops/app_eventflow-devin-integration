"""
Azure Function: Azure DevOps Service Hook → Devin API Relay

Receives webhook payloads from Azure DevOps service hooks when work items
are updated. If the work item has the "Devin:Discovery" tag, it creates
a new Devin session via the Devin API with the work item's description.
"""

import json
import logging
import os
import re

import azure.functions as func
import requests

app = func.FunctionApp()

DEVIN_API_BASE = "https://api.devin.ai/v3"
DEVIN_TAG = "Devin:Discovery"


def get_config():
    """Load required configuration from environment variables."""
    api_key = os.environ.get("DEVIN_API_KEY")
    org_id = os.environ.get("DEVIN_ORG_ID")
    if not api_key or not org_id:
        raise ValueError("DEVIN_API_KEY and DEVIN_ORG_ID must be set")
    return api_key, org_id


def extract_tags(work_item: dict) -> list[str]:
    """Extract tags from an Azure DevOps work item payload."""
    fields = work_item.get("fields", {})
    tags_str = fields.get("System.Tags", "")
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(";") if t.strip()]


def has_devin_tag(tags: list[str]) -> bool:
    """Check if the Devin:Discovery tag is present (case-insensitive)."""
    return any(t.lower() == DEVIN_TAG.lower() for t in tags)


def build_prompt(work_item: dict, work_item_id: int, work_item_url: str) -> str:
    """Build a Devin session prompt from the work item details."""
    fields = work_item.get("fields", {})
    title = fields.get("System.Title", "No title")
    description = fields.get("System.Description", "")
    work_item_type = fields.get("System.WorkItemType", "Work Item")

    # Strip HTML tags from description
    if description:
        description = re.sub(r"<[^>]+>", "", description).strip()

    prompt_parts = [
        f"Azure DevOps {work_item_type} #{work_item_id}: {title}",
    ]
    if description:
        prompt_parts.append(f"\nDescription:\n{description}")
    if work_item_url:
        prompt_parts.append(f"\nSource: {work_item_url}")

    return "\n".join(prompt_parts)


def create_devin_session(api_key: str, org_id: str, prompt: str) -> dict:
    """Create a new Devin session via the API."""
    url = f"{DEVIN_API_BASE}/organizations/{org_id}/sessions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"prompt": prompt}

    logging.info("Creating Devin session for org %s", org_id)
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


@app.function_name(name="DevOpsWebhook")
@app.route(route="devops-webhook", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def devops_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger that receives Azure DevOps service hook payloads.

    Expected event type: workitem.updated
    Trigger condition: Work item tagged with "Devin:Discovery"
    """
    logging.info("Received Azure DevOps webhook request")

    try:
        body = req.get_json()
    except ValueError:
        logging.error("Invalid JSON payload")
        return func.HttpResponse("Invalid JSON", status_code=400)

    event_type = body.get("eventType", "")
    logging.info("Event type: %s", event_type)

    # Accept both workitem.updated and workitem.created
    if event_type not in ("workitem.updated", "workitem.created"):
        logging.info("Ignoring event type: %s", event_type)
        return func.HttpResponse(
            json.dumps({"status": "ignored", "reason": f"event type '{event_type}' not handled"}),
            mimetype="application/json",
        )

    resource = body.get("resource", {})

    # For workitem.updated, the work item is under resource.revision
    # For workitem.created, it's directly under resource
    if event_type == "workitem.updated":
        work_item = resource.get("revision", resource)
    else:
        work_item = resource

    work_item_id = resource.get("id") or work_item.get("id", 0)
    work_item_url = resource.get("_links", {}).get("html", {}).get("href", "")
    if not work_item_url:
        work_item_url = resource.get("url", "")

    tags = extract_tags(work_item)
    logging.info("Work item #%s tags: %s", work_item_id, tags)

    if not has_devin_tag(tags):
        logging.info("Work item #%s does not have '%s' tag, skipping", work_item_id, DEVIN_TAG)
        return func.HttpResponse(
            json.dumps({"status": "skipped", "reason": f"'{DEVIN_TAG}' tag not found"}),
            mimetype="application/json",
        )

    prompt = build_prompt(work_item, work_item_id, work_item_url)
    logging.info("Built prompt for work item #%s: %s", work_item_id, prompt[:200])

    try:
        api_key, org_id = get_config()
    except ValueError as e:
        logging.error("Configuration error: %s", e)
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(e)}),
            status_code=500,
            mimetype="application/json",
        )

    try:
        result = create_devin_session(api_key, org_id, prompt)
        session_url = result.get("url", "")
        session_id = result.get("session_id", "")
        logging.info("Devin session created: %s (ID: %s)", session_url, session_id)

        return func.HttpResponse(
            json.dumps({
                "status": "session_created",
                "work_item_id": work_item_id,
                "devin_session_id": session_id,
                "devin_session_url": session_url,
            }),
            mimetype="application/json",
        )
    except requests.exceptions.RequestException as e:
        logging.error("Devin API error: %s", e)
        return func.HttpResponse(
            json.dumps({"status": "error", "message": f"Devin API call failed: {e}"}),
            status_code=502,
            mimetype="application/json",
        )
