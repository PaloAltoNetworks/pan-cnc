import re

import netaddr
from django.core.validators import ValidationError
from django.utils.deconstruct import deconstructible
from netaddr import AddrFormatError
import json


@deconstructible
class FqdnOrIp:
    """
    Checks for valid IPv4, IPv6, or hostname notation from value. Uses netaddr to do the heavy lifting
    """
    regex = ''

    def __init__(self, value):
        hostname_re = r'(?=^.{4,253}$)(^((?!-)[a-zA-Z0-9-]{0,62}[a-zA-Z0-9]\.)+[a-zA-Z]{2,63}$)'
        self.regex = re.compile(hostname_re, re.IGNORECASE)
        self.__call__(value)

    def __call__(self, value):

        try:
            netaddr.IPNetwork(value)
        except AddrFormatError:
            if not self.regex.match(value):
                raise ValidationError('Not a valid IPv4, IPv6, or Hostname', code='Invalid Format')

    def __eq__(self, other):
        return (
            isinstance(other, FqdnOrIp)
        )


@deconstructible
class Cidr:
    """
    Checks for valid CIDR notation from value. Uses netaddr to do the heavy lifting
    """

    def __init__(self, value):
        self.__call__(value)

    def __call__(self, value):

        if '/' not in value:
            raise ValidationError('Not a valid CIDR', code='Invalid Format')

        try:
            netaddr.IPNetwork(value)
        except AddrFormatError:
            raise ValidationError('Not a valid CIDR', code='Invalid Format')

    def __eq__(self, other):
        return (
            isinstance(other, Cidr)
        )


@deconstructible
class JSONValidator:
    """
    Checks for valid json input
    """

    def __init__(self, value):
        self.__call__(value)

    def __call__(self, value):
        try:
            cleaned = value.replace('\r\n', '')
            json.loads(cleaned)
        except ValueError:
            raise ValidationError('Not valid JSON')

    def __eq__(self, other):
        return (
            isinstance(other, JSONValidator)
        )
