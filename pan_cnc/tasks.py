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

"""
Palo Alto Networks pan-cnc

pan-cnc is a library to build simple GUIs and workflows primarily to interact with various APIs

Please see http://github.com/PaloAltoNetworks/pan-cnc for more information

This software is provided without support, warranty, or guarantee.
Use at your own risk.
"""

import asyncio
import json
import logging
import os
from asyncio import LimitOverrunError

from celery import current_task
from celery import shared_task
from skilletlib import SkilletLoader
from skilletlib.exceptions import SkilletLoaderException

from pan_cnc.tasklibs.docker_utils import DockerHelper
from pan_cnc.tasklibs.docker_utils import DockerHelperException

logger = logging.getLogger(__name__)


class OutputHolder(object):
    """
    Simple class to hold output for our tasks
    """
    full_output = ''
    metadata = ''

    def __init__(self):
        self.full_output = ''
        self.metadata = ''

    def add_metadata(self, message):
        self.metadata += message

    def add_output(self, message):
        self.full_output += message

    def get_output(self):
        return self.full_output

    def get_progress(self):
        return self.metadata + self.full_output


async def cmd_runner(cmd_seq: list, cwd: str, env: dict, o: OutputHolder) -> int:
    """
    This function will get called within our tasks to execute subprocesses using asyncio
    :param cmd_seq: command to execute
    :param cwd: current working dir
    :param env: dict containing the environment variables to pass along
    :param o: reference to out OutputHolder class
    :return: int return code once the command has completed
    """
    p = await asyncio.create_subprocess_exec(cmd_seq[0], *cmd_seq[1:],
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                             cwd=cwd, env=env, limit=524288)

    print(f'Spawned process {p.pid}')
    o.add_metadata(f'CNC: Spawned Process: {p.pid}\n')
    # ensure we always have at least some output while in progress
    current_task.update_state(state='PROGRESS', meta=o.get_progress())

    while True:
        try:
            line = await p.stdout.readline()
            if line == b'':
                break

            o.add_output(line.decode())
            current_task.update_state(state='PROGRESS', meta=o.get_progress())
        except UnicodeDecodeError as ude:
            print('Could not read results from task')
            print(ude)
            return 255
        except LimitOverrunError as loe:
            print('Could not read results from task due to buffer overrun')
            print(loe)
            return 255
        except ValueError as ve:
            print('Could not read output from task, possible buffer overrun')
            print(ve)
            return 255

    await p.wait()
    return p.returncode


def exec_local_task(cmd_seq: list, cwd: str, env=None) -> str:
    """
    This function will kick off our local task calling cmd_runner in a celery worker thread. Uses an event loop
    to track progress
    :param cmd_seq: command sequence to execute
    :param cwd: current working directory
    :param env: dict containing env vars
    :return: str containing the state of the job
    """
    print('Kicking off new task - exe local task')
    process_env = os.environ.copy()
    if env is not None and type(env) is dict:
        process_env.update(env)

    state = dict()
    try:
        o = OutputHolder()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        r = loop.run_until_complete(cmd_runner(cmd_seq, cwd, process_env, o))
        loop.stop()
        print(f'Task {current_task.request.id} return code is {r}')
        state['returncode'] = r
        state['out'] = o.get_output()
        state['err'] = ''
    except OSError as ose:
        print('Caught Error executing task!')
        print(ose)
        state['returncode'] = 666
        state['out'] = str(ose)
        state['err'] = str(ose)

    try:
        print('returning output')
        return json.dumps(state)
    except TypeError as te:
        print('Caught Error Returning Task output!')
        print(te)
        return '{{"returncode": 666, "out": "Error Returning Task Output", "err": "TypeError"}}'


