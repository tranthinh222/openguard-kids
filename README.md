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
uvicorn app.main:app --reload                      # agent on the same machine
uvicorn app.main:app --host 0.0.0.0 --port 8000    # agent on another machine
```

`uvicorn` listens on 127.0.0.1 by default, which other machines cannot reach.
When the agent runs on another machine, start the server with `--host 0.0.0.0`
and allow TCP 8000 through the server machine's firewall.

On the Windows Agent machine, copy `.env.example` to `.env`, set `OGK_SERVER_URL`
to the server's LAN address (for example `http://192.168.1.10:8000`, not
`127.0.0.1`) and set `OGK_POLICY_HMAC_SECRET` to the server's
`POLICY_HMAC_SECRET`, then run:

```powershell
python agent/openguard_agent.py run
```

On Windows the agent keeps its data in `C:\ProgramData\OpenGuardKids`. After
`agent/openguard_service.py install` that folder is writable only by SYSTEM and
Administrators, so do not use `run` any more: the service already runs the agent,
and `agent_gui.py` is the tray UI. Without the service, run `run` from an
elevated PowerShell ("Run as Administrator"), or point `OGK_STATE_PATH` at another
folder for testing. See `agent/WEEK04.md`.

The dashboard Child Detail page now edits quota/schedule and reviews extra-time
requests. See `WEEK02_CHANGES.md` for the complete add/modify/remove list.
