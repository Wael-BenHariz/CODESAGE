import pytest


@pytest.mark.integration
def test_health_and_readiness_are_available(api):
    root = str(api.base_url).split("/api/v1", maxsplit=1)[0]
    assert api.get(root + "/api/v1/health").status_code == 200
    assert api.get(root + "/api/v1/health/ready").status_code == 200
