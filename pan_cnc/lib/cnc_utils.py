# Copyright (c) 2018, Palo Alto Networks
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Author: Nathan Embery nembery@paloaltonetworks.com

import io
import os
import pickle
import re
from pathlib import Path

import pyAesCrypt
from django.core.cache import cache
from django.conf import settings
from pan_cnc.lib import git_utils


def check_user_secret(user_id):
    secret_dir = os.path.expanduser('~/.pan_cnc')
    file_path = os.path.join(secret_dir, user_id)
    if not os.path.exists(file_path):
        return False

    return True


def create_environment(name, description, secrets):
    env = dict()
    env['meta'] = dict()
    env['meta']['description'] = description
    env['meta']['name'] = name
    env['secrets'] = secrets
    return env


def init_environment(name, description, secrets):
    secret_dict = dict()
    secret_dict[name] = create_environment(name, description, secrets)
    return secret_dict


def create_new_user_environment_set(user_id, passphrase):
    secret_dict = dict()
    secret_dict['Local Panorama'] = create_environment('Local Panorama',
                                                       'PaloAltoNetworks Panorama',
                                                       {
                                                           'TARGET_IP': '192.168.55.7',
                                                           'TARGET_USERNAME': 'admin',
                                                           'TARGET_PASSWORD': 'admin',
                                                       })

    secret_dict['Local PAN-OS'] = create_environment('Local VM-Series PAN-OS',
                                                     'PaloAltoNetworks PAN-OS VM50',
                                                     {
                                                         'TARGET_IP': '192.168.55.10',
                                                         'TARGET_USERNAME': 'admin',
                                                         'TARGET_PASSWORD': 'admin',
                                                     })

    return save_user_secrets(user_id, secret_dict, passphrase)


def load_user_secrets(user_id, passphrase):
    secret_dir = os.path.expanduser('~/.pan_cnc')
    file_path = os.path.join(secret_dir, user_id)

    buffer_size = 64 * 1024

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
    secret_dir = os.path.expanduser('~/.pan_cnc')
    if not os.path.isdir(secret_dir):
        os.mkdir(secret_dir)

    try:
        file_path = os.path.join(secret_dir, user_id)
        pickled_data = pickle.dumps(secret_dict)
        buffer_size = 64 * 1024

        # input plaintext binary stream
        secret_input_stream = io.BytesIO(pickled_data)

        # initialize ciphertext binary stream
        secret_output_stream = io.BytesIO()

        # encrypt stream
        pyAesCrypt.encryptStream(secret_input_stream, secret_output_stream, passphrase, buffer_size)
        secret_output_stream.seek(0)

        with open(file_path, 'wb+') as fps:
            fps.write(secret_output_stream.getvalue())
    except OSError as ose:
        print('Caught Error saving user secrets!')
        return False
    except BaseException as be:
        print('Caught Error saving user secrets!')
        return False

    return True


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

    config = dict()
    try:
        path = os.path.expanduser('~')
        rc_filepath = os.path.join(path, '.panrc')

        if not os.path.exists(rc_filepath):
            return config

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
        return config


def get_cached_value(key):
    return cache.get(key, None)


def set_cached_value(key, val):
    cache.set(key, val)


def init_app(app_cnc_config):
    if 'repositories' not in app_cnc_config:
        return None

    if 'app_dir' not in app_cnc_config:
        print('Invalid app_dir in app_cnc_configuration')
        return None

    for r in app_cnc_config['repositories']:
        if 'destination_directory' not in r:
            print('Invalid repository app_cnc_configuration')
            continue

        repo_dir = os.path.join(app_cnc_config['app_dir'], 'snippets', r['destination_directory'])
        repo_path = Path(repo_dir)
        app_dir_path = Path(app_cnc_config['app_dir'])
        if app_dir_path not in repo_path.parents:
            print('Will not allow destination directory to be outside of our application dir')
            continue

        if not os.path.exists(repo_dir):
            try:
                os.makedirs(repo_dir)
            except IOError:
                print('Could not make repo_dir!')
                continue

        repo_url = r['url']
        repo_name = r['name']
        repo_branch = r['branch']
        print(f'Pulling / Refreshing repository: {repo_url}')
        git_utils.clone_or_update_repo(repo_dir, repo_name, repo_url, repo_branch)

    return None


def get_app_config(app_name):
    """
    Return the app configuration dict (pan-cnc) or None if app by app_name is not found / loaded
    :param app_name: name of the app to load. This should match the 'name' attribute in the pan-cnc file
    :return: dict containing app_config or None if not found
    """
    if app_name in settings.INSTALLED_APPS_CONFIG:
        return settings.INSTALLED_APPS_CONFIG[app_name]

    print('Could not load app_config')
    return None


def is_testing() -> bool:
    """
    Check for an environment variable that determines if we are in test mode
    :return: bool
    """
    if os.environ.get('CNC_TEST', '') == 'TRUE':
        return True
    else:
        print(os.environ)
        return False
