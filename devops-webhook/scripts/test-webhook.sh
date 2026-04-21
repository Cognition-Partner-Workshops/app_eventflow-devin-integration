#!/usr/bin/env bash
set -euo pipefail

# Test the webhook relay locally or against deployed function
# Usage: ./scripts/test-webhook.sh <webhook-url>

WEBHOOK_URL="${1:?Usage: $0 <webhook-url>}"

echo "=== Testing Webhook Relay ==="
echo "URL: $WEBHOOK_URL"
echo ""

# Simulate an Azure DevOps workitem.updated event with Devin:Discovery tag
PAYLOAD=$(cat <<'EOF'
{
  "subscriptionId": "test-subscription-id",
  "notificationId": 1,
  "id": "test-event-id",
  "eventType": "workitem.updated",
  "publisherId": "tfs",
  "message": {
    "text": "Work item updated"
  },
  "resource": {
    "id": 42,
    "rev": 3,
    "revision": {
      "id": 42,
      "rev": 3,
      "fields": {
        "System.WorkItemType": "User Story",
        "System.Title": "Update readme on the OtterWorks app",
        "System.Description": "Review and update the README.md file in the OtterWorks repository. Ensure setup instructions, architecture overview, and contribution guidelines are current and accurate.",
        "System.Tags": "Devin:Discovery",
        "System.State": "New"
      }
    },
    "_links": {
      "html": {
        "href": "https://dev.azure.com/example/DevinIntegration/_workitems/edit/42"
      }
    }
  },
  "resourceVersion": "1.0",
  "resourceContainers": {
    "project": {
      "id": "test-project-id"
    }
  }
}
EOF
)

echo "Sending test payload (workitem.updated with Devin:Discovery tag)..."
echo ""

RESPONSE=$(curl -s -w "\n\nHTTP Status: %{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$WEBHOOK_URL")

echo "Response:"
echo "$RESPONSE"
echo ""

# Test without the tag (should be skipped)
echo "---"
echo "Sending test payload (workitem.updated WITHOUT Devin:Discovery tag)..."

PAYLOAD_NO_TAG=$(echo "$PAYLOAD" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['resource']['revision']['fields']['System.Tags'] = 'SomeOtherTag'
print(json.dumps(d))
")

RESPONSE2=$(curl -s -w "\n\nHTTP Status: %{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD_NO_TAG" \
  "$WEBHOOK_URL")

echo "Response:"
echo "$RESPONSE2"
