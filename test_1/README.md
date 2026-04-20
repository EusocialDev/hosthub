# HostHub Voice Agent

HostHub is a Django application for restaurant call operations. It ingests calls from Bland.ai, organizes them by account and location, and gives hosts a focused dashboard for reviewing, resolving, and monitoring guest calls.

The app is built around a multi-tenant model:

- **Account**: the business or restaurant group.
- **Location**: a physical restaurant/location owned by an account.
- **UserAccess**: the permission record that connects a Django user to an account, role, and allowed locations.
- **Call**: an ingested voice-agent call associated with an account, location, and phone number.

## Core Features

- **HostHub dashboard** for calls that need host action.
- **Worker PIN login** scoped to a selected account and location.
- **Location-based access control** through `UserAccess.locations`.
- **Call filtering** by status, category, date, and phone number.
- **Call resolution workflow** with handled/unhandled states and dispositions.
- **Live call monitoring** through polling and server-sent events.
- **Final transcript access** protected by the logged-in user's location permissions.
- **Staff management** for owners/managers to create, edit, activate, and deactivate workers.
- **Location status controls** for store open/closed overrides and Bland pathway syncing.
- **Bland.ai webhook ingestion** for call records, transcripts, summaries, tags, and phone-number tenant resolution.
- **Daily report/email support** through management commands and reporting services.

## Project Structure

```text
.
├── manage.py
├── requirements.txt
├── test_1/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── testendpoint/
│   ├── models.py
│   ├── views.py
│   ├── views_live.py
│   ├── views_sse.py
│   ├── urls.py
│   ├── services/
│   ├── templates/testendpoint/
│   └── static/testendpoint/
├── hosthub/
│   ├── views.py
│   ├── urls.py
│   ├── templates/hosthub/
│   └── static/hosthub/
└── staff/
    ├── views.py
    ├── forms.py
    ├── services/
    ├── templates/staff/
    └── static/staff/
```

## Django Apps

### `testendpoint`

Owns the core data model and external integrations:

- Accounts, locations, phone numbers, calls, alerts, sessions, transcripts, and user access.
- Login/location selection views.
- Bland.ai webhook ingestion.
- Live transcript and SSE endpoints.
- Report and email service code.

### `hosthub`

Owns the main host-facing dashboard:

- Dashboard view at `/dashboard/`.
- Call queue filtering and counts.
- Call resolution actions.
- Live call UI endpoints.
- Bland transfer/live-call helper endpoints.

### `staff`

Owns manager/admin workflows inside the app:

- Worker list, create, and edit screens.
- Role and location assignment.
- Worker active/inactive toggles.
- Store status override controls.
- Location schedule reconciliation helpers.

## Main Routes

```text
/                         Landing page
/dashboard/                HostHub dashboard
/staff/                    Worker management
/admin/                    Django admin

/test/login/               Account picker
/test/login/<account>/     Location picker
/test/login/<account>/<location>/
                           Worker PIN login
/test/logout/              Logout

/test/webhooks/bland/calls/<token>/
                           Bland.ai call webhook
/test/sse/call/<call_id>/  Live call SSE stream
/test/transcript/call/<id>/
                           Final transcript endpoint
```

## Access Model

The app's business-data permissions are user based. Most protected views resolve access through:

```python
request.user.hosthub_access
```

That `UserAccess` record determines:

- which account the user belongs to,
- which locations the user can access,
- whether the access is active,
- and whether the user is an `owner`, `manager`, or `host`.

Session values such as `active_account_id` and `active_location_id` are used as UI context. They should narrow the current location experience, but they should not be treated as the source of authorization for calls, transcripts, staff actions, or live streams.

## Local Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root.

Minimum local values:

```env
SECRET_KEY=replace-me
POSTGRES_NAME=hosthub
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Optional integration values:

```env
ENVIRONMENT=local
DATABASE_URL=
BLAND_API_KEY=
BLAND_ORG_ID=
BLAND_WEBHOOK_TOKEN=
HOSTHUB_SSE_TOKEN=
CARRYOUT_DASHBOARD_SLUG=
RESEND_API_KEY=
RECIPIENT_EMAIL=
DEFAULT_FROM_EMAIL=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
```

4. Run migrations:

```bash
python manage.py migrate
```

5. Create an admin user:

```bash
python manage.py createsuperuser
```

6. Start the development server:

```bash
python manage.py runserver
```

The app will be available at:

```text
http://127.0.0.1:8000/
```

## Common Commands

Run tests:

```bash
python manage.py test
```

Collect static files:

```bash
python manage.py collectstatic
```

Send daily call report:

```bash
python manage.py send_daily_call_report
```

Process location schedules:

```bash
python manage.py process_location_schedules
```

## Environment Notes

The app reads `ENVIRONMENT` to switch behavior for production, staging, and local development.

- `production` disables `DEBUG` and uses `hosthub.160maincarryout.com`.
- `staging` enables `DEBUG` and uses `devhosthub.160maincarryout.com`.
- any other value defaults to local development behavior.

The database can be configured either with `DATABASE_URL` or individual Postgres variables.

Media storage is configured for Cloudflare R2/S3-compatible storage. Static files are served with WhiteNoise using compressed manifest storage.

## Development Notes

- Keep tenant/business-data authorization centered on `UserAccess`.
- Check account, location, and user active states before exposing login or dashboard data.
- Use session location values as current UI context only after confirming the logged-in user can access that location.
- Prefer central permission helpers for repeated access checks.
- Keep host-facing screens touch-friendly, fast, and focused on calls needing action.

## Product Flow

Typical HostHub flow:

```text
Choose account
    -> choose location
        -> worker selects name and enters PIN
            -> HostHub dashboard
                -> review calls
                -> resolve calls
                -> monitor live calls
```

Manager flow:

```text
Manager/owner logs in
    -> opens Manager Area
        -> manages workers
        -> assigns roles and locations
        -> toggles worker access
        -> manages location status
```

## Browser Support

HostHub is designed for modern browsers with support for:

- CSS Grid and Flexbox,
- standard JavaScript event handling,
- server-sent events,
- responsive layouts,
- and touch-friendly controls.
