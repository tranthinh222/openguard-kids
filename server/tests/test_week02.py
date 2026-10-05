from datetime import datetime, timezone


def parent_headers(client, email="week2@example.com"):
    credentials={"email":email,"password":"StrongPass123!"}
    assert client.post("/api/v1/auth/register",json=credentials).status_code==201
    token=client.post("/api/v1/auth/token",json=credentials).json()["access_token"]
    return {"Authorization":f"Bearer {token}"}


def enrolled_device(client, headers):
    child=client.post("/api/v1/children",headers=headers,json={"display_name":"Minh"}).json(); cid=child["id"]
    code=client.post(f"/api/v1/children/{cid}/enrollment",headers=headers).json()["code"]
    device=client.post("/api/v1/agent/enroll",json={"code":code,"device_name":"PC Minh","fingerprint":"week2-fingerprint"}).json()
    return cid, device


def test_policy_update_increments_version_and_heartbeat_delivers_it(client):
    headers=parent_headers(client); cid,device=enrolled_device(client,headers)
    old=client.get(f"/api/v1/children/{cid}/policy",headers=headers).json(); assert old["version"]==1
    slots=[True]*336; slots[0]=False
    payload={"payload":{"screen_time":{"weekday_minutes":60,"weekend_minutes":120,"idle_timeout_sec":300,"grace_period_sec":60,"warning_minutes":[10,5,1]},"weekly_schedule":slots,"apps":[],"domains":[]}}
    updated=client.put(f"/api/v1/children/{cid}/policy",headers=headers,json=payload)
    assert updated.status_code==200 and updated.json()["version"]==2 and updated.json()["signature"]!=old["signature"]
    hb=client.post("/api/v1/agent/heartbeat",headers={"Authorization":f"Bearer {device['access_token']}"},json={"policy_version":1,"agent_version":"0.2.0","quota_used_sec":30,"agent_wall_clock":datetime.now(timezone.utc).isoformat()})
    assert hb.status_code==200 and hb.json()["policy_update_available"] is True and hb.json()["policy_version"]==2


def test_extra_time_approval_creates_command_and_ack(client):
    headers=parent_headers(client,"request@example.com"); cid,device=enrolled_device(client,headers); auth={"Authorization":f"Bearer {device['access_token']}"}
    req=client.post("/api/v1/agent/requests",headers=auth,json={"type":"extra_time","requested_minutes":15}); assert req.status_code==200
    request_id=req.json()["id"]
    approved=client.post(f"/api/v1/children/{cid}/requests/{request_id}/approve",headers=headers,json={}); assert approved.status_code==200
    hb=client.post("/api/v1/agent/heartbeat",headers=auth,json={"policy_version":1,"agent_version":"0.2.0"}); commands=hb.json()["commands"]
    assert len(commands)==1 and commands[0]["type"]=="ADD_TIME" and commands[0]["payload"]["minutes"]==15
    command_id=commands[0]["command_id"]
    ack=client.post(f"/api/v1/agent/commands/{command_id}/ack",headers=auth,json={"status":"completed"}); assert ack.status_code==200 and ack.json()["status"]=="completed"


def test_parent_cannot_change_other_child_policy(client):
    a=parent_headers(client,"a2@example.com"); b=parent_headers(client,"b2@example.com"); cid,_=enrolled_device(client,a)
    policy=client.get(f"/api/v1/children/{cid}/policy",headers=a).json()
    assert client.put(f"/api/v1/children/{cid}/policy",headers=b,json={"payload":policy["payload"]}).status_code==404


def test_realtime_websocket_delivers_parent_command(client):
    headers = parent_headers(client, "ws@example.com")
    cid, device = enrolled_device(client, headers)
    auth = {"Authorization": f"Bearer {device['access_token']}"}
    # Get the concrete device id owned by this child.
    device_id = client.get(f"/api/v1/children/{cid}/devices", headers=headers).json()[0]["id"]
    with client.websocket_connect("/api/v1/agent/ws", headers=auth) as ws:
        created = client.post(
            f"/api/v1/devices/{device_id}/commands",
            headers=headers,
            json={"type": "ADD_TIME", "minutes": 15},
        )
        assert created.status_code == 201
        message = ws.receive_json()
        assert message["command_id"] == created.json()["id"]
        assert message["type"] == "ADD_TIME"
        ws.send_json({"type": "ack", "command_id": message["command_id"], "status": "completed"})


def test_request_decisions_are_pushed_to_agent_in_realtime(client):
    headers = parent_headers(client, "decision@example.com")
    cid, device = enrolled_device(client, headers)
    auth = {"Authorization": f"Bearer {device['access_token']}"}
    base = f"/api/v1/children/{cid}/requests"
    with client.websocket_connect("/api/v1/agent/ws", headers=auth) as ws:
        first = client.post("/api/v1/agent/requests", headers=auth, json={"type": "extra_time", "requested_minutes": 15}).json()["id"]
        assert client.post(f"{base}/{first}/reject", headers=headers, json={"response": "Mai nhé"}).status_code == 200
        rejected = ws.receive_json()
        assert rejected["type"] == "REQUEST_REJECTED"
        assert rejected["payload"] == {"minutes": 15, "request_id": first, "response": "Mai nhé"}

        second = client.post("/api/v1/agent/requests", headers=auth, json={"type": "extra_time", "requested_minutes": 15}).json()["id"]
        assert client.post(f"{base}/{second}/approve", headers=headers, json={}).status_code == 200
        approved = ws.receive_json()
        assert approved["type"] == "ADD_TIME"
        assert approved["payload"] == {"minutes": 15, "request_id": second}


def test_parent_cannot_send_request_rejected_command(client):
    headers = parent_headers(client, "forged@example.com")
    cid, _ = enrolled_device(client, headers)
    device_id = client.get(f"/api/v1/children/{cid}/devices", headers=headers).json()[0]["id"]
    forged = client.post(f"/api/v1/devices/{device_id}/commands", headers=headers, json={"type": "REQUEST_REJECTED"})
    assert forged.status_code == 422
