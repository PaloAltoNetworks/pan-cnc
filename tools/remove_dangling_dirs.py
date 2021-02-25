#!/bin/env python3
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

# This script will find all directories found in the 'repositories' directory that are not actually git
# entries. This can happen when a directory cannot be deleted cleanly by the cnc application due to it running
# as a non-privileged user.

import os
import shutil
import sys

app_repo_dir = sys.argv[1]

# basic sanity checks
if not os.path.exists(app_repo_dir):
    print('Refusing to run on non-existent directory')
    sys.exit(1)

# subvert funny business
if not os.path.abspath(app_repo_dir).startswith('/home/cnc_user/.pan_cnc'):
    print('Nice try')
    sys.exit(1)

# now the meat, list each entry in the repositories dir
# verify it's a directory, then verify it has a '.git' subfolder
# if not, then it's a problem and should be removed
for f in os.listdir(app_repo_dir):
    d = os.path.join(app_repo_dir, f)
    if os.path.isdir(d):
        git_dir = os.path.join(d, '.git')
        if not os.path.exists(git_dir):
            print(f'Removing Dangling Repository Directory: {d}')
            shutil.rmtree(d)
