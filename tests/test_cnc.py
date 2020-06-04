def test_with_client(client):
    response = client.get('/')
    print(response.status_code)
    assert response.status_code == 302
