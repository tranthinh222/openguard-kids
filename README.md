# openguard-kids

## Screen time and remote policy

Week 02 adds F1 + core F4: versioned screen-time policies, 7×48 weekly schedule,
Agent-side active-use counting with `time.monotonic()`, Windows idle detection,
10/5/1 minute warnings, grace period, workstation locking, extra-time requests,
and queued/realtime device commands.

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
