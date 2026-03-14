"""FastAPI framework exceptions."""


class CallbackError(Exception):
    """Error raised when a lifecycle callback fails.

    This exception is raised when exception/shutdown callbacks fail,
    after logging the error if a logger is available.
    """

    pass


class ConfigError(Exception):
    """Error raised for invalid server configuration.

    This exception is raised at build time when the server configuration
    is invalid or contains conflicting settings.
    """

    pass
