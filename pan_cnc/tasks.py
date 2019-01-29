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

from celery import shared_task
import time
import json
from subprocess import Popen, PIPE


@shared_task
def test(count: int) -> str:
    i = 0
    while i < count:
        print(f'{i}')
        time.sleep(0.1)
        i = i + 1

    return f'Counted up to {count}'


def exec_local_task(cmd_seq, cwd):
    p = Popen(cmd_seq, cwd=cwd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    o, e = p.communicate()
    state = dict()
    state['returncode'] = p.returncode
    state['out'] = o
    state['err'] = e
    return json.dumps(state)


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
    cmd_seq = ['terraform', 'plan', '-no-color']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

    return exec_local_task(cmd_seq, terraform_dir)


@shared_task
def terraform_apply(terraform_dir, tf_vars):
    print('Executing task terraform apply')
    cmd_seq = ['terraform', 'apply', '-no-color', '-auto-approve']
    for k, v in tf_vars.items():
        cmd_seq.append('-var')
        cmd_seq.append(f'{k}={v}')

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
