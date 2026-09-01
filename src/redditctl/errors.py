from __future__ import annotations


class RedditctlError(Exception):
    code = "redditctl_error"
    retryable = False

    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class UsageError(RedditctlError):
    code = "usage_error"


class ConfigurationError(RedditctlError):
    code = "configuration_error"


class AuthenticationError(RedditctlError):
    code = "authentication_error"


class PermissionDeniedError(RedditctlError):
    code = "permission_error"


class RateLimitedError(RedditctlError):
    code = "rate_limited"
    retryable = True


class PolicyError(RedditctlError):
    code = "policy_error"


class ValidationError(RedditctlError):
    code = "validation_error"


class NetworkError(RedditctlError):
    code = "network_error"
    retryable = True


class UncertainOutcomeError(RedditctlError):
    code = "uncertain_outcome"


class StorageError(RedditctlError):
    code = "storage_error"


class InternalError(RedditctlError):
    code = "internal_error"
