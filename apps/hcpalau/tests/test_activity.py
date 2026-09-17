def test_activity_is_admin_only(client, admin_headers) -> None:
    assert client.get("/activity").status_code == 401
    assert client.get("/activity", headers=admin_headers).status_code == 200
