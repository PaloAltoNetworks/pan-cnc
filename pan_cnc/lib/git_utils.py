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

import requests
import urllib3
from git import InvalidGitRepositoryError, NoSuchPathError, GitCommandError
from git import Repo
from requests import ConnectionError

from pan_cnc.lib import cnc_utils

urllib3.disable_warnings()


def clone_or_update_repo(repo_dir, repo_name, repo_url, branch='master'):
    """
    Clone a repository if it does not exist OR update it if it does
    :param repo_dir: dir where the repo should live
    :param repo_name: name of the repo
    :param repo_url: url from which to clone or update the repo
    :param branch: which branch to checkout
    :return:  boolean
    """
    try:

        repo = Repo(repo_dir)
        f = repo.remotes.origin.pull()
        if len(f) > 0:
            flags = f[0].flags
            print(f'Updated repo with return: {flags}')
        return True
    except NoSuchPathError as nspe:
        print('Directory does not exist')
        return False

    except InvalidGitRepositoryError as igre:
        # this is not yet a git repo, let's try to clone it
        return clone_repo(repo_dir, repo_name, repo_url, branch)
    except GitCommandError as gce:
        print(gce)
        return False


def clone_repo(repo_dir, repo_name, repo_url, branch='master'):
    """
    Clone the given repository into the given directory name
    :param repo_dir:
    :param repo_name:
    :param repo_url:
    :param branch:
    :return:
    """
    try:
        repo = Repo.clone_from(repo_url, repo_dir, depth=3, branch=branch, config='http.sslVerify=false')
    except GitCommandError as gce:
        print(gce)
        return False

    return True


def get_repo_details(repo_name, repo_dir):
    """
    Fetch the details for a given repo name and directory
    :param repo_name:
    :param repo_dir:
    :return:
    """
    repo = Repo(repo_dir)

    url = repo.remotes.origin.url
    branch = repo.active_branch.name
    commits = repo.iter_commits(branch, max_count=5)

    commit_log = list()
    for c in commits:
        commit_detail = dict()
        commit_detail['time'] = str(c.committed_datetime)
        commit_detail['author'] = c.author.name
        commit_detail['message'] = c.message
        commit_detail['id'] = str(c)
        commit_log.append(commit_detail)

    repo_detail = dict()
    repo_detail['name'] = repo_name
    repo_detail['url'] = url
    repo_detail['branch'] = branch
    repo_detail['commits'] = commit_log
    repo_detail['commits_url'] = get_repo_commits_url(url)

    upstream_details = get_repo_upstream_details(repo_name, url)
    if 'description' in upstream_details:
        repo_detail['description'] = upstream_details['description']
    else:
        repo_detail['description'] = branch

    return repo_detail


def update_repo(repo_dir):
    """
    Pull the latest updates from a repository
    :param repo_dir:
    :return:
    """
    repo = Repo(repo_dir)
    # FIXME - ensure we catch errors here
    f = repo.remotes.origin.pull()
    if len(f) > 0:
        flags = f[0].flags
        if flags == 4:
            return "Already up to date"
        elif flags == 64:
            return "Updated to Latest"
        else:
            return "Error: Unknown flag returned"

    return "Unknown Error"


def get_repo_upstream_details(repo_name, repo_url):
    """
    Attempt to get the details from a git repository. Details are found via specific APIs for each type of git repo.
    Currently only Github is supported.
    :param repo_name:
    :param repo_url:
    :return:
    """
    details = cnc_utils.get_cached_value(f'git_utils_upstream_{repo_name}')
    if details is not None:
        return details

    details = dict()

    if 'github' in repo_url:
        url_parts = repo_url.split('/')[-2:]
        owner = url_parts[0]
        repo = url_parts[1].split('.git')[0]

        try:
            api_url = f'https://api.github.com/repos/{owner}/{repo}'
            detail_string = requests.get(api_url, verify=False)
            details = detail_string.json()
            cnc_utils.set_cached_value(f'git_utils_upstream_{repo_name}', details)
        except ConnectionResetError as cre:
            print('Could not get github details due to ConnectionResetError')
            print(cre)
        except ConnectionError as ce:
            print('Could not get github details due to ConnectionError')
            print(ce)
            return details
        except Exception as e:
            print(type(e))
            print(e)
            raise

    return details


def get_repo_commits_url(repo_url):
    commits_url = None
    if 'github' in repo_url:
        url_parts = repo_url.split('/')[-2:]
        owner = url_parts[0]
        repo = url_parts[1].split('.git')[0]

        commits_url = f'https://github.com/{owner}/{repo}/commit/'

    return commits_url
