# Phase 3 — Admin Pricing Dashboard (build notes)

A control panel at **`/admin/pricing`** for NSR to manage pricing over time. Not
a CRM — pricing only. Pricing values are entered here by NSR; the code seeds only
placeholder defaults.

## How it works
```
/admin/pricing (admin/pricing.html)
   │  password -> POST /api/admin/login -> short-lived HMAC token
   ▼
GET  /api/admin/pricing   -> active config (form) + live sample quote
POST /api/admin/pricing   -> validate -> save new active version to Supabase
                             (preview=true validates + samples without saving)
   │
   ▼  Supabase table pricing_config (append-only, is_active flag, RLS on)
   ▼
load_pricing()  reads the active row (cached) -> every quote uses it
```

`load_pricing()` precedence: **Supabase active row → `ROOFNOW_PRICING_JSON` →
`ROOFNOW_PRICING_FILE` → `pricing.config.json` → built-in defaults.** If Supabase
isn't configured, quotes safely use the defaults.

## Editable settings
Tiers (Good/Better/Best $/sq, name, blurb, features), pitch multipliers,
complexity multipliers, waste defaults, base spread, minimum job, accessory
allowances (flat or per-square, per-tier), financing teaser (APR + term →
"as low as $X/mo" on the report), and service-area gating (states / ZIP
prefixes / out-of-area message).

## Required env (Vercel)
- `ADMIN_PASSWORD` — gate for the dashboard (unset = admin disabled)
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — config storage (service-role key
  is server-side only; bypasses RLS; never exposed to the browser)
- `ADMIN_TOKEN_SECRET` — optional; defaults to `ADMIN_PASSWORD`

## Supabase
Table `public.pricing_config` (migration `create_pricing_config`), RLS enabled
with **no policies** so only the service role (server) can read/write. Seeded
with one active `seed-default` row (placeholder defaults).

## Future (Phase 3.1+)
The append-only history + Estimate Confidence "pricing freshness" hook lay the
groundwork to train estimate confidence on real estimate-vs-contract outcomes.
