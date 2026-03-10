# EventFlow Workshop — Participant Guide

## Your Team Environment

You have a dedicated set of services running on Azure:

| Service | URL |
|---------|-----|
| **Storefront** | `https://ef-store-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io` |
| **Order Service** | `https://ef-order-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io` |
| **Payment Service** | `https://ef-payment-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io` |
| **Operations Dashboard** | `https://ef-store-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io/ops.html` |

Replace `{N}` with your team number (1-10).

---

## Three Ways to Investigate with Devin

### Flow 1: Manual Investigation (Copy & Paste)

1. Go to the **Storefront** and place a JPY order to trigger the bug
2. Open the **Operations Dashboard** (`/ops.html`) to see the incident
3. Click **"Copy Prompt for Manual Use"** on the ops dashboard
4. Go to [app.devin.ai](https://app.devin.ai) and start a new session
5. Paste the investigation prompt
6. Watch Devin investigate, identify the root cause, and open a PR

### Flow 2: One-Click from Ops Dashboard

1. Trigger the bug (JPY order from storefront)
2. Open the **Operations Dashboard**
3. Click **"Investigate with Devin"**
4. A Devin session is created automatically via the API
5. Follow the session link to watch Devin work

### Flow 3: Fully Automatic (No Human Needed)

When the bug is triggered, Azure Monitor detects the error spike and automatically:
1. Alert rule fires on payment service exceptions
2. Webhook calls the alert-webhook Container App
3. Webhook creates a Devin API session with full team context
4. Devin investigates and opens a fix PR — zero human intervention

---

## What Devin Needs to Investigate

### Repositories (Devin should have access to all of these)

| Repo | Purpose |
|------|---------|
| `app_eventflow-order-service` | System 1: Order API + event publisher |
| `app_eventflow-payment-service` | System 2: Payment processor (HAS THE BUG) |
| `app_eventflow-infra` | Azure infrastructure (Bicep IaC) |
| `app_eventflow-storefront` | Customer-facing UI + ops dashboard |

All repos are in the `Cognition-Partner-Workshops` GitHub org.

### Programmatic Access Devin Needs

| Access Type | What | Why |
|-------------|------|-----|
| **GitHub** | Read/write to all 4 repos | Read code, open PRs with fixes |
| **MCP: Azure Log Analytics** | Query KQL against the workspace | Read exception stack traces and error logs |
| **Azure CLI (optional)** | `az monitor log-analytics query` | Alternative to MCP for log queries |

### MCP Server Configuration

Devin can connect to the Azure Log Analytics MCP server to query production logs:

```json
{
  "mcpServers": {
    "eventflow-logs": {
      "command": "python",
      "args": ["mcp-server/server.py"],
      "env": {
        "AZURE_TENANT_ID": "<tenant-id>",
        "AZURE_CLIENT_ID": "<client-id>",
        "AZURE_CLIENT_SECRET": "<client-secret>",
        "AZURE_LOG_ANALYTICS_WORKSPACE_ID": "<workspace-id>"
      }
    }
  }
}
```

### Key KQL Queries for Investigation

```kusto
-- Recent payment service exceptions
exceptions
| where cloud_RoleName == "ef-payment-team{N}"
| order by timestamp desc
| take 20

-- Error traces with context
traces
| where cloud_RoleName == "ef-payment-team{N}"
| where severityLevel >= 3
| order by timestamp desc
| take 50

-- Error rate over time
requests
| where cloud_RoleName == "ef-payment-team{N}"
| summarize total=count(), failed=countif(success == false)
  by bin(timestamp, 5m)
| order by timestamp desc
```

---

## Investigation Prompt Template

Copy this into a new Devin session (replace `{N}` with your team number):

```
## Production Incident — Service Outage

**Team**: team{N}
**Severity**: Critical — customer-facing failure

### What We Know

Our e-commerce platform has two backend services: an Order Service that accepts
customer orders and publishes events, and a Payment Service that consumes those
events and processes payments.

Operational symptoms:
- Customers placing orders in certain currencies see a long delay followed by a generic "Unable to Process Order" error
- Orders in USD complete successfully with no issues
- The Payment Service appears to be crashing or failing intermittently — health checks are failing
- Affected orders remain stuck in "pending" status and never complete
- The Order Service is healthy and accepting orders normally — the problem is downstream

### Live Environment

- Order Service: https://ef-order-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io
- Payment Service: https://ef-payment-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io
- Both services have Swagger docs at /docs and health endpoints at /health
- Orders can be viewed at GET /api/orders on the Order Service

### Repositories

- https://github.com/Cognition-Partner-Workshops/app_eventflow-order-service (branch: team{N})
- https://github.com/Cognition-Partner-Workshops/app_eventflow-payment-service (branch: team{N})
- https://github.com/Cognition-Partner-Workshops/app_eventflow-infra
- https://github.com/Cognition-Partner-Workshops/app_eventflow-storefront (branch: team{N})

### Your Task

1. Investigate — Figure out why certain orders are failing. Look at the code, check the service endpoints, and identify the root cause.
2. Fix — Open a Pull Request on the appropriate repository against the team{N} branch with the bug fix and a new test case that covers the failure scenario.
3. Verify — Make sure the fix passes CI before marking the investigation complete.

IMPORTANT: Open your fix PR against the team{N} branch, not main. This team has its own isolated deployment.
```

---

## For Workshop Facilitators — The Bug Explained

> **Note:** This section is for facilitators only. Do NOT share this with participants —
> the goal is for Devin to discover the root cause on its own from the symptoms above.

**What happens:**
1. Customer places a JPY order for ¥12,800 (Mechanical Keyboard)
2. Order Service accepts it and publishes event to Service Bus
3. Payment Service receives the event and calls `convert_to_display_amount(12800, "JPY")`
4. The function divides by 100: `12800 / 100 = 128.0`
5. But JPY has a minimum threshold of 500 — so `128.0 < 500.0` fails validation
6. **`ValueError: Amount 128.0 JPY is below minimum threshold 500.0 JPY`**

**The root cause:** JPY is a zero-decimal currency (no cents). ¥12,800 means 12,800 yen, not 128.00 yen. The payment service assumes all currencies use cents and blindly divides by 100.

**The fix:** Check if the currency is zero-decimal before dividing. Zero-decimal currencies (JPY, KRW, VND, CLP, etc.) should skip the division.
