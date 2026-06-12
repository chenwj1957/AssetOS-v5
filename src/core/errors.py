class PMIntelligenceError(Exception):
    """Base application error."""


class RoutingError(PMIntelligenceError):
    """Raised when orchestration routing cannot produce a valid result."""


class SkillNotFoundError(PMIntelligenceError):
    """Raised when a selected skill file does not exist."""


class MemoryNotFoundError(PMIntelligenceError):
    """Raised when a selected memory file does not exist."""


class UnsafeMemoryPathError(MemoryNotFoundError):
    """Raised when a selected memory file path escapes the asset memory root."""


class LLMProviderError(PMIntelligenceError):
    """Raised when an LLM provider cannot complete a request."""


class ConfigurationError(PMIntelligenceError):
    """Raised when runtime configuration is invalid."""
