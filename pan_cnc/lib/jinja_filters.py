from passlib.hash import md5_crypt
from passlib.hash import des_crypt
from passlib.hash import sha512_crypt
from base64 import urlsafe_b64decode, urlsafe_b64encode

defined_filters = ['md5_hash', 'des_hash', 'sha512_hash', 'b64encode', 'b64decode']


def md5_hash(txt):
    return md5_crypt.hash(txt)


def des_hash(txt):
    return des_crypt.hash(txt)


def sha512_hash(txt):
    return sha512_crypt.hash(txt)


def b64encode(txt):
    return urlsafe_b64encode(txt)


def b64decode(txt):
    return urlsafe_b64decode(txt)