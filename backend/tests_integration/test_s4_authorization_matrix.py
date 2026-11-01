import pytest


@pytest.mark.integration
def test_platform_settings_requires_auth(api):
    response = api.get("/platform/settings")
    assert response.status_code in (401, 403)


@pytest.mark.integration
def test_developer_cannot_read_platform_settings(api, token_for):
    response = api.get(
        "/platform/settings",
        headers={"Authorization": f"Bearer {token_for('developer')}"},
    )
    assert response.status_code == 403
