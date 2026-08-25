# HostHub / Eusocial Voice Agent

HostHub is a multi-tenant Django dashboard for restaurant teams using Bland.ai voice agents. It ingests completed and live phone calls, assigns each call to the correct restaurant and location by inbound phone number, and gives hosts a focused workflow for reviewing requests, handling follow-ups, monitoring active calls, and managing location availability.

The system is built around one operational rule:

> A restaurant tenant is resolved from the Bland AI phone number associated with that restaurant location. Calls are routed from the restaurant's public phone number, which the customer dials, to the Bland AI phone number for the correct agent. This routing is currently handled by OnSip and its logic for all locations.

When Bland sends a final call payload, the app normalizes the payload's `to` number and matches it to an active `PhoneNumber`. That mapping determines the `Account`, `Location`, and dashboard visibility for the call.

## What This Project Does

- Routes final Bland calls to the correct restaurant account and location.
- Provides a two-step restaurant login flow: account credentials, then staff member plus 4-digit PIN.
- Shows only the calls a logged-in worker is authorized to see.
- Organizes calls into HostHub categories: reservations, carryout, leave-message, private events, and other.
- Displays category-specific request details from Bland pathway variables.
- Supports live calls with active-call polling, transcript history, and SSE transcript updates.
- Lets hosts resolve calls with category-specific dispositions.
- Supports reservation SMS confirmation through a GHL webhook.
- Supports carryout cart recovery SMS for abandoned carryout carts.
- Lets managers and owners manage workers, PINs, location access, date overrides, and manual open/closed status.
- Syncs location open/closed state to Bland inbound pathway configuration.
- Sends account-scoped daily call reports through Resend.

## Repository Layout

The Django project lives in `test_1/`.

```text
.
├── README.md
└── test_1/
    ├── manage.py
    ├── requirements.txt
    ├── test_1/                 # Django settings, ASGI/WSGI, root URLs
    ├── testendpoint/           # tenant models, login, webhooks, transcripts, reports
    ├── hosthub/                # main HostHub dashboard and Bland live-call actions
    └── staff/                  # manager area, workers, hours, pathway scheduling
```


## Core Concepts

### Multi-Tenant Model

The tenant hierarchy is:

```text
Account
└── Location
    └── PhoneNumber
        └── Call
```

The core models live in `testendpoint/models.py`.

- `Account`: restaurant tenant. Stores account login credentials, active status, daily report settings, and platform metadata.
- `Location`: physical restaurant location. Stores slug, logo, timezone, transfer targets, Bland pathway IDs, business-hour state, and manual override state.
- `PhoneNumber`: active inbound phone number mapped to exactly one account and one location.
- `UserAccess`: connects a Django user to one account, one or more locations, a role, and a 4-digit PIN hash.
- `Call`: final/post-call Bland record shown in HostHub.
- `CallSession` and `TranscriptTurn`: live-call session and live transcript storage.
- `BusinessHour` and `DateOverride`: regular hours and special date rules.

### Tenant Resolution

Final call ingestion happens in `testendpoint.views.upsert_call_from_bland_json`.

The flow is:

1. Read Bland `call_id` or `c_id`.
2. Ignore calls shorter than 16 seconds.
3. Compute `display_category` from Bland `pathway_tags`.
4. Normalize Bland `to` with `_normalize_phone_number`.
5. Find an active `PhoneNumber` with that normalized number.
6. Copy the matched phone number's `account` and `location` onto the `Call`.
7. Upsert the `Call` by `bland_call_id`.

If the inbound number cannot be matched, ingestion fails. That is intentional: a call without a known active restaurant number should not appear in any tenant dashboard.

## Login And Access

HostHub login has two layers.

### 1. Account Login

Route:

```text
/test/login/
```

The account login uses `Account.login_username` and `Account.login_password_hash`. This step does not log in a Django user. It creates a preauthenticated account session with:

- `preauth_account_id`
- `preauth_location_ids`
- `preauth_started_at`

If the account has one active location, the app goes straight to that location's worker login. If it has multiple active locations, the app shows the location picker.

### 2. Worker PIN Login

Routes:

```text
/test/login/<account_slug>/locations
/test/login/<account_slug>/<location_slug>
```

