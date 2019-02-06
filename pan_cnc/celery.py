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

from __future__ import absolute_import, unicode_literals
from celery import Celery
import os
import sys

# play some tricks with the src path, as we don't always know what apps will be avialable here
SITE_PATH = os.path.abspath(os.path.dirname(__file__))
PROJECT_PATH = os.path.normpath(os.path.join(SITE_PATH, '..', '..'))
SRC_PATH = os.path.join(PROJECT_PATH, 'src')

# add the src path to the system module search path
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

cnc_apps = list()
for d in os.listdir(SRC_PATH):
    print(f'Adding package {d} to celery')
    cnc_apps.append(d)

__broker_inout = '/tmp/celery'
__broker_processed = '/tmp/celery_processed'
__backend_results = '/tmp/celery_results'

if not os.path.exists(__broker_inout):
    os.makedirs(__broker_inout)

if not os.path.exists(__broker_processed):
    os.makedirs(__broker_processed)

if not os.path.exists(__backend_results):
    os.makedirs(__backend_results)

app = Celery('pan_cnc', backend=f'file://{__backend_results}')
app.conf.update({
    'broker_url': 'filesystem://',
    'backend': 'filesystem://',
    'broker_transport_options': {
        'data_folder_in': __broker_inout,
        'data_folder_out': __broker_inout,
        'data_folder_processed': __broker_processed
    },
    'imports': ('pan_cnc.tasks',),
    'result_persistent': True,
    'task_serializer': 'json',
    'result_serializer': 'json',
    'accept_content': ['json']})

app.autodiscover_tasks(cnc_apps)
