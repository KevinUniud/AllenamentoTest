"""Typed failures raised by the SWI-Prolog integration layer."""


class PrologBridgeError(Exception):
    """Base error for bridge, protocol and process failures."""


class PrologNotFoundError(PrologBridgeError):
    """SWI-Prolog executable or a required source file was not found."""


class PrologExecutionError(PrologBridgeError):
    """SWI-Prolog returned an error or an invalid response."""
