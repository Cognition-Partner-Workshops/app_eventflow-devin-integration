# Azure DevOps Service Hook → Devin API Relay

Automatically trigger [Devin AI](https://devin.ai) sessions when Azure DevOps work items are tagged with `Devin:Discovery`.

## Architecture

```
Azure DevOps Board          Azure Function (Webhook Relay)       Devin API
┌──────────────────┐        ┌──────────────────────────┐        ┌──────────────────┐
│  Work Item tagged │──────▶│  1. Parse payload         │──────▶│  POST /v3/orgs/  │
│  "Devin:Discovery"│ HTTP  │  2. Check for tag         │ HTTP  │  {id}/sessions   │
│                   │ POST  │  3. Extract title + desc   │ POST  │                  │
│  Service Hook     │       │  4. Build prompt           │       │  Session created │
│  fires webhook    │       │  5. Call Devin API         │       │                  │
└──────────────────┘        └──────────────────────────┘        └──────────────────┘
```

## How It Works

1. A user adds the `Devin:Discovery` tag to any work item in Azure DevOps
2. An Azure DevOps **service hook** fires a webhook (HTTP POST) to an Azure Function
3. The function parses the payload and checks for the `Devin:Discovery` tag (case-insensitive)
4. If present, it extracts the work item title, description, and URL
5. It calls the Devin API to create a new session with those details as the prompt

## Prerequisites

- Azure subscription with permissions to create resources
- Azure DevOps organization with a project
- [Devin API key](https://docs.devin.ai/api-reference/getting-started/teams-quickstart) (`ManageOrgSessions` permission)
- Azure CLI (`az`) installed

## Quick Start

### 1. Deploy the Azure Function

```bash
export DEVIN_API_KEY="cog_your_api_key_here"
export DEVIN_ORG_ID="org-your-org-id-here"

chmod +x scripts/deploy-function.sh
./scripts/deploy-function.sh rg-devin-integration devin-webhook-relay eastus
```

### 2. Get the Webhook URL

The function uses anonymous auth, so the URL is simply:

```
https://<func-app-name>.azurewebsites.net/api/devops-webhook
```

### 3. Set Up Azure DevOps Service Hook

```bash
export AZURE_DEVOPS_PAT="your-pat-here"

chmod +x scripts/setup-devops.sh
./scripts/setup-devops.sh \
  "https://dev.azure.com/YourOrg" \
  "YourProject" \
  "https://<func-app-name>.azurewebsites.net/api/devops-webhook"
```

### 4. Test the Integration

```bash
chmod +x scripts/test-webhook.sh
./scripts/test-webhook.sh "https://<func-app-name>.azurewebsites.net/api/devops-webhook"
```

### 5. Trigger a Real Session

Add the `Devin:Discovery` tag to any work item:

```bash
az boards work-item update \
  --id <work-item-id> \
  --fields "System.Tags=Devin:Discovery" \
  --org "https://dev.azure.com/YourOrg" \
  --project "YourProject"
```

## File Structure

```
devops-webhook/
├── README.md               # This file
├── function_app.py         # Webhook relay logic (Azure Function)
├── host.json               # Azure Functions host configuration
├── requirements.txt        # Python dependencies
└── scripts/
    ├── deploy-function.sh  # Deploy Azure Function to Azure
    ├── setup-devops.sh     # Create Azure DevOps project and service hook
    └── test-webhook.sh     # Test with simulated payloads
```

## Configuration

### Azure Function App Settings

| Setting | Description |
|---------|-------------|
| `DEVIN_API_KEY` | Devin API key (starts with `cog_`) |
| `DEVIN_ORG_ID` | Devin organization ID (starts with `org-`) |

### Tag Customization

To change the trigger tag, edit the `DEVIN_TAG` constant in `function_app.py`.

## Devin API Reference

- [Create Session](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions) -- `POST /v3/organizations/{org_id}/sessions`
- [Authentication](https://docs.devin.ai/api-reference/authentication)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Service hook shows failures | Check function is running: `az functionapp show --name <app> --resource-group <rg> --query state` |
| Devin session not created | Verify `DEVIN_API_KEY` and `DEVIN_ORG_ID` in app settings |
| Tag not detected | Ensure exact tag `Devin:Discovery` (case-insensitive match) |
| Cold start timeouts | Warm the function first or switch to Premium plan |
