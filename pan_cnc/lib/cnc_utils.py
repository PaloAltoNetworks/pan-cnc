from django.core.cache import cache

import os
import re
import pyAesCrypt
import pickle
import io


def load_user_secrets(user_id, passphrase):

    secret_dir = '/var/tmp/.pan_cnc'
    file_path = os.path.join(secret_dir, user_id)

    buffer_size = 64 * 1024

    secret_input = ''
    with open(file_path, 'rb') as fps:
        secret_input = io.BytesIO(fps.read())

    # initialize decrypted binary stream
    secret_output = io.BytesIO()

    # get ciphertext length
    secret_len = len(secret_input.getvalue())

    # go back to the start of the ciphertext stream
    secret_input.seek(0)

    try:
        # decrypt stream
        pyAesCrypt.decryptStream(secret_input, secret_output, passphrase, buffer_size, secret_len)
    except ValueError as ve:
        print(ve)
        print('Incorrect Passphrase')
        return None

    # print decrypted data
    secret_pickle = secret_output.getvalue()
    secret_dict = pickle.loads(secret_pickle)
    return secret_dict


def save_user_secrets(user_id, secret_dict, passphrase):

    secret_dir = '/var/tmp/.pan_cnc'
    if not os.path.isdir(secret_dir):
        os.mkdir(secret_dir)

    file_path = os.path.join(secret_dir, user_id)
    print(secret_dict)
    pickled_data = pickle.dumps(secret_dict)
    print(pickled_data)
    buffer_size = 64 * 1024

    # input plaintext binary stream
    secret_input_stream = io.BytesIO(pickled_data)

    # initialize ciphertext binary stream
    secret_output_stream = io.BytesIO()

    # encrypt stream
    pyAesCrypt.encryptStream(secret_input_stream, secret_output_stream, passphrase, buffer_size)

    encrypted_stuff = secret_output_stream.getvalue()
    secret_output_stream.seek(0)

    with open(file_path, 'wb+') as fps:
        fps.write(secret_output_stream.getvalue())

    return None


def get_config_value(config_key, default=None):

    config_val = os.environ.get(config_key, '')
    if config_val != '':
        return config_val

    if cache.get('panrc') is None:
        config = load_panrc()
    else:
        config = cache.get('panrc')

    if config_key in config:
        return config[config_key]
    else:
        return default


def load_panrc():
    try:
        path = os.path.expanduser('~')
        rc_filepath = os.path.join(path, '.panrc')
        config = dict()
        with open(rc_filepath, 'r') as rcf:
            rcs = rcf.read()
            for line in rcs.split('\n'):
                if not re.match(r'^\s*$', line) and not re.match(r'^#', line):
                    (k, v) = map(str.strip, line.split('='))
                    cleaned_k = str(k).replace('"', '')
                    cleaned_v = str(v).replace('"', '')
                    print('setting config to %s: %s' % (cleaned_k, cleaned_v))
                    config[cleaned_k] = cleaned_v

            cache.set('panrc', config)
            return config

    except Exception as msg:
        print(msg)


def get_cached_value(key):
    return cache.get(key)


def set_cached_value(key, val):
    cache.set(key, val)