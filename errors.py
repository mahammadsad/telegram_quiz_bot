"""Typed application errors shared across service and CLI boundaries."""

from __future__ import annotations


class ApplicationError(RuntimeError):
    """Base class for expected operational failures."""

    category = "application_error"
    retryable = False


class ConfigurationError(ApplicationError):
    category = "configuration_error"


class QuizGenerationError(ApplicationError):
    category = "quiz_generation_error"


class DatabaseIntegrityError(ApplicationError):
    category = "database_integrity_error"


class TelegramPostingError(ApplicationError):
    category = "telegram_posting_error"
    retryable = True

    def __init__(self, message: str, *, delivery_uncertain: bool = False):
        super().__init__(message)
        self.delivery_uncertain = delivery_uncertain


class ResourceDiscoveryError(ApplicationError):
    category = "resource_discovery_error"
