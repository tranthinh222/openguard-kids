# Dashboard Week 01

Parent Dashboard use the same FastAPI server with API Agent.

## Stack

- Jinja2: server-side rendering
- HTMX: update enrollment panel without reload page
- Bootstrap 5: responsive UI
- Bootstrap Icons
- Vanilla JavaScript: countdown enrollment code
- FastAPI server-side web session + HttpOnly cookie
- CSRF token for persisting after login

## Route

- `GET /login`
- `POST /login`
- `POST /logout`
- `GET /dashboard`
- `GET /children`
- `GET /children/new`
- `POST /children`
- `GET /children/{child_id}`
- `POST /children/{child_id}/enrollment`

## Development notification

`WEB_COOKIE_SECURE=false` to run local with HTTP. When enabling HTTPS, switch to:

```env
WEB_COOKIE_SECURE=true
```

Bootstrap, Bootstrap Icons and HTMX are currently downloaded via CDN. Perhap vendor these assets into `dashboard/static/vendor/`.
