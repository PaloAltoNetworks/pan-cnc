import pytest


@pytest.mark.scm
def test_with_client(client):
    response = client.get('/')
    assert response.status_code == 302
