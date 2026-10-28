"""A suíte é offline: chamadas HTTP exigem transporte simulado explicitamente."""
import pytest
import requests
import httpx


@pytest.fixture(autouse=True)
def bloquear_http_real(monkeypatch):
    def bloqueado(*args, **kwargs):
        raise AssertionError("HTTP real bloqueado na suíte; use resposta simulada ou validador manual.")
    monkeypatch.setattr(requests.sessions.Session, "request", bloqueado)
    monkeypatch.setattr(httpx.Client, "send", bloqueado)
