def test_workspace_pages_render(client):
    for path, page_name in [
        ("/policies", "policies"),
        ("/policies/demo-child", "policy-detail"),
        ("/requests", "requests"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert f'data-page="{page_name}"' in response.text


def test_navigation_uses_first_class_workspace_routes(client):
    response = client.get("/children")
    assert response.status_code == 200
    assert 'href="/policies"' in response.text
    assert 'href="/requests"' in response.text
    assert '/children?view=policies' not in response.text
    assert '/children?view=requests' not in response.text


def test_legacy_workspace_urls_redirect(client):
    response = client.get("/children?view=policies", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/policies"

    response = client.get("/children?view=requests", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/requests"

    response = client.get("/children/child-123?view=policies", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/policies/child-123"

    response = client.get("/children/child-123?view=requests", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/requests?child_id=child-123"
