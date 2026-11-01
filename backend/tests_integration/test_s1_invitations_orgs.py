import pytest


@pytest.mark.integration
def test_org_listing_requires_valid_identity(api, token_for):
    token = token_for("org_admin")
    response = api.get("/orgs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
