import pytest


@pytest.mark.integration
@pytest.mark.parametrize(
    "role", ["platform", "org_admin", "reviewer", "developer", "none", "invitee"]
)
def test_auth_me_role_matrix(api, token_for, role):
    response = api.get(
        "/auth/me", headers={"Authorization": f"Bearer {token_for(role)}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("role")
    assert isinstance(data.get("capabilities"), dict)
