"""Errors the services raise. Clients show ``str(error)`` to the student; the API
(Phase 3) maps each class to an HTTP status."""


class ServiceError(Exception):
    """Base class. The message is safe to show to a student."""


class InvalidInput(ServiceError):
    """The request itself is wrong (empty answer, unknown course, bad week)."""


class NotEnrolled(ServiceError):
    """The learner isn't enrolled in the course."""


class NoActiveSession(ServiceError):
    """There's no quiz or tutor session to act on."""


class WrongState(ServiceError):
    """The session isn't in a state that allows this (e.g. answering during feedback)."""


class Busy(ServiceError):
    """The learner's previous request is still being processed."""


class Unavailable(ServiceError):
    """A dependency (model, retrieval, storage) failed; trying again may work."""


class RateLimited(ServiceError):
    """Too many attempts; ``retry_after`` says how many seconds to wait."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class NotAuthenticated(ServiceError):
    """Missing, unknown or expired login token."""


class NotPermitted(ServiceError):
    """Logged in, but the account's role or course ownership doesn't allow this."""


class NotFound(ServiceError):
    """The account or thing asked about doesn't exist."""
