def test_test_route_is_removed(client):
    """Bug test: /test backdoor route must not exist and should return 404."""
    response = client.get('/test')
    assert response.status_code == 404

def test_name_equals_test_does_not_bypass_validation(client):
    """Bug test: name='test' in form submission must not bypass validation or redirect."""
    response = client.post('/', data={'name': 'test'})
    # It should fail validation and render index.html with errors (200), not 302 redirect
    assert response.status_code == 200
    assert b"Registration Form" in response.data
    # Should contain validation error or form errors, not redirect to success
    assert response.headers.get('Location') is None
