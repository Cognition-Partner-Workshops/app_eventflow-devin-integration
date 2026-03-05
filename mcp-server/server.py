"""MCP Server for Azure Log Analytics — gives Devin access to production logs.

This server implements the Model Context Protocol (MCP) to expose
Azure Log Analytics queries as tools that the Devin agent can invoke
during incident investigation.

Run with: python server.py
"""

import json
import logging
import os
from datetime import datetime, timezone

from azure.identity import ClientSecretCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Azure configuration
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET", "")
WORKSPACE_ID = os.environ.get("AZURE_LOG_ANALYTICS_WORKSPACE_ID", "")


def get_logs_client() -> LogsQueryClient | None:
    """Create an authenticated Azure Log Analytics query client.

    Returns:
        A LogsQueryClient instance, or None if credentials are not configured.
    """
    if not all([AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET]):
        logger.warning("Azure credentials not configured")
        return None

    credential = ClientSecretCredential(
        tenant_id=AZURE_TENANT_ID,
        client_id=AZURE_CLIENT_ID,
        client_secret=AZURE_CLIENT_SECRET,
    )
    return LogsQueryClient(credential)


def query_logs(query: str, timespan: str = "PT1H") -> list[dict]:
    """Execute a Kusto query against Azure Log Analytics.

    Args:
        query: KQL query string.
        timespan: ISO 8601 duration (default: last 1 hour).

    Returns:
        List of result rows as dicts.
    """
    client = get_logs_client()
    if client is None:
        return [{"error": "Log Analytics client not configured"}]

    if not WORKSPACE_ID:
        return [{"error": "AZURE_LOG_ANALYTICS_WORKSPACE_ID not set"}]

    try:
        response = client.query_workspace(
            workspace_id=WORKSPACE_ID,
            query=query,
            timespan=timespan,
        )

        if response.status == LogsQueryStatus.SUCCESS:
            rows = []
            for table in response.tables:
                columns = [col.name for col in table.columns]
                for row in table.rows:
                    rows.append(dict(zip(columns, row)))
            return rows
        else:
            return [{"error": f"Query returned partial results: {response.partial_error}"}]

    except Exception as exc:
        logger.exception("Log Analytics query failed")
        return [{"error": str(exc)}]


# ─── MCP Tool Definitions ────────────────────────────────────────────────────
# These are the tools exposed to the Devin agent via MCP

MCP_TOOLS = {
    "query_logs": {
        "name": "query_logs",
        "description": "Execute a KQL query against Azure Log Analytics. Use this to investigate application logs, exceptions, and traces from the EventFlow services.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "KQL (Kusto Query Language) query to execute",
                },
                "timespan": {
                    "type": "string",
                    "description": "ISO 8601 duration for the query window (default: PT1H = last 1 hour)",
                    "default": "PT1H",
                },
            },
            "required": ["query"],
        },
    },
    "get_exceptions": {
        "name": "get_exceptions",
        "description": "Get recent exceptions from a specific service. Returns exception type, message, and stack trace.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Cloud role name (e.g., 'eventflow-payment-service')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of exceptions to return (default: 20)",
                    "default": 20,
                },
            },
            "required": ["service_name"],
        },
    },
    "get_traces": {
        "name": "get_traces",
        "description": "Get recent log traces from a specific service, filtered by severity.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Cloud role name (e.g., 'eventflow-payment-service')",
                },
                "min_severity": {
                    "type": "integer",
                    "description": "Minimum severity level: 0=Verbose, 1=Info, 2=Warning, 3=Error, 4=Critical",
                    "default": 2,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of traces to return (default: 50)",
                    "default": 50,
                },
            },
            "required": ["service_name"],
        },
    },
    "get_metrics": {
        "name": "get_metrics",
        "description": "Get error rate and request metrics for a specific service over the last hour.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Cloud role name (e.g., 'eventflow-payment-service')",
                },
            },
            "required": ["service_name"],
        },
    },
}


def handle_tool_call(tool_name: str, arguments: dict) -> list[dict]:
    """Route an MCP tool call to the appropriate handler.

    Args:
        tool_name: Name of the tool to invoke.
        arguments: Tool arguments.

    Returns:
        List of result dicts.
    """
    if tool_name == "query_logs":
        return query_logs(
            query=arguments["query"],
            timespan=arguments.get("timespan", "PT1H"),
        )

    elif tool_name == "get_exceptions":
        service = arguments["service_name"]
        limit = arguments.get("limit", 20)
        query = f"""
            exceptions
            | where cloud_RoleName == "{service}"
            | order by timestamp desc
            | take {limit}
            | project timestamp, type, outerMessage, innermostMessage, details
        """
        return query_logs(query)

    elif tool_name == "get_traces":
        service = arguments["service_name"]
        severity = arguments.get("min_severity", 2)
        limit = arguments.get("limit", 50)
        query = f"""
            traces
            | where cloud_RoleName == "{service}"
            | where severityLevel >= {severity}
            | order by timestamp desc
            | take {limit}
            | project timestamp, severityLevel, message
        """
        return query_logs(query)

    elif tool_name == "get_metrics":
        service = arguments["service_name"]
        query = f"""
            requests
            | where cloud_RoleName == "{service}"
            | summarize
                total_requests = count(),
                failed_requests = countif(success == false),
                avg_duration_ms = avg(duration),
                p95_duration_ms = percentile(duration, 95)
              by bin(timestamp, 5m)
            | order by timestamp desc
            | take 12
        """
        return query_logs(query)

    else:
        return [{"error": f"Unknown tool: {tool_name}"}]


# ─── MCP Server Protocol ─────────────────────────────────────────────────────

def handle_mcp_request(request: dict) -> dict:
    """Handle an incoming MCP JSON-RPC request.

    Args:
        request: The MCP JSON-RPC request.

    Returns:
        The MCP JSON-RPC response.
    """
    method = request.get("method", "")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "eventflow-log-analytics",
                    "version": "1.0.0",
                },
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": tool["parameters"],
                    }
                    for tool in MCP_TOOLS.values()
                ]
            },
        }

    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        results = handle_tool_call(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(results, indent=2, default=str),
                    }
                ]
            },
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def main() -> None:
    """Run the MCP server over stdio."""
    import sys

    logger.info("EventFlow Log Analytics MCP Server starting (stdio mode)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_mcp_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            logger.error("Invalid JSON received: %s", line)
        except Exception:
            logger.exception("Error handling MCP request")


if __name__ == "__main__":
    main()
