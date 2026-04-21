#!/usr/bin/env bash
set -euo pipefail

# Set up Azure DevOps project, work item, and service hook
# Usage: ./scripts/setup-devops.sh <org-url> <project-name> <webhook-url>
#
# Prerequisites:
#   - Azure DevOps PAT set as AZURE_DEVOPS_PAT environment variable
#   - az devops extension installed: az extension add --name azure-devops

DEVOPS_ORG="${1:?Usage: $0 <org-url> <project-name> <webhook-url>}"
PROJECT_NAME="${2:-DevinIntegration}"
WEBHOOK_URL="${3:-}"

if [ -z "${AZURE_DEVOPS_PAT:-}" ]; then
  echo "ERROR: AZURE_DEVOPS_PAT environment variable must be set"
  exit 1
fi

# Configure Azure DevOps CLI defaults
export AZURE_DEVOPS_EXT_PAT="$AZURE_DEVOPS_PAT"
az devops configure --defaults organization="$DEVOPS_ORG"

echo "=== Setting up Azure DevOps Project ==="
echo "Organization: $DEVOPS_ORG"
echo "Project:      $PROJECT_NAME"
echo ""

# Create project
echo "Creating project '$PROJECT_NAME'..."
az devops project create \
  --name "$PROJECT_NAME" \
  --description "Devin AI integration demo - triggers Devin sessions from tagged work items" \
  --process Agile \
  --source-control git \
  --visibility private \
  --output none 2>/dev/null || echo "Project may already exist, continuing..."

az devops configure --defaults project="$PROJECT_NAME"

# Create a sample work item (User Story)
echo "Creating sample work item..."
WORK_ITEM_ID=$(az boards work-item create \
  --type "User Story" \
  --title "Update readme on the OtterWorks app" \
  --description "Review and update the README.md file in the OtterWorks repository. Ensure setup instructions, architecture overview, and contribution guidelines are current and accurate." \
  --query "id" \
  --output tsv)

echo "Created work item #$WORK_ITEM_ID"

# Create the service hook if webhook URL is provided
if [ -n "$WEBHOOK_URL" ]; then
  echo ""
  echo "Creating service hook for work item updates..."
  
  # Get project ID
  PROJECT_ID=$(az devops project show --project "$PROJECT_NAME" --query "id" --output tsv)
  
  # Create service hook via REST API (the CLI doesn't support service hooks directly)
  HOOK_PAYLOAD=$(cat <<EOF
{
  "publisherId": "tfs",
  "eventType": "workitem.updated",
  "resourceVersion": "1.0",
  "consumerId": "webHooks",
  "consumerActionId": "httpRequest",
  "publisherInputs": {
    "projectId": "$PROJECT_ID"
  },
  "consumerInputs": {
    "url": "$WEBHOOK_URL",
    "httpHeaders": "Content-Type: application/json",
    "resourceDetailsToSend": "All",
    "messagesToSend": "All",
    "detailedMessagesToSend": "All"
  }
}
EOF
)

  # Use the Azure DevOps REST API to create the service hook
  RESPONSE=$(curl -s -X POST \
    -u ":$AZURE_DEVOPS_PAT" \
    -H "Content-Type: application/json" \
    -d "$HOOK_PAYLOAD" \
    "${DEVOPS_ORG}/_apis/hooks/subscriptions?api-version=7.1")
  
  HOOK_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id','ERROR'))" 2>/dev/null || echo "ERROR")
  
  if [ "$HOOK_ID" != "ERROR" ] && [ -n "$HOOK_ID" ]; then
    echo "Service hook created: $HOOK_ID"
  else
    echo "WARNING: Service hook creation may have failed. Response:"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
  fi
else
  echo ""
  echo "NOTE: No webhook URL provided. Skipping service hook creation."
  echo "You can create it manually in Azure DevOps:"
  echo "  1. Go to Project Settings > Service hooks"
  echo "  2. Click '+ Create subscription'"
  echo "  3. Select 'Web Hooks' as the service"
  echo "  4. Event: 'Work item updated'"
  echo "  5. URL: <your-function-url>?code=<function-key>"
fi

echo ""
echo "=== Setup Complete ==="
echo "Project: $DEVOPS_ORG/$PROJECT_NAME"
echo "Work Item: #$WORK_ITEM_ID - 'Update readme on the OtterWorks app'"
echo ""
echo "To trigger a Devin session, add the tag 'Devin:Discovery' to work item #$WORK_ITEM_ID"
echo "You can do this via the UI or CLI:"
echo "  az boards work-item update --id $WORK_ITEM_ID --fields 'System.Tags=Devin:Discovery'"
