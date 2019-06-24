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
import os
import subprocess
from subprocess import Popen

from celery import current_task
from celery import shared_task


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
                                             cwd=cwd, env=env)

    print(f'Spawned process {p.pid}')
    o.add_metadata(f'CNC: Spawned Process: {p.pid}\n')
    # ensure we always have at least some output while in progress
    current_task.update_state(state='PROGRESS', meta=o.get_progress())

    while True:
        line = await p.stdout.readline()
        if line == b'':
            break

        try:
            o.add_output(line.decode())
            current_task.update_state(state='PROGRESS', meta=o.get_progress())
        except UnicodeDecodeError as ude:
            print(f'Could not read results from task')
            print(ude)
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

    o = OutputHolder()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    r = loop.run_until_complete(cmd_runner(cmd_seq, cwd, process_env, o))
    loop.stop()
    print(f'Task {current_task.request.id} return code is {r}')
    state = dict()
    state['returncode'] = r

    # clean out CNC related informational messages
    # We need to communicate back some information such as spawned process id, but we don't
    # need to show these to the user after task completion, so filter them out here
    # FIXME - there should be a better way to do this?

    print('returning output')
    state['out'] = o.get_output()
    state['err'] = ''
    return json.dumps(state)


def exec_sync_local_task(cmd_seq: list, cwd: str, env=None) -> str:
    """
    Execute local Task in a subprocess thread. Capture stdout and stderr together
    and update the task after the task is done. This should only be used for things we know will happen very fast
    :param cmd_seq: Command to run and all it's arguments
    :param cwd: working directory in which to start the command
    :param env: dict of env variables where k,v == env var name, env var value
    :return: JSON encoded string - dict containing the following keys: returncode, out, err
    """
    print(f'Executing new task  with id: {current_task.request.id}')

    process_env = os.environ.copy()
    if env is not None and type(env) is dict:
        process_env.update(env)

    p = Popen(cmd_seq, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True,
              env=process_env, shell=False)
    stdout, stderr = p.communicate()
    rc = p.returncode
    print(f'Task {current_task.request.id} return code is {rc}')
    state = dict()
    state['returncode'] = rc
    state['out'] = stdout
    state['err'] = stderr
    return json.dumps(state)


@shared_task
def terraform_validate(terraform_dir, tf_vars):
    print('Executing task terraform validate')
    cmd_seq = ['terraform', 'validate', '-no-color']

    env = dict()
    for k, v in tf_vars.items():
        env[f'TF_VAR_{k}'] = v

    return exec_local_task(cmd_seq, terraform_dir, env)


@shared_task
def terraform_init(terraform_dir, tf_vars):
    print('Executing task terraform init')
    cmd_seq = ['terraform', 'init', '-no-color']

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_plan(terraform_dir, tf_vars):
    print('Executing task terraform plan')
    cmd_seq = ['terraform', 'plan', '-no-color', '-out=.cnc_plan']
    env = dict()
    for k, v in tf_vars.items():
        env[f'TF_VAR_{k}'] = v

    return exec_local_task(cmd_seq, terraform_dir, env)


@shared_task
def terraform_apply(terraform_dir, tf_vars):
    print('Executing task terraform apply')
    cmd_seq = ['terraform', 'apply', '-no-color', '-auto-approve', './.cnc_plan']
    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_output(terraform_dir, tf_vars):
    print('Executing task terraform output')
    cmd_seq = ['terraform', 'output', '-no-color', '-json']
    return exec_sync_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_destroy(terraform_dir, tf_vars):
    print('Executing task terraform destroy')
    cmd_seq = ['terraform', 'destroy', '-no-color', '-auto-approve']
    env = dict()
    for k, v in tf_vars.items():
        env[f'TF_VAR_{k}'] = v

    return exec_local_task(cmd_seq, terraform_dir, env)


@shared_task
def terraform_refresh(terraform_dir, tf_vars):
    print('Executing task terraform status')
    cmd_seq = ['terraform', 'refresh', '-no-color']
    env = dict()
    for k, v in tf_vars.items():
        env[f'TF_VAR_{k}'] = v

    return exec_local_task(cmd_seq, terraform_dir, env)


@shared_task
def python3_init_env(working_dir):
    print('Executing task Python3 init')
    cmd_seq = ['python3', '-m', 'virtualenv', f'{working_dir}/.venv']
    env = dict()
    env['PYTHONUNBUFFERED'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_init_with_deps(working_dir, tools_dir):
    print('Executing task Python3 init with Dependencies')
    cmd_seq = [f'{tools_dir}/init_virtual_env.sh', working_dir]
    env = dict()
    env['PYTHONUNBUFFERED'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_init_existing(working_dir):
    print('Executing task Python3 init with Dependencies')
    cmd_seq = [f'{working_dir}/.venv/bin/pip3', 'install', '--upgrade', '-r', 'requirements.txt']
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

    for k, v in args.items():
        if type(v) is list:
            val = ",".join(v)
        else:
            val = v
        if input_type == 'env':
            env[k] = val
        else:
            cmd_seq.append(f'--{k}={val}')

    print(cmd_seq)
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_execute_bare_script(working_dir, script, input_type, args):
    print(f'Executing task Python3 {script}')
    cmd_seq = ['python3', '-u', script]

    env = dict()
    env['PYTHONUNBUFFERED'] = "1"

    for k, v in args.items():
        if type(v) is list:
            val = ",".join(v)
        else:
            val = v
        if input_type == 'env':
            env[k] = val
        else:
            cmd_seq.append(f'--{k}={val}')

    return exec_local_task(cmd_seq, working_dir, env)