@shared_task
def python3_init_with_deps(working_dir, tools_dir):
    print('Executing task Python3 init with Dependencies')
    cmd_seq = [f'{tools_dir}/init_virtual_env.sh', working_dir]
    env = dict()
    env['PYTHONUNBUFFERED'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_execute_script(working_dir, script, input_type, args):
    """Build python3 cli and environment"""
    print(f'Executing task Python3 {script}')
    cmd_seq = [f'{working_dir}/.venv/bin/python3', '-u', script]

    env = dict()
    env['PYTHONUNBUFFERED'] = "1"
    # https://gitlab.com/panw-gse/as/panhandler/-/issues/44 - ensure PATH and VIRTUALENV are set properly in the env
    orig_path = os.environ.get('PATH', '/usr/bin')
    env['PATH'] = f'{working_dir}/.venv/bin:{orig_path}'
    env['VIRTUAL_ENV'] = f'{working_dir}/.venv'

    sanitized_args = __santize_args(args)

    for k, v in sanitized_args.items():
        if input_type == 'env':
            env[k] = v
        else:
            cmd_seq.append(f'--{k}={v}')

    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_execute_bare_script(working_dir, script, input_type, args):
    print(f'Executing task Python3 {script}')
    cmd_seq = ['python3', '-u', script]

    env = dict()
    env['PYTHONUNBUFFERED'] = "1"

    sanitized_args = __santize_args(args)

    for k, v in sanitized_args.items():
        if input_type == 'env':
            env[k] = v
        else:
            cmd_seq.append(f'--{k}={v}')

    return exec_local_task(cmd_seq, working_dir, env)


def __santize_args(args: dict) -> dict:
    """
    Attempt to sanitize input arguments for things like improper types and Null values. Lists are converted
    to comma separated lists and None type values are converted to ''

    :param args: dictionary of variables from the skillet with values from the user, default values from the skillet
    or values from env secrets
    :return: dictionary on with values sanitized
    """

    sanitized_args = dict()

    for k, v in args.items():
        if type(v) is list:
            # do not try to serialize lists of data objects other than str
            str_list = []

            for list_item in v:
                if type(list_item) is str:
                    str_list.append(list_item)

            val = ",".join(str_list)

        else:
            # Fix of PH#163 - do not allow None types to slip in here
            if v is None:
                val = ''
            else:
                val = v

        sanitized_args[k] = val

    return sanitized_args


@shared_task
def execute_docker_skillet(skillet_def: dict, args: dict) -> str:
    """
    Execute a skillet of type 'docker'. This requires the calling application have access to the
    docker socket

    :param skillet_def: the skillet as loaded from the YAML file (dict)
    :param args: context arguments required for the given skillets. These will overwrite the 'variables' in the
    skillet
    :return: JSON encoded string with dict containing the following keys: {'returncode', 'out', 'err'}
    """
    state = dict()
    full_output = ''
    err = ''
    rc = 0

    docker_helper = DockerHelper()

    if skillet_def['type'] != 'docker' and skillet_def['type'] != 'terraform':
        rc = 255
        err = f'Not a valid skillet type: {skillet_def["type"]}!'

    elif not docker_helper.check_docker_server():
        rc = 240
        err = 'Could not connect to Docker daemon, verify permissions on the docker socket! \n\n' \
              'See the documentation for details: https://panhandler.readthedocs.io/en/master/debugging.html'

    else:
        try:
            persistent_volumes = docker_helper.get_cnc_volumes()

            if 'app_data' not in skillet_def:
                skillet_def['app_data'] = dict()

            # always overwrite any volumes that may have snuck in here
            if persistent_volumes:
                skillet_def['app_data']['volumes'] = persistent_volumes

            else:
                # only this app should be setting app_data/volumes here, remove anything else
                if 'volumes' in skillet_def['app_data']:
                    skillet_def['app_data'].pop('volumes')

            sl = SkilletLoader()
            skillet = sl.create_skillet(skillet_def)

            # FIX for #181
            sanitized_args = __santize_args(args)

            output_generator = skillet.execute_async(sanitized_args)

            for out in output_generator:
                full_output += out
                current_task.update_state(state='PROGRESS', meta=full_output)

            r = skillet.get_results()

            # FIXME - docker skillets can run multiple snippets / cmds inside the container
            # should check for the output of each and determine if a single failure is considered a failure
            # for the entire skillet or only a failure for one step ?
            if isinstance(r, dict) and 'snippets' in r:
                for k, v in r['snippets'].items():
                    result = v.get('results', 'failure')

                    if result == 'success':
                        full_output = v.get('raw', '')
                    elif result == 'error' or 'fail' in result:
                        err = v.get('raw', 'error')
                        rc = 2
                    else:
                        full_output = v.get('raw', '')
                        err = f'Unknown return value type {result}'
                        rc = 3
            else:
                full_output = r
                err = 'unknown output from skillet'

        except DockerHelperException as dee:
            logger.error(dee)
            rc = 1
            err = str(dee)

        except SkilletLoaderException as sle:
            logger.error(sle)
            rc = 1
            err = str(sle)

    state['returncode'] = rc
    state['out'] = full_output
    state['err'] = err

    return json.dumps(state)
