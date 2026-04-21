#!/usr/bin/env bash
set -euo pipefail

# Deploy the Azure Function webhook relay
# Usage: ./scripts/deploy-function.sh <resource-group> <function-app-name> <location>

RESOURCE_GROUP="${1:-rg-devin-integration}"
FUNC_APP_NAME="${2:-devin-webhook-relay}"
LOCATION="${3:-eastus}"
STORAGE_ACCOUNT="${FUNC_APP_NAME//-/}sa"
# Truncate storage account name to 24 chars (Azure limit)
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:0:24}"

echo "=== Deploying Azure Function Webhook Relay ==="
echo "Resource Group:  $RESOURCE_GROUP"
echo "Function App:    $FUNC_APP_NAME"
echo "Location:        $LOCATION"
echo "Storage Account: $STORAGE_ACCOUNT"
echo ""

# Create resource group
echo "Creating resource group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# Create storage account
echo "Creating storage account..."
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --output none

# Create function app
echo "Creating function app..."
az functionapp create \
  --name "$FUNC_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --storage-account "$STORAGE_ACCOUNT" \
  --consumption-plan-location "$LOCATION" \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux \
  --output none

# Configure app settings
echo "Configuring Devin API settings..."
if [ -z "${DEVIN_API_KEY:-}" ] || [ -z "${DEVIN_ORG_ID:-}" ]; then
  echo "WARNING: DEVIN_API_KEY and DEVIN_ORG_ID environment variables not set."
  echo "You will need to set them manually:"
  echo "  az functionapp config appsettings set \\"
  echo "    --name $FUNC_APP_NAME \\"
  echo "    --resource-group $RESOURCE_GROUP \\"
  echo "    --settings DEVIN_API_KEY=<your-key> DEVIN_ORG_ID=<your-org-id>"
else
  az functionapp config appsettings set \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --settings \
      "DEVIN_API_KEY=$DEVIN_API_KEY" \
      "DEVIN_ORG_ID=$DEVIN_ORG_ID" \
    --output none
  echo "Devin API settings configured."
fi

# Deploy the function code
echo "Deploying function code..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNC_DIR="$SCRIPT_DIR/.."

cd "$FUNC_DIR"
func azure functionapp publish "$FUNC_APP_NAME" --python 2>/dev/null || {
  echo ""
  echo "NOTE: Azure Functions Core Tools (func) not installed."
  echo "Falling back to zip deployment..."
  
  DEPLOY_ZIP="/tmp/function-deploy.zip"
  rm -f "$DEPLOY_ZIP"
  zip -r "$DEPLOY_ZIP" . -x "local.settings.json" -x ".venv/*" -x "__pycache__/*"
  
  az functionapp deployment source config-zip \
    --name "$FUNC_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --src "$DEPLOY_ZIP" \
    --output none
  
  rm -f "$DEPLOY_ZIP"
}

# Get the function URL
echo ""
echo "=== Deployment Complete ==="
FUNC_URL="https://${FUNC_APP_NAME}.azurewebsites.net/api/devops-webhook"
echo "Webhook URL: $FUNC_URL"
echo ""
echo "Use this URL when configuring the Azure DevOps service hook."
echo "The endpoint uses anonymous auth — no function key required."
