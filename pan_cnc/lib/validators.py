from django.core.validators import RegexValidator
import re


class HostTypeValidator(RegexValidator):

    ul = '\u00a1-\uffff'  # unicode letters range (must not be a raw string)
    # IP patterns
    ipv4_re = r'(?:25[0-5]|2[0-4]\d|[0-1]?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}'
    ipv6_re = r'\[[0-9a-f:\.]+\]'  # (simple regex, validated later)
    # Host patterns
    hostname_re = r'[a-z' + ul + r'0-9](?:[a-z' + ul + r'0-9-]{0,61}[a-z' + ul + r'0-9])?'
    regex = re.compile('(?:' + ipv4_re + '|' + ipv6_re + '|' + hostname_re + ')', re.IGNORECASE)
    message = 'Enter a valid Hostname or IP Address.'
