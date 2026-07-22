"""Public exceptions raised by registry and routing APIs."""


class SeaMileError(Exception):
    """Base exception for recoverable sea-mile errors."""

    code = "sea_mile_error"


class RegistryDataError(SeaMileError):
    """The local registry files are missing or violate their schema."""

    code = "registry_data_error"


class SourceDataError(SeaMileError):
    """A public reference snapshot could not be downloaded or read."""

    code = "source_data_error"


class PortNotFoundError(SeaMileError):
    """No port satisfies the requested identifier or exact name."""

    code = "port_not_found"


class AmbiguousPortError(SeaMileError):
    """More than one independent port identity satisfies a request."""

    code = "ambiguous_port"


class PortCoordinateError(SeaMileError):
    """A selected port has no usable routing coordinate."""

    code = "port_coordinate"
