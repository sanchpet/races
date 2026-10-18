import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests run on recorded fixtures; any real connection is a bug."""

    def refuse(*args, **kwargs):
        raise RuntimeError("network access in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
