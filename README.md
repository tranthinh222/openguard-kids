# openguard-kids

## Screen time and remote policy

### Environment files

| File | Purpose | Loaded automatically? |
| --- | --- | --- |
| `.env.example` | Shared local-development template for Server + Agent; safe to commit | No |
| `.env` | Actual local configuration and secrets; never commit | Yes, by Server and Agent |
| `server/.env.example` | Server-only deployment template; safe to commit | No |
| `server/.env.deploy` | Actual Docker deployment variables; never commit | Only via `docker --env-file` |

For local development, create root `.env` from root `.env.example` only when
it does not exist. Merge newly added settings into an existing `.env` manually;
copying the template over it would replace current secrets and configuration.
The files are alternatives for different environments, not three configuration
layers to concatenate. See [server deployment instructions](server/README.md).

Precedence is **process environment > root `.env` > code defaults** for settings
loaded by the application. `server/.env` is not automatically loaded. Server
settings use names such as `DATABASE_URL`; Agent settings use the `OGK_` prefix.
Keep `POLICY_HMAC_SECRET` and `OGK_POLICY_HMAC_SECRET` identical, and keep the
server/agent report timezone offsets consistent. Restart the affected process
after changes. A PowerShell `$env:...` override continues to take precedence
until removed or the shell is closed.

`RETENTION_INTERVAL_SEC` controls how often the server runs cleanup; it does
not change the 90-day activity retention age. The code default is 86400 seconds
(daily). The deployment template currently specifies 776000 seconds (about
9 days); choose the intended cleanup frequency when preparing deployment.

Week 02 adds F1 + core F4: versioned screen-time policies, 7×48 weekly schedule,
Agent-side active-use counting with `time.monotonic()`, Windows idle detection,
10/5/1 minute warnings, grace period, workstation locking, extra-time requests,
and queued/realtime device commands.

Clock drift handling, restart/offline behavior and manual verification are
documented in [docs/CLOCK_DRIFT.md](docs/CLOCK_DRIFT.md).

Before running locally, copy `.env.example` to `.env` if `.env` doesn't exist.
The Agent and Server load this shared project-level file automatically; keep
`POLICY_HMAC_SECRET` and `OGK_POLICY_HMAC_SECRET` identical. Then run:

```bash
cd server
alembic upgrade head
uvicorn app.main:app --reload
```

On the Windows Agent environment, edit `OGK_SERVER_URL` in `.env` when the
server is on another machine, then run:

```powershell
python agent/openguard_agent.py run
```

The dashboard Child Detail page now edits quota/schedule and reviews extra-time
requests. See `WEEK02_CHANGES.md` for the complete add/modify/remove list.
