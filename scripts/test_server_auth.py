from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server


def test_health_is_public():
    client = TestClient(server.app)
    res = client.get('/health')
    assert res.status_code == 200
    assert res.json()['status'] == 'ok'


def test_sensitive_routes_fail_closed_in_production_without_api_token(monkeypatch):
    monkeypatch.setenv('MIRAGE_ENV', 'production')
    monkeypatch.delenv('MIRAGE_API_TOKEN', raising=False)
    client = TestClient(server.app)
    res = client.post('/profile', json={'data': [{'a': 1}]})
    assert res.status_code == 503


def test_sensitive_routes_accept_bearer_token(monkeypatch):
    monkeypatch.setenv('MIRAGE_ENV', 'production')
    monkeypatch.setenv('MIRAGE_API_TOKEN', 'test-token')
    client = TestClient(server.app)
    res = client.post(
        '/profile',
        headers={'Authorization': 'Bearer test-token'},
        json={'data': [{'a': 1}, {'a': 2}]},
    )
    assert res.status_code == 200
    assert res.json()['columns'][0]['name'] == 'a'


def test_sensitive_routes_reject_wrong_token(monkeypatch):
    monkeypatch.setenv('MIRAGE_ENV', 'production')
    monkeypatch.setenv('MIRAGE_API_TOKEN', 'test-token')
    client = TestClient(server.app)
    res = client.post(
        '/profile',
        headers={'X-API-Key': 'wrong-token'},
        json={'data': [{'a': 1}]},
    )
    assert res.status_code == 401
