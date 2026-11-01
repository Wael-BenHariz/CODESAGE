import pytest


@pytest.mark.integration
def test_review_list_requires_auth(api):
    response = api.get("/reviews")
    assert response.status_code in (401, 403)
