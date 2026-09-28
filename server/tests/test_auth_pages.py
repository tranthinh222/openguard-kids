import re


def test_auth_pages_and_nested_assets(client):
    for path, form in [("/login", "login-form"), ("/register", "register-form")]:
        response = client.get(path)
        assert response.status_code == 200
        assert f'id="{form}"' in response.text
        assert 'href="/static/css/app.css"' in response.text
        assert 'href="/register"' in response.text
        assert 'href="/login"' in response.text
    assert client.get("/static/js/register.js").status_code == 200


def test_register_then_login_with_csrf(client):
    payload = {"email": "family@example.com", "password": "FamilyPass123!"}
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    assert response.json()["role"] == "parent"
    assert "password" not in response.json()
    assert client.get("/api/v1/auth/session").status_code == 401
    assert client.post("/api/v1/auth/login", json=payload).status_code == 403
    login_page = client.get("/login")
    csrf = re.search(r'data-login-csrf="([^"]+)"', login_page.text).group(1)
    response = client.post("/api/v1/auth/login", json=payload, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/session").json()["user"]["email"] == payload["email"]


def test_register_rejects_duplicate_and_invalid_input(client):
    payload = {"email": "family@example.com", "password": "FamilyPass123!"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["message"] == "Email already registered"
    assert client.post("/api/v1/auth/register", json={**payload, "email": "invalid"}).status_code == 422
    assert client.post("/api/v1/auth/register", json={**payload, "password": "lowercase123"}).status_code == 400
