from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, NoKeyringError

from redditctl.errors import ConfigurationError


class CredentialStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringCredentialStore:
    def __init__(self, service: str = "redditctl") -> None:
        self.service = service

    def get(self, name: str) -> str | None:
        try:
            return keyring.get_password(self.service, name)
        except (KeyringError, NoKeyringError) as exc:
            raise ConfigurationError("No supported OS credential store is available") from exc

    def set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(self.service, name, value)
        except (KeyringError, NoKeyringError) as exc:
            raise ConfigurationError("Could not write to the OS credential store") from exc

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self.service, name)
        except keyring.errors.PasswordDeleteError:
            return
        except (KeyringError, NoKeyringError) as exc:
            raise ConfigurationError("Could not access the OS credential store") from exc


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)
