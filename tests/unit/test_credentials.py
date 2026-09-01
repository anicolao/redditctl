from __future__ import annotations

import keyring

from redditctl.credentials import KeyringCredentialStore, MemoryCredentialStore


def test_memory_credential_store_round_trip() -> None:
    store = MemoryCredentialStore()
    store.set("key", "value")
    assert store.get("key") == "value"
    store.delete("key")
    assert store.get("key") is None


def test_keyring_credential_store_delegates(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, name: values.get((service, name)))
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda service, name, value: values.__setitem__((service, name), value),
    )
    monkeypatch.setattr(
        keyring, "delete_password", lambda service, name: values.pop((service, name))
    )
    store = KeyringCredentialStore("test")
    store.set("name", "secret")
    assert store.get("name") == "secret"
    store.delete("name")
    assert store.get("name") is None