After the account/location is selected, staff choose their name and enter a 4-digit PIN. This checks `UserAccess.pin_hash`. On success, Django logs in the selected user and restores the account/location session context.

### Dashboard Authorization

All HostHub call querysets are scoped to the logged-in user's `UserAccess`:

```python
Call.objects.filter(
    account=access.account,
    location__in=access.locations.all(),
)
```

The dashboard only shows a location name in call rows when the user has access to multiple locations. Single-location staff see the restaurant workflow without extra location noise.

## HostHub Dashboard

Main route:

```text
/dashboard/
```

The dashboard is implemented in `hosthub/views.py` and `hosthub/templates/hosthub/index.html`.

HostHub supports:

- Call filtering by category, status, date, custom date, and phone search.
- Default "needs action" workflow.
- Handled/resolved call view.
- Category-specific detail panels.
- Final transcript loading.
- Reservation confirmation SMS.
- Marking calls handled with a disposition.
- Live-call panel with active calls and transfer actions.

### Call Categories

`Call.display_category` values:

- `reservation`
- `carryout`
- `leave_message`
- `private_events`
- `other`

Categories are derived from Bland `pathway_tags`:

- tags containing `reservation` become `reservation`
- tags containing `carryout` become `carryout`
- tags containing `leave` become `leave_message`
- tags containing `private` become `private_events`
- everything else becomes `other`

### Category-Specific Details

The template writes Bland variables into `data-*` attributes, and the HostHub JavaScript renders the selected call based on category.

Common variable usage:

- Reservation: `user_name`, `guest`, `date`, `time`, `request`, `user_message`
- Carryout: `order_summary`, `total_price`, `user_message`
- Private events: `occasion`, `party_date`, `party_time`, `guests`, `party_message`, `user_message`
- Leave message: `user_message`

When Bland pathway variable names change, update both the template bindings and the dashboard JavaScript renderers.

## Bland Integration

### Final And Live Webhook

Route:

```text
/test/webhooks/bland/calls/<token>/
```

The webhook:

- accepts only POST
- validates `<token>` against `BLAND_WEBHOOK_TOKEN`
- requires JSON
- routes live transcript events to `ingest_bland_webhook_event`
- routes final call payloads to `upsert_call_from_bland_json`

Live transcript payloads are identified by:

```python
"message" in payload and payload.get("category") == "call"
```

Final payloads create or update `Call` records.

### Live Calls

HostHub polls Bland active calls through:

```text
/api/bland/live-calls/
```

The backend calls:

```text
https://api.bland.ai/v1/calls/active
```

It filters active calls to the logged-in user's authorized active phone numbers, then upserts `CallSession` rows so transcript and transfer endpoints can authorize against the same tenant boundary.

### Live Transcripts

Routes:

```text
/test/api/calls/<call_id>/turns/
/test/sse/call/<call_id>/?token=<HOSTHUB_SSE_TOKEN>
```

Both require an authenticated user authorized for the `CallSession.to_number`. SSE also requires `HOSTHUB_SSE_TOKEN`.

The frontend uses EventSource for streamed transcript turns and also polls transcript history as a fallback.

### Call Transfer

Route:

```text
/api/bland/transfer-call/
```

The transfer endpoint:

1. Finds the live `CallSession`.
2. Confirms the logged-in user is authorized for the session's `to_number`.
3. Reads the location's `transfer_target` first, then `transfer_number`.
4. Posts to Bland's active-call transfer endpoint.

### Inbound Pathway Sync

Open/closed routing is controlled by Bland inbound pathway IDs on each `Location`.

The app syncs a location's expected pathway to:

```text
https://api.bland.ai/v1/inbound/<phone_number.number>
```

Managers can manually set a store open or closed from the staff area. The scheduler also computes expected state from business hours and date overrides.

## Staff And Manager Area

Route prefix:

```text
/staff/
```

Roles:

- `owner`: can manage workers across the account.
- `manager`: can manage host workers for overlapping assigned locations.
- `host`: can use the HostHub dashboard but does not see the manager area.

The staff area supports:

- worker creation and editing
- assigning locations
- assigning roles
- setting 4-digit PINs
- activating/deactivating workers
- manual open/closed status
- date overrides for special hours or closures

