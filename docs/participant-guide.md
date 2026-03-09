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
## Production Incident Investigation

**Team**: team{N}
**Alert**: Payment Processing Failure on JPY orders
**Severity**: Critical
**Order Service**: https://ef-order-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io
**Payment Service**: https://ef-payment-team{N}.salmonbush-13ada168.eastus.azurecontainerapps.io

### Context

The EventFlow payment processing stack is experiencing errors. JPY (Japanese Yen)
orders are accepted by the Order Service but the Payment Service crashes during
processing. USD orders work correctly.

The error is: `ValueError: Amount X.X JPY is below minimum threshold` — the payment
service incorrectly divides all currency amounts by 100 (converting cents to dollars),
but JPY is a zero-decimal currency that should not be divided.

### Repositories

- https://github.com/Cognition-Partner-Workshops/app_eventflow-order-service (branch: team{N})
- https://github.com/Cognition-Partner-Workshops/app_eventflow-payment-service (branch: team{N})
- https://github.com/Cognition-Partner-Workshops/app_eventflow-infra
- https://github.com/Cognition-Partner-Workshops/app_eventflow-storefront

### Investigation Steps

1. Look at the payment service code in `app_eventflow-payment-service`, specifically
   the payment processor in `app/services/processor.py`.
2. Identify the zero-decimal currency bug in the `convert_to_display_amount()` function.
3. Open a Pull Request on `app_eventflow-payment-service` against the `team{N}` branch with:
   - The bug fix: skip division by 100 for zero-decimal currencies (JPY, KRW, VND, etc.)
   - A new test case covering JPY order processing
   - Clear PR description explaining the root cause and fix
4. Verify the fix passes CI.
```

---

## The Bug Explained

**What happens:**
1. Customer places a JPY order for ¥12,800 (Mechanical Keyboard)
2. Order Service accepts it and publishes event to Service Bus
3. Payment Service receives the event and calls `convert_to_display_amount(12800, "JPY")`
4. The function divides by 100: `12800 / 100 = 128.0`
5. But JPY has a minimum threshold of 500 — so `128.0 < 500.0` fails validation
6. **`ValueError: Amount 128.0 JPY is below minimum threshold 500.0 JPY`**

**The root cause:** JPY is a zero-decimal currency (no cents). ¥12,800 means 12,800 yen, not 128.00 yen. The payment service assumes all currencies use cents and blindly divides by 100.

**The fix:** Check if the currency is zero-decimal before dividing. Zero-decimal currencies (JPY, KRW, VND, CLP, etc.) should skip the division.
