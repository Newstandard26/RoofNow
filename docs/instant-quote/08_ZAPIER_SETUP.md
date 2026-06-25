# Zapier Lead Funnel — Setup

How a RoofNow website lead reaches your CRMs.

```
quote.html intake form
        │  POST /api/lead   (validates first/last name, address, phone, email)
        ▼
api/lead.py  ──►  measure + build instant quote
        │
        ▼  funnel_lead()  (best-effort; never blocks the homeowner)
        ├─ POST LEAD_WEBHOOK_URL  ──►  Zapier Catch Hook  ──►  AccuLynx + LeadConnector
        ├─ POST SLACK_WEBHOOK_URL ──►  Slack channel        (optional)
        └─ SMTP                    ──►  team email           (optional)
```

The serverless function can't use interactive integrations, so it POSTs a flat,
CRM-ready JSON payload to a **Zapier Catch Hook**. Zapier holds the AccuLynx and
LeadConnector auth and fans the lead out.

Validated live (2026-06-25): **AccuLynx Create Lead** ✅ and **LeadConnector
Add/Update Contact** ✅ both accept the mapping below. **Gmail Send Email** is
**restricted by your Zapier account admin** (`halted`) — use the built-in SMTP
email sink, or have an admin unrestrict the Gmail action in Zapier.

## One-time setup (~3 minutes)

1. In Zapier, **Create Zap**.
2. Trigger: **Webhooks by Zapier → Catch Hook**. Copy the custom webhook URL.
3. In Vercel (Project → Settings → Environment Variables) set
   **`LEAD_WEBHOOK_URL`** to that URL. Redeploy.
4. Add the action steps below. Map the incoming fields (left) to each app's
   fields (right). Because the payload keys already match, most rows auto-suggest.
5. Submit a real lead on the site (or use Zapier's test) and turn the Zap on.

## Webhook payload (what `/api/lead` POSTs)

`roofwall.quote.funnel.lead_to_webhook_payload` produces:

| key                  | example                          |
|----------------------|----------------------------------|
| `first_name`         | `Jane`                           |
| `last_name`          | `Roof`                           |
| `name`               | `Jane Roof`                      |
| `email`              | `jane@example.com`               |
| `phone`              | `8155550123` (digits only)       |
| `address`            | `123 Main St, Rockford, IL 61101`|
| `tier`               | `better`                         |
| `estimate_low`       | `14700`                          |
| `estimate_high`      | `25100`                          |
| `estimate_amount`    | `$14,700 – $25,100`              |
| `confidence_band`    | `high` / `medium` / `low`        |
| `confidence_pct`     | `90`                             |
| `capture_confidence` | `Complete` / `Partial` / `Needs Review` |
| `lead_priority`      | `Hot` / `Warm` / `Cold`          |
| `source`             | `RoofNow Instant Quote`          |
| `lead_source_detail` | `Website Form`                   |
| `captured_by_agent`  | `Form`                           |
| `service_needed`     | `Roof Replacement`               |
| `lead_type`          | `Residential`                    |
| `property_type`      | `Single-Family`                  |
| `pipeline_stage`     | `New Lead`                       |
| `notes`              | one-line summary (contact + estimate + confidence) |

## Action step A — AccuLynx: Create Lead

| AccuLynx field    | map from        |
|-------------------|-----------------|
| First name *(req)*| `first_name`    |
| Last name         | `last_name`     |
| Email Address     | `email`         |
| Phone Number 1    | `phone`         |
| Phone Type 1      | `mobile` (static)|
| Street            | `address`       |
| Priority          | `normal` (static)|
| Notes             | `notes`         |

(AccuLynx parses the single `address` string into city/state/zip on its side. If
you prefer split fields, add a Formatter step — not required to start.)

## Action step B — LeadConnector (GoHighLevel): Add/Update Contact

| LeadConnector field | map from              |
|---------------------|-----------------------|
| Mark as Lead *(req)*| `true` (static)       |
| First Name          | `first_name`          |
| Last Name           | `last_name`           |
| Full Name           | `name`                |
| Email               | `email`               |
| Phone Number        | `phone`               |
| Address             | `address`             |
| Source              | `source`              |
| Lead Source Detail  | `lead_source_detail`  |
| Service Needed      | `service_needed`      |
| Property Type       | `property_type`       |
| Lead Type           | `lead_type`           |
| Captured By Agent   | `captured_by_agent`   |
| Capture Confidence  | `capture_confidence`  |
| Lead Priority       | `lead_priority`       |
| Pipeline Stage      | `pipeline_stage`      |
| Estimate Amount     | `estimate_amount`     |
| Tags                | `RoofNow, Website` (static) |
| Notes               | `notes`               |

## Optional non-Zapier sinks (set in Vercel env)

- **Slack**: `SLACK_WEBHOOK_URL` (Incoming Webhook) — instant channel post.
- **Email**: `SMTP_HOST/PORT/USER/PASS`, `LEAD_NOTIFY_TO`
  (default `mattk@newstandardrestoration.com`). Use this instead of Zapier Gmail,
  which is admin-restricted on your account.

All sinks are independent and best-effort: an unconfigured or failing sink is
skipped and never blocks the homeowner's quote or the other sinks.
