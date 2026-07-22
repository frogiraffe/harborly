"""Public exceptions raised by registry and routing APIs."""


class SeaMileError(Exception):
    """Base exception for recoverable sea-mile errors."""


class RegistryDataError(SeaMileError):
    """The local registry files are missing or violate their schema."""


class SourceDataError(SeaMileError):
    """A public reference snapshot could not be downloaded or read."""


class PortNotFoundError(SeaMileError):
    """No port satisfies the requested identifier or exact name."""


class AmbiguousPortError(SeaMileError):
    """More than one independent port identity satisfies a request."""


class PortCoordinateError(SeaMileError):
    """A selected port has no usable routing coordinate."""
