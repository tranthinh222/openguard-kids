# Parent dashboard

Jinja2 serves the HTML pages. JavaScript modules fetch the existing FastAPI JSON APIs. Bootstrap 5 and Bootstrap Icons provide the shared UI foundation.

## Account flow

- `GET /register` renders the registration page.
- `POST /api/v1/auth/register` receives `{email, password}`. The confirmation field is checked locally and is not sent to the API.
- Registration creates an account, then redirects to `/login?registered=1` with a success message. It does not create a session.
- `GET /login` renders the login page and issues the login CSRF cookie.
- `POST /api/v1/auth/login` receives credentials plus the `X-CSRF-Token` header and creates an HttpOnly session cookie.
- `GET /api/v1/auth/session` loads the signed-in parent; `POST /api/v1/auth/logout` ends the session.

Both account forms support password visibility controls, loading states and API error messages. Registration checks the same five password requirements as the server and verifies password confirmation. Server validation remains authoritative.

## Dashboard pages

The dashboard uses first-class workspaces with separate responsibilities:

- `/dashboard` — family overview.
- `/children` — child profiles.
- `/children/new` — create a child profile.
- `/children/{child_id}` — devices, enrollment and shortcuts to child-related workspaces.
- `/policies` — policy overview for all children.
- `/policies/{child_id}` — screen-time quota and 7 × 48 weekly schedule editor.
- `/requests` — centralized extra-time request queue with child/status filters.
- Reports remain unavailable until Week 03.

All pages use the shared authenticated shell and fetch data through `/api/v1/` routes. Enrollment creation, copy/countdown and live pairing status remain in `child-detail.js`. Policy editing is owned by `policies.js`; request processing is owned by `requests.js`.

Legacy Week 02 URLs such as `/children?view=policies` and `/children/{id}?view=requests` redirect to the new first-class routes. No API contract or database migration is required for this UI refactor.

## UI

`templates/auth/layout.html` contains the shared login/registration layout. `static/css/app.css` defines the green/cream palette, responsive layouts and the animated CSS family illustration (floating hearts, blinking faces, staggered entrance). Reduced-motion preferences disable all animation. No external illustration assets are required.

The design direction uses the supplied UI reference document and Google Family Link's family-oriented presentation as inspiration, without copying product assets or adding controls for unavailable features.

## Local development

Use `WEB_COOKIE_SECURE=false` with local HTTP; set it to `true` for HTTPS. Bootstrap and Bootstrap Icons are loaded from CDN, so their styles require network access.

Run the account integration checks from `server/`:

```bash
../.venv/bin/python -m pytest tests/test_auth_pages.py -q
```

The tests use the existing isolated in-memory database fixture.

## Automatic device updates

The dashboard, children list and child detail page refresh their existing read APIs every 5 seconds after the previous request completes. Newly enrolled devices appear without a page reload. Online status remains server-calculated: a device is online for less than 120 seconds after its latest heartbeat; a newly paired device without a heartbeat is shown as offline.

`static/js/live-refresh.js` pauses while the tab is hidden and refreshes on return. Requests have a 10-second timeout, never overlap, and retry transient errors with backoff up to 30 seconds. The page keeps its last data and displays a stale-data notice while reconnecting. Lost access stops polling. An unchanged response does not rebuild the content; child detail refreshes only the device list, preserving the enrollment code and countdown.

Heartbeat timestamps in parent-facing responses include UTC timezone information. Device changes and timeout transitions become visible on the next successful poll (normally within about 5 seconds plus request time).

Tests:

```bash
# From the repository root; Node 24 supports the fake timer test API.
node --test server/dashboard/tests/live-refresh.test.mjs

# From server/; isolated SQLite fixtures, no real device or wait required.
../.venv/bin/python -m pytest tests/test_device_updates.py tests/test_auth_pages.py -q
```

When creating a pairing code, the API also returns `enrollment_id`. While that code is displayed, the child detail refresh checks `GET /api/v1/children/{child_id}/enrollment/{enrollment_id}`. This read endpoint checks parent/child ownership and returns `pending`, `used`, or `expired`, without exposing the code or its hash.

Once the displayed code is used, the UI removes the code and copy button, stops the countdown, and displays a pairing-success message. A different code being used for the same child does not trigger this message. The parent can immediately create another code; late responses for a previous code are ignored. No database migration is required.
