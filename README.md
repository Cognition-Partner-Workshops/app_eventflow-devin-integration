# EventFlow Devin Integration

The AI-powered incident response layer for the EventFlow demo. Connects Azure Monitor alerts to the Devin API for automated root cause analysis and fix generation.

## Architecture Role

```
Azure Monitor Alert
        ↓
┌───────────────────┐
│  Azure Function   │  ← alert-function/
│ (webhook handler) │
└────────┬──────────┘
         ↓
┌───────────────────┐
│    Devin API      │  Creates a session with context about all EventFlow repos
│   /v1/sessions    │
└────────┬──────────┘
         ↓
┌───────────────────┐
│   Devin Agent     │  Uses MCP to query Azure Log Analytics
│ (investigation)   │
└────────┬──────────┘
         ↓
┌───────────────────┐
│   Pull Request    │  Fix PR on app_eventflow-payment-service
│  (auto-generated) │
└───────────────────┘
```

## Components

### 1. Alert Function (`alert-function/`)

An Azure Function (Python, Consumption plan) that:
- Receives webhook payloads from Azure Monitor alert rules
- Parses the Common Alert Schema to extract error details
- Calls the Devin API to create a new investigation session
- Passes structured context: affected service, error logs, repo URLs

### 2. MCP Server (`mcp-server/`)

A Model Context Protocol server that gives Devin access to:
- **Azure Log Analytics** — query application logs, exceptions, traces
- **Azure Monitor Metrics** — query error rates, response times, availability
- Provides tools: `query_logs`, `get_exceptions`, `get_metrics`, `get_traces`

### 3. Shared Schemas (`schemas/`)

JSON schemas for the events flowing through the system:
- `order_created.json` — Event published by Order Service
- `payment_processed.json` — Event published by Payment Service
- `alert_payload.json` — Common Alert Schema from Azure Monitor

### 4. Demo Runbook (`docs/`)

Step-by-step instructions for running the full demo narrative.

## Setup

### Prerequisites

- Python 3.11+
- Azure Functions Core Tools v4
- A Devin API key (from https://app.devin.ai/settings)

### Alert Function

```bash
cd alert-function
pip install -r requirements.txt

# Local testing
func start

# Deploy to Azure
func azure functionapp publish <function-app-name>
```

### MCP Server

```bash
cd mcp-server
pip install -r requirements.txt

# Run locally
python server.py
```

## Environment Variables

### Alert Function

| Variable | Description |
|---|---|
| `DEVIN_API_KEY` | Devin API authentication token |
| `DEVIN_API_URL` | Devin API base URL (default: `https://api.devin.ai/v1`) |
| `GITHUB_ORG` | GitHub org name (default: `Cognition-Partner-Workshops`) |
| `REPOS` | Comma-separated repo names for Devin context |

### MCP Server

| Variable | Description |
|---|---|
| `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics workspace customer ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | Service principal client ID |
| `AZURE_CLIENT_SECRET` | Service principal secret |

## Demo Flow

1. **Trigger**: JPY order submitted to Order Service
2. **Crash**: Payment Service throws ValueError (zero-decimal currency bug)
3. **Detect**: Application Insights captures exception, alert rule fires
4. **Invoke**: Azure Function receives alert webhook, calls Devin API
5. **Investigate**: Devin connects to Log Analytics via MCP, reads exception details
6. **Fix**: Devin opens PR on `app_eventflow-payment-service` with currency fix + test
7. **Deploy**: CI passes, CD deploys fixed Payment Service
8. **Verify**: Same JPY order now succeeds
