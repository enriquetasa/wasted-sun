"""Application-specific errors (avoid overloading RuntimeError)."""


class ConfigurationError(ValueError):
    """Invalid operator configuration (e.g. env vars for Postgres)."""
