# openguard-kids

## Screen time and remote policy

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
