# openguard-kids

## Screen time and remote policy

Week 02 adds F1 + core F4: versioned screen-time policies, 7×48 weekly schedule,
Agent-side active-use counting with `time.monotonic()`, Windows idle detection,
10/5/1 minute warnings, grace period, workstation locking, extra-time requests,
and queued/realtime device commands.

Before running the Agent in the course lab, the Agent and Server must share the same
`POLICY_HMAC_SECRET` / `OGK_POLICY_HMAC_SECRET`. Then run:

```bash
cd server
alembic upgrade head
uvicorn app.main:app --reload
```

On the Windows Agent environment:

```powershell
$env:OGK_SERVER_URL="http://<server>:8000"
$env:OGK_POLICY_HMAC_SECRET="<same policy secret as server>"
python agent/openguard_agent.py run
```

The dashboard Child Detail page now edits quota/schedule and reviews extra-time
requests. See `WEEK02_CHANGES.md` for the complete add/modify/remove list.
