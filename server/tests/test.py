from fastapi.testclient import TestClient
from httpx import Response, Request

def health_check_should_be_success(client: TestClient):
    response: Response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def register_parent_should_be_success_if_valid(client: TestClient):
    response: Response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "parent@example.com",
            "password": "StrongPassword123!",
        },
    )

    assert response.status_code == 201

def login_parent_should_be_success_if_valid(client: TestClient):
    response: Response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "parent@example.com",
            "password": "StrongPassword123!",
        },
    )

    assert response.status_code == 200

