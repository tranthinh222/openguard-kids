import re


def login_dashboard(client, email="workspace@example.com"):
    credentials = {"email": email, "password": "StrongPass123!"}
    assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    login_page = client.get("/login")
    csrf = re.search(r'data-login-csrf="([^"]+)"', login_page.text).group(1)
    login = client.post(
        "/api/v1/auth/login",
        json=credentials,
        headers={"X-CSRF-Token": csrf},
    )
    assert login.status_code == 200
    return login.json()["csrf_token"]


def test_workspace_data_apis_work_with_dashboard_cookie_session(client):
    csrf = login_dashboard(client)
    child = client.post(
        "/api/v1/children",
        json={"display_name": "Minh"},
        headers={"X-CSRF-Token": csrf},
    )
    assert child.status_code == 201
    child_id = child.json()["id"]

    children = client.get("/api/v1/children")
    assert children.status_code == 200
    assert [item["id"] for item in children.json()] == [child_id]

    policy = client.get(f"/api/v1/children/{child_id}/policy")
    assert policy.status_code == 200
    assert policy.json()["version"] == 1

    requests = client.get(f"/api/v1/children/{child_id}/requests")
    assert requests.status_code == 200
    assert requests.json() == []

    policy_page = client.get(f"/policies/{child_id}")
    assert policy_page.status_code == 200
    assert f'data-child-id="{child_id}"' in policy_page.text
    assert f'href="/children/{child_id}"' in policy_page.text

    child_page = client.get(f"/children/{child_id}")
    assert child_page.status_code == 200
    assert f'href="/policies/{child_id}"' in child_page.text
    assert f'href="/requests?child_id={child_id}"' in child_page.text
