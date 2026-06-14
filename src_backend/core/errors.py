class BaseAppError(Exception):
    """Base application error."""


class RoutingError(BaseAppError):
    """Raised when orchestration routing cannot produce a valid result."""


class SkillNotFoundError(BaseAppError):
    """Raised when a selected skill file does not exist."""


class MemoryNotFoundError(BaseAppError):
    """Raised when a selected memory file does not exist."""


class UnsafeMemoryPathError(MemoryNotFoundError):
    """Raised when a selected memory file path escapes the asset memory root."""


class LLMProviderError(BaseAppError):
    """Raised when an LLM provider cannot complete a request."""


class ConfigurationError(BaseAppError):
    """Raised when runtime configuration is invalid."""
