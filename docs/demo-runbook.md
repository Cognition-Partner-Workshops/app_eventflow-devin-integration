# EventFlow Demo Runbook

Step-by-step guide for running the full EventFlow incident response demo.

## Prerequisites

Before running the demo, ensure:

- [ ] All 4 repos are pushed to `Cognition-Partner-Workshops`
- [ ] Azure infrastructure is deployed via `app_eventflow-infra`
- [ ] Container images are built and pushed to ACR
- [ ] Container Apps are running and healthy
- [ ] Devin API key is configured in the Azure Function
- [ ] MCP server is configured with Log Analytics credentials

## Demo Script

### Act 1: Show the Working Stack (2 minutes)

1. **Open the Order Service Swagger UI**
   ```
   https://<order-service-fqdn>/docs
   ```

2. **Create a USD order** (this works perfectly):
   ```bash
   curl -X POST https://<order-service-fqdn>/api/orders \
     -H "Content-Type: application/json" \
     -d '{
       "customer_id": "cust-demo-001",
       "currency": "USD",
       "items": [
         {"product_id": "prod-101", "name": "Wireless Mouse", "quantity": 2, "unit_price": 2999}
       ]
     }'
   ```

3. **Show the payment was processed** — check Payment Service:
   ```bash
   curl https://<payment-service-fqdn>/api/payments
   ```

4. **Narrate**: "Our e-commerce order flow works end-to-end. Orders come in, events flow through Azure Service Bus, payments are processed. CI is green, CD deployed this automatically."

### Act 2: The Silent Bug Ships (2 minutes)

5. **Show the Order Service CI** — open GitHub Actions for `app_eventflow-order-service`:
   - Point out: all tests pass, including the new international currency support
   - "A developer added multi-currency support. Tests pass. CD deploys."

6. **Show the Payment Service CI** — open GitHub Actions for `app_eventflow-payment-service`:
   - "Payment Service tests also pass — but notice they only test USD and EUR."

7. **Narrate**: "Both services pass CI independently. The bug is a cross-service integration issue that unit tests don't catch."

### Act 3: The Crash (2 minutes)

8. **Submit a JPY order** (this will crash the Payment Service):
   ```bash
   curl -X POST https://<order-service-fqdn>/api/orders \
     -H "Content-Type: application/json" \
     -d '{
       "customer_id": "cust-demo-002",
       "currency": "JPY",
       "items": [
         {"product_id": "prod-201", "name": "Mechanical Keyboard", "quantity": 1, "unit_price": 15800}
       ]
     }'
   ```

9. **Show the Order Service accepted it** — the order was created successfully.

10. **Show the Payment Service crashed** — check payments endpoint:
    ```bash
    curl https://<payment-service-fqdn>/api/payments
    ```
    The JPY payment is not in the list (it crashed before being recorded).

11. **Open Azure Monitor / Application Insights**:
    - Show the exception in the Live Metrics view
    - Show the error spike in the Failures blade
    - "The observability stack caught it immediately."

### Act 4: Devin Investigates (3-5 minutes)

12. **Show the alert firing** — open Azure Monitor Alerts:
    - The alert rule detected the error spike
    - The action group triggered the webhook

13. **Show the Devin session being created** — open the Devin dashboard:
    - Devin received the alert context automatically
    - Devin is connecting to Azure Log Analytics via MCP

14. **Watch Devin work** (this is the main demo moment):
    - Devin queries the exception logs
    - Devin reads the stack trace: `ValueError: Amount 158.0 JPY is below minimum threshold 500.0 JPY`
    - Devin traces the bug to `processor.py:convert_to_display_amount()`
    - Devin identifies: "All currencies divided by 100, but JPY has zero decimal places"
    - Devin opens a PR on `app_eventflow-payment-service`

15. **Narrate**: "Devin used MCP to connect to our production logs, identified the root cause across two services, and opened a fix PR — all automatically triggered by the alert."

### Act 5: The Fix Ships (2 minutes)

16. **Show the PR** — open the PR on GitHub:
    - The fix: currency-aware conversion using a decimal places lookup
    - New test case: JPY order processing
    - Clear PR description explaining the root cause

17. **Show CI passing** on the PR — all tests pass including the new JPY test.

18. **Merge the PR** — CD automatically deploys the fix.

19. **Retry the JPY order**:
    ```bash
    curl -X POST https://<order-service-fqdn>/api/orders \
      -H "Content-Type: application/json" \
      -d '{
        "customer_id": "cust-demo-003",
        "currency": "JPY",
        "items": [
          {"product_id": "prod-201", "name": "Mechanical Keyboard", "quantity": 1, "unit_price": 15800}
        ]
      }'
    ```

20. **Show it works** — check payments:
    ```bash
    curl https://<payment-service-fqdn>/api/payments
    ```
    The JPY payment is now processed successfully.

21. **Show observability** — error rate drops to zero in Azure Monitor.

## Talking Points for Executives

- **Speed**: Traditional incident response takes hours (paging, war rooms, manual investigation). Devin did it in minutes.
- **Context**: Devin had access to all repos in the stack and production logs — it could trace the issue across service boundaries.
- **Quality**: The fix included a test case, preventing regression. It went through the same CI/CD pipeline as any human PR.
- **Cost**: The entire Azure infrastructure runs for < $10/month. The AI investigation saved hours of engineering time.
- **Integration**: This works with your existing stack — Azure Monitor, GitHub Actions, Service Bus. No new infrastructure required beyond the Devin API integration.

## Troubleshooting

| Issue | Resolution |
|---|---|
| Order Service returns 500 | Check Service Bus connection string in Container App env vars |
| Payment Service not consuming events | Verify Service Bus queue name matches between services |
| Alert not firing | Check Application Insights is receiving telemetry; verify alert rule is enabled |
| Devin session not created | Verify DEVIN_API_KEY in Azure Function app settings |
| MCP server can't query logs | Check AZURE_LOG_ANALYTICS_WORKSPACE_ID and service principal credentials |

## Cleanup

After the demo:
```bash
cd app_eventflow-infra
./scripts/teardown.sh
```

This deletes all Azure resources. The GitHub repos remain for future demos.