## Reports And Notifications

### Daily Call Reports

Daily reports are account-scoped and built from `Call` rows for a date window.

Command:

```bash
python manage.py send_daily_call_report
```

Only active accounts with daily reporting enabled and a configured report email are processed.

### Reservation Confirmation

Route:

```text
/calls/<call_id>/confirm-reservation/
```

Reservation confirmation sends a payload to `GHL_RESERVATION_CONFIRMATION_WEBHOOK_URL`. If the webhook succeeds, the call is marked resolved with disposition `reservation_confirmed`.

### Carryout Cart Recovery

For final carryout calls, `maybe_send_recovery_sms` can:

1. Extract `order_cart` from Bland variables.
2. Create a cart import link on `160maincarryout.com`.
3. Trigger an SMS through `RECOVERY_SMS_WEBHOOK_URL`.
4. Mark `recovery_sms_sent_at` to prevent duplicate sends.

It skips calls that already printed to the kitchen, have no cart items, have no usable caller phone, or already received a recovery SMS.

## Local Development

From the Django project directory:

```bash
cd test_1
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Default local routes:

```text
http://127.0.0.1:8000/                         landing page
http://127.0.0.1:8000/test/login/              account login
http://127.0.0.1:8000/dashboard/               HostHub dashboard
http://127.0.0.1:8000/staff/                   manager area
http://127.0.0.1:8000/admin/                   Django admin
```

The project expects PostgreSQL configuration through either `DATABASE_URL` or the individual PostgreSQL environment variables used by `settings.py`.

## Environment Variables

The app reads `.env` from `test_1/.env`.

Required or commonly used settings:

```text
SECRET_KEY
ENVIRONMENT
DATABASE_URL
POSTGRES_NAME
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_HOST
POSTGRES_PORT

BLAND_API_KEY
BLAND_ORG_ID
BLAND_WEBHOOK_TOKEN
HOSTHUB_SSE_TOKEN

CARRYOUT_DASHBOARD_SLUG
CART_IMPORT_TOKEN
RECOVERY_SMS_WEBHOOK_URL

GHL_RESERVATION_CONFIRMATION_WEBHOOK_URL

RESEND_API_KEY
RECIPIENT_EMAIL
DEFAULT_FROM_EMAIL

R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
```

Notes:

- `RECOVERY_SMS_WEBHOOK_URL` is accessed with `os.environ[...]`, so it must be present when Django settings load.
- `BLAND_WEBHOOK_TOKEN` protects the Bland webhook route.
- `HOSTHUB_SSE_TOKEN` is an additional gate for transcript SSE streams.
- Location logos are stored through Cloudflare R2/S3 storage.

## Management Commands

Run due schedule transitions and reconcile location pathway state with Bland:

```bash
python manage.py process_location_schedules
```

Send daily call reports:

```bash
python manage.py send_daily_call_report
```

## Legacy Code

The old live-alert system still exists in code:

- `CallAlert`
- `/test/live/alerts/`
- `/test/live/alerts/<alert_id>/resolve/`
- hidden alert banner markup in the HostHub template
- JS alert helper functions

This feature is not active in the current dashboard because `startLiveAlertPolling()` is commented out. The active live-call system is the live calls panel plus transcript history/SSE.

## Operational Notes

- Final call tenant isolation depends on Bland's `to` number matching an active `PhoneNumber`.
- Live-call and transcript endpoints authorize by active phone numbers for the logged-in user's account and locations.
- Phone normalization is currently US-focused.
- `date=all` works by falling through without adding a date filter.
- Dashboard request detail rendering depends on exact Bland pathway variable names.
- There are two similar call-access helpers: `hosthub.views.accessible_calls_for_user` and `testendpoint.services.access.get_visible_calls_queryset`.

## Tech Stack

- Python
- Django 5.1
- PostgreSQL
- WhiteNoise for static files
- Cloudflare R2/S3-compatible storage for media
- Bland.ai for voice calls and inbound pathway configuration
- Resend for daily report email
- GHL webhook for reservation confirmation SMS

## Current Status

This repository is an active product codebase for HostHub. The README is intentionally focused on how the system works today.
