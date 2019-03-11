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

from celery import shared_task, current_task
import time
import json
from subprocess import Popen, PIPE
import os


@shared_task
def test(count: int) -> str:
    i = 0
    while i < count:
        print(f'{i}')
        time.sleep(0.1)
        i = i + 1

    return f'Counted up to {count}'


def exec_local_task(cmd_seq, cwd, env=None):

    print(f'My task id is: {current_task.request.id}')
    process_env = os.environ.copy()
    if env is not None and type(env) is dict:
        process_env.update(env)

    p = Popen(cmd_seq, cwd=cwd, stdout=PIPE, stderr=PIPE, universal_newlines=True, env=process_env)
    o, e = p.communicate()
    state = dict()
    state['returncode'] = p.returncode
    state['out'] = o
    state['err'] = e
    return json.dumps(state)

# def exec_local_task(cmd_seq, cwd, env=None):
#
#     print(f'My task id is: {current_task.request.id}')
#     process_env = os.environ.copy()
#     if env is not None and type(env) is dict:
#         process_env.update(env)
#
#     with Popen(cmd_seq, cwd=cwd, stdout=PIPE, stderr=PIPE, bufsize=1, universal_newlines=True, env=process_env) as p:
#         full_output = ''
#         for line in p.stdout:
#             full_output = full_output + line
#             print('Updating progress')
#             current_task.update_state(state='PROGRESS', meta=full_output)
#
#     rc = p.returncode
#     print(f'RETURN CODE IS {rc}')
#     err = ''
#     if p.returncode != 0:
#         try:
#             err = p.stderr.readlines()
#         except ValueError as ve:
#             print('stderr is already closed!')
#             err = 'Unknown error'
#
#     # o, e = p.communicate()
#     state = dict()
#     state['returncode'] = p.returncode
#     state['out'] = full_output
#     state['err'] = err
#     return json.dumps(state)

@shared_task
def terraform_validate(terraform_dir, tf_vars):
    print('Executing task terraform validate')
    cmd_seq = ['terraform', 'validate', '-no-color']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_init(terraform_dir, tf_vars):
    print('Executing task terraform init')
    cmd_seq = ['terraform', 'init', '-no-color']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_plan(terraform_dir, tf_vars):
    print('Executing task terraform plan')
    cmd_seq = ['terraform', 'plan', '-no-color', '-out=.cnc_plan']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_apply(terraform_dir, tf_vars):
    print('Executing task terraform apply')
    cmd_seq = ['terraform', 'apply', '-no-color', '-auto-approve', './.cnc_plan']
    # for k, v in tf_vars.items():
    #     cmd_seq.append('-var')
    #     cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_output(terraform_dir, tf_vars):
    print('Executing task terraform output')
    cmd_seq = ['terraform', 'output', '-no-color', '-json']
    # for k, v in tf_vars.items():
    #     cmd_seq.append('-var')
    #     cmd_seq.append(f'{k}={v}')
    print(cmd_seq)
    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_destroy(terraform_dir, tf_vars):
    print('Executing task terraform destroy')
    cmd_seq = ['terraform', 'destroy', '-no-color', '-auto-approve']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_refresh(terraform_dir, tf_vars):
    print('Executing task terraform status')
    cmd_seq = ['terraform', 'refresh', '-no-color']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def python3_init_env(working_dir):
    print('Executing task Python3 init')
    cmd_seq = ['pipenv', 'install']
    env = dict()
    env['PIPENV_IGNORE_VIRTUALENVS'] = "1"
    env['PIPENV_VENV_IN_PROJECT'] = "1"
    env['PIPENV_DEFAULT_PYTHON_VERSION'] = "3.6"
    env['PIPENV_NOSPIN'] = "1"
    env['PIPENV_YES'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_init_with_deps(working_dir):
    print('Executing task Python3 init with Dependencies')
    cmd_seq = ['pipenv', 'install', '-r', 'requirements.txt']
    env = dict()
    env['PIPENV_IGNORE_VIRTUALENVS'] = "1"
    env['PIPENV_VENV_IN_PROJECT'] = "1"
    env['PIPENV_DEFAULT_PYTHON_VERSION'] = "3.6"
    env['PIPENV_NOSPIN'] = "1"
    env['PIPENV_YES'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_init_existing(working_dir):
    print('Executing task Python3 init with Dependencies')
    cmd_seq = ['pipenv', 'update', '--bare']
    env = dict()
    env['PIPENV_IGNORE_VIRTUALENVS'] = "1"
    env['PIPENV_VENV_IN_PROJECT'] = "1"
    env['PIPENV_DEFAULT_PYTHON_VERSION'] = "3.6"
    env['PIPENV_NOSPIN'] = "1"
    env['PIPENV_YES'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)


@shared_task
def python3_execute_script(working_dir, script, args):
    print(f'Executing task Python3 {script}')
    cmd_seq = ['pipenv', 'run', 'python3', script]

    for k, v in args.items():
        cmd_seq.append(f'--{k}={v}')

    env = dict()
    env['PIPENV_IGNORE_VIRTUALENVS'] = "1"
    env['PIPENV_VENV_IN_PROJECT'] = "1"
    env['PIPENV_DEFAULT_PYTHON_VERSION'] = "3.6"
    env['PIPENV_NOSPIN'] = "1"
    env['PIPENV_YES'] = "1"
    return exec_local_task(cmd_seq, working_dir, env)

