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
import json
import os
import pickle
import re
from pathlib import Path

import pyAesCrypt
from django.conf import settings
from django.core.cache import cache

from pan_cnc.lib import git_utils
from time import time
from pan_cnc.lib import snippet_utils


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
    except OSError:
        print('Caught Error saving user secrets!')
        return False
    except BaseException:
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

        if os.path.isdir(rc_filepath):
            print('Refusing to load .panrc directory')
            # FIXME - we should properly handle this
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


def _load_long_term_cache(app_name: str) -> None:
    """
    Loads the cache file from the current users $HOME dir/.pan_cnc/app_name/cache
    :param app_name: name of the current CNC application
    :return: None
    """
    path = os.path.expanduser('~')

    cache_dir = os.path.join(path, '.pan_cnc', app_name)

    try:
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, mode=600)
    except OSError as ose:
        print('Could not create application cache dir!')
        print(ose)
        return None

    cache_file = os.path.join(cache_dir, 'cache')
    cache_contents = dict()
    try:
        if not os.path.exists(cache_file):
            with open(cache_file, 'w') as cf:
                cf.write(json.dumps(dict()))

            os.chmod(cache_file, mode=0o600)
            return None

        with open(cache_file, 'r+') as cf:
            cache_contents_str = cf.read()
            cache_contents = json.loads(cache_contents_str)

    except OSError as ose:
        print('Could not open cache file')
        print(ose)

    except ValueError as ve:
        print('Could not load long term cache')
        print(ve)

    # always set something in the in-memory cache, even if it's only a blank dict
    cache.set(f'{app_name}_cache', cache_contents)
    return None


def save_long_term_cache(app_name: str, contents: dict) -> None:
    json_string = json.dumps(contents)

    path = os.path.expanduser('~')
    cache_dir = os.path.join(path, '.pan_cnc', app_name)

    try:
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, mode=600)

        cache_file = os.path.join(cache_dir, 'cache')

        with open(cache_file, 'w+') as cf:
            cf.write(json_string)
    except OSError:
        print('Could not save long term cache')

    return None


def get_long_term_cached_value(app_name: str, key: str) -> any:

    cache_key = f'{app_name}_cache'

    if cache_key not in cache:
        _load_long_term_cache(app_name)

    ltc = cache.get(cache_key, dict())

    if 'meta' not in ltc:
        return None

    if key not in ltc['meta']:
        return None

    now = time()

    if 'time' not in ltc['meta'][key]:
        return None
    if 'life' not in ltc['meta'][key]:
        return None

    time_added = ltc['meta'][key]['time']
    try:
        life = int(ltc['meta'][key]['life'])
    except ValueError:
        print('could not parse life value from cache entry')
        return None

    # Allow -1 to indicate cached items that should stay cached forever
    if life == -1:
        return ltc.get(key, None)

    if (now - time_added) > life:
        print(f'Aging out cache item for {key}')
        return None

    print(f'Cache hit for {key}')
    return ltc.get(key, None)


def set_long_term_cached_value(app_name: str, key: str, value: any, life=3600, cache_type='snippet') -> None:

    cache_key = f'{app_name}_cache'

    if cache_key not in cache:
        _load_long_term_cache(app_name)

    ltc = cache.get(cache_key, dict())

    if key in ltc and value is None:
        ltc.pop(key)
        if 'meta' in ltc and key in ltc['meta']:
            ltc['meta'].pop(key)

    else:
        ltc[key] = value

        # Ensure all meta values are kept around so we can evict items from the cache
        if 'meta' not in ltc:
            ltc['meta'] = dict()

        ltc['meta'][key] = dict()
        ltc['meta'][key]['time'] = time()
        ltc['meta'][key]['life'] = life
        ltc['meta'][key]['cache_type'] = cache_type

    cache.set(cache_key, ltc)

    apps_to_save = cache.get('ltc_dirty', list())

    if type(apps_to_save) is not list:
        apps_to_save = list()

    if app_name not in apps_to_save:
        apps_to_save.append(app_name)

    cache.set('ltc_dirty', apps_to_save)
    # save_long_term_cache(app_name, ltc)
    return None


def clear_long_term_cache(app_name: str) -> None:
    ltc = dict()
    cache_key = f'{app_name}_cache'
    cache.set(cache_key, ltc)

    apps_to_save = cache.get('ltc_dirty', list())

    if type(apps_to_save) is not list:
        apps_to_save = list()

    if app_name not in apps_to_save:
        apps_to_save.append(app_name)

    cache.set('ltc_dirty', apps_to_save)
    # save_long_term_cache(app_name, ltc)
    print('Cleared')
    return None


def evict_cache_items_of_type(app_name, cache_type):
    cache_key = f'{app_name}_cache'

    if cache_key not in cache:
        _load_long_term_cache(app_name)

    ltc = cache.get(cache_key, dict())
    if 'meta' in ltc:
        for key in ltc['meta']:
            if 'cache_type' in ltc['meta'][key]:
                if ltc['meta'][key]['cache_type'] == cache_type:
                    if key in ltc:
                        print(f'Evicting item {key}')
                        set_long_term_cached_value(app_name, key, None, 0, cache_type)


def init_app(app_cnc_config):

    if 'name' not in app_cnc_config:
        print('No name found in app_cnc_config!')
        return None

    app_name = app_cnc_config['name']

    if 'repositories' not in app_cnc_config:
        return None

    if 'app_dir' not in app_cnc_config:
        print('Invalid app_dir in app_cnc_configuration')
        return None

    for r in app_cnc_config['repositories']:
        if 'destination_directory' not in r:
            print('Invalid repository app_cnc_configuration')
            continue

        user_dir = os.path.expanduser('~')
        repo_base_dir = os.path.join(user_dir, '.pan_cnc', app_name, 'repositories')
        repo_dir = os.path.join(repo_base_dir, r['destination_directory'])

        repo_path = Path(repo_dir)
        repo_base_path = Path(repo_base_dir)

        if repo_base_path not in repo_path.parents:
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
        cache_key = f"{repo_dir}_life"
        cached = get_long_term_cached_value(app_name, cache_key)
        if not cached:
            print(f'Pulling / Refreshing repository: {repo_url}')
            if git_utils.clone_or_update_repo(repo_dir, repo_name, repo_url, repo_branch):
                # if we have updated something, then we need to clear the caches
                snippet_utils.invalidate_snippet_caches(app_name)

            # only check for updates every 2 hours at most on app reload
            set_long_term_cached_value(app_name, cache_key, True, 7200, 'imported_repos')

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
        return False
