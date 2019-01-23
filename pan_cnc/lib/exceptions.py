# This module holds custom exceptions for Pan-CNC


class SnippetRequiredException(Exception):
    pass


class LoginRequired(Exception):
    pass


class TargetConnectionException(Exception):
    pass

