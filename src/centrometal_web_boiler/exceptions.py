"""Errors raised by the library."""


class WebBoilerError(Exception):
    """An exchange with the Centrometal cloud failed (HTTP error, unexpected page or data)."""


class WebBoilerAuthError(WebBoilerError):
    """The website refused the e-mail / password."""
