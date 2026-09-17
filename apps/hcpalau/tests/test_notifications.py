def test_notification_stub_requires_admin_and_never_claims_delivery(client, admin_headers) -> None:
    unauthorized = client.post("/notifications/send/1/1")
    assert unauthorized.status_code == 401

    response = client.post("/notifications/send/1/1", headers=admin_headers)

    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "provider_not_configured"
