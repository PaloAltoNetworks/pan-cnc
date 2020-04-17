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

import datetime
import subprocess
from pathlib import Path

import requests
import urllib3
from git import GitCommandError
from git import GitError
from git import InvalidGitRepositoryError
from git import NoSuchPathError
from git import Repo
from requests import RequestException

from pan_cnc.lib import cnc_utils
from pan_cnc.lib.exceptions import ImportRepositoryException

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
            if flags == 4:
                print("Already up to date")
                return False
            elif flags == 64:
                print("Updated to Latest")
                return True
            else:
                print("Unknown flag returned")
                return False

        repo.close()
        return True
    except NoSuchPathError:
        print('Directory does not exist')
        return False

    except InvalidGitRepositoryError:
        # this is not yet a git repo, let's try to clone it
        print(f'Cloning new repo with name {repo_name}')
        return clone_repo(repo_dir, repo_name, repo_url, branch)
    except GitCommandError as gce:
        print(gce)
        return False
    except GitError as ge:
        print(ge)
        return False


def clone_repo(repo_dir, repo_name, repo_url, branch='master'):
    """
    Wrapper for clone_repository for old clone_repo func which only returned bool
    :param repo_dir: dir to clone the repo into
    :param repo_name: name of the repo to use for reporting
    :param repo_url: url of the upstream repo
    :param branch: branch to clone from
    :return: bool
    """
    try:
        message = clone_repository(repo_dir, repo_name, repo_url, branch)
        print(message)
        return True
    except ImportRepositoryException as ire:
        print(ire)
        return False


def clone_repository(repo_dir, repo_name, repo_url, branch='master'):
    """
    Clone the given repository into the given directory name
    :param repo_dir:
    :param repo_name:
    :param repo_url:
    :param branch:
    :return:
    """
    try:
        print(f'Cloning {repo_name}')
        # bugfix/workaround for issue #23
        env = dict()
        if 'http' in repo_url:
            true_binary = subprocess.check_output("which true", shell=True)
            true_binary_path = true_binary.decode('utf-8').strip()
            print(f'USING fake ASKPASS of {true_binary_path}')
            env['GIT_ASKPASS'] = true_binary_path

        # remove depth option to allow us to query remote branches
        Repo.clone_from(repo_url, repo_dir, env=env, config='http.sslVerify=false')
    except (GitCommandError, GitError) as gce:
        raise ImportRepositoryException(gce)

    return "Imported repository successfully"


def get_repo_details(repo_name, repo_dir, app_name='cnc'):
    """
    Fetch the details for a given repo name and directory

    :param repo_name:
    :param repo_dir:
    :param app_name: name of the CNC application
    :return:
    """

    repo_detail = cnc_utils.get_long_term_cached_value(app_name, f'{repo_name}_detail')
    if repo_detail:
        return repo_detail

    repo_detail = dict()
    repo_detail['name'] = repo_name

    try:

        repo = Repo(repo_dir)

    except NoSuchPathError as nspe:
        print(f'Repository directory {repo_dir} does not actually exist!')
        print(nspe)
        repo_detail['error'] = 'Repository directory could not be found!'
        return repo_detail
    except GitError as ge:
        print(ge)
        repo_detail['error'] = 'Git Repository Error!'
        return repo_detail

    # Fix for PH #172
    if not hasattr(repo.remotes, 'origin'):
        repo_detail['error'] = 'Git Repository Error! No origin set!'
        return repo_detail

    url = str(repo.remotes.origin.url)
    url_details = parse_repo_origin_url(url)

    is_github = False
    if 'github' in url:
        link = f"https://github.com/{url_details['owner']}/{url_details['repo']}"
        is_github = True
    elif 'spring.palo' in url:
        link = f"https://spring.paloaltonetworks.com/{url_details['owner']}/{url_details['repo']}"
    else:
        link = url

    if 'repo' not in url_details or url_details['repo'] is None or url_details['repo'] == '':
        url_details['repo'] = repo_name

    branch = 'master'
    commit_log = list()
    last_updated = 0
    last_updated_str = ''

    repo_detail['label'] = url_details['repo']
    repo_detail['link'] = link
    repo_detail['dir'] = repo_name
    repo_detail['url'] = url
    repo_detail['branch'] = branch
    repo_detail['commits_url'] = get_repo_commits_url(url)

    repo_detail['is_github'] = is_github

    try:
        branch = repo.active_branch.name
        commits = repo.iter_commits(branch, max_count=5)

        # fix for #182 - do not lose track of current branch
        repo_detail['branch'] = branch

        for c in commits:
            commit_detail = dict()
            timestamp = datetime.datetime.fromtimestamp(c.committed_date)
            commit_detail['time'] = timestamp.strftime('%Y-%m-%d %H:%M')
            commit_detail['author'] = c.author.name
            commit_detail['message'] = c.message
            commit_detail['id'] = str(c)
            commit_log.append(commit_detail)

            if c.committed_date > last_updated:
                last_updated = c.committed_date
                last_updated_str = commit_detail['time']

    except GitCommandError as gce:
        print('Could not get commits from repo')
        print(gce)
        # partial fix for PH #171 - bail out when issues getting git details here to avoid hang
        repo_detail['error'] = 'Could not fetch commit history for repo!'
        return repo_detail

    except GitError as ge:
        print('Unknown GitError')
        print(ge)
        repo_detail['error'] = 'Unknown Git error getting history for repo!'
        return repo_detail

    branches = __get_repo_branches(repo)

    repo_detail['branches'] = branches
    repo_detail['commits'] = commit_log
    repo_detail['last_updated'] = last_updated_str
    repo_detail['last_updated_time'] = last_updated

    upstream_details = get_repo_upstream_details(repo_name, url, app_name)
    if 'description' in upstream_details:
        if upstream_details['description'] is None or upstream_details['description'] == 'None':
            repo_detail['description'] = f"{url} {branch}"
        else:
            repo_detail['description'] = upstream_details['description']
    else:
        repo_detail['description'] = branch

    cnc_utils.set_long_term_cached_value(app_name, f'{repo_name}_detail', repo_detail, 604800, 'git_repo_details')
    return repo_detail


def update_repo(repo_dir: str, branch=None):
    """
    Pull the latest updates from a repository
    :param repo_dir: directory of repo to update
    :param branch: branch to switch to before update
    :return:
    """
    repo_path = Path(repo_dir)

    if not repo_path.exists():
        return 'Error: Path does not exist'

    try:
        repo = Repo(repo_dir)

        changes = repo.index.diff(None)
        if len(changes) > 0:
            print('There are local changes that may get lost if we update!')

        checkout = False
        if branch is not None:
            current_branch = repo.active_branch.name
            if branch != current_branch:
                print(f'Checking out new branch: {branch}')
                checkout = True
                repo.git.checkout(branch)

        f = repo.remotes.origin.pull()

    except GitCommandError as gce:
        print(gce)
        return 'Error: Could not update! Ensure there are no local changes before updating'

    except InvalidGitRepositoryError as igre:
        print(igre)
        return 'Error: Could not update! Invalid git repository directory'

    except NoSuchPathError as nspe:
        print(nspe)
        return 'Error: Could not update, repository directory could not be found'

    except GitError as ge:
        print(ge)
        return 'Error: Could not update, Unknown error with git repository'

    if checkout:
        return f"Checked out new Branch: {branch}"

    if len(f) > 0:
        flags = f[0].flags
        if flags == 4:
            return "This branch is already up to date"
        elif flags == 64:
            return "This branch has been updated to Latest"
        else:
            return "Error: Unknown flag returned"

    return "Unknown Error"


def get_repo_branches_from_dir(repo_dir: str) -> list:

    repo = Repo(repo_dir)
    try:
        g = repo.git
        fc = g.config(['--get',  'remote.origin.fetch'])
        if fc != '+refs/heads/*:refs/remotes/origin/*':
            print('updating from shallow repo')
            g.config(['remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*'])

    except GitCommandError as gce:
        print(gce)
    except GitError as ge:
        print(ge)

    return __get_repo_branches(repo)


def __get_repo_branches(repo: Repo) -> list:
    """
    Returns a list of branches for the given Git Repo object
    :param repo: Git Repo object
    :return: list of branch names available
    """

    # keep a list of branches
    branches = list()

    # always keep at least the current active branch
    branch = repo.active_branch.name
    branches.append(branch)

    try:
        # fix for PH: #130 - deleted branches continue to show up in ph after upstream branch deleted
        repo.git.fetch(all=True, prune=True)

        raw_branches = repo.git.branch('-r')
        # branches will be raw output from git command like:
        # '  origin/HEAD -> origin/master\n  origin/develop\n  origin/master\n'
        remote_name = repo.remote().name
        # clean up the output into a list
        for b in raw_branches.split('\n'):
            if '->' in b:
                # skip line that shows currently tracked branch, we don't need that here
                continue
            parsed_branch = b.replace(remote_name + '/', '').strip()
            if parsed_branch not in branches:
                branches.append(parsed_branch)

    except GitCommandError as gce:
        print('Could not get branches from repo')
        print(gce)
    except GitError as ge:
        print('Unknown GitError')
        print(ge)
    finally:
        return branches


def get_repo_upstream_details(repo_name: str, repo_url: str, app_name: str) -> dict:
    """
    Attempt to get the details from a git repository. Details are found via specific APIs for each type of git repo.
    Currently only Github is supported.
    :param repo_name:
    :param repo_url:
    :param app_name: cnc application name
    :return:
    """

    details = dict()

    if cnc_utils.is_testing():
        return details

    cache_repo_name = repo_name.replace(' ', '_')
    cached_details = cnc_utils.get_long_term_cached_value(app_name, f'git_utils_upstream_{cache_repo_name}')
    # fix for issue #70, details will be None after cache miss, use a new var name to keep details as a dict
    if cached_details is not None:
        return cached_details

    api_throttle_active = cnc_utils.get_long_term_cached_value(app_name, f'git_utils_api_throttle')
    if api_throttle_active:
        print('Skipping get_repo_upstream_details due to availability')
        return details

    print('Not found in cache, loading from upstream')
    url_details = parse_repo_origin_url(repo_url)
    owner = url_details.get('owner', '')
    repo = url_details.get('repo', '')

    try:
        api_url = f'https://api.github.com/repos/{owner}/{repo}'
        # fix for issue #70, increase timeout to 30 seconds
        detail_response = requests.get(api_url, verify=False, timeout=30)
        if detail_response.status_code != 200:
            print(f'response was {detail_response.status_code}, disabling upstream api queries')
            cnc_utils.set_long_term_cached_value(app_name, 'git_utils_api_throttle', True, 3601,
                                                 'git_repo_details')
            return details

        details = detail_response.json()
        # fix for issue #70, cache this value for 3 days instead of 1
        cnc_utils.set_long_term_cached_value(app_name, f'git_utils_upstream_{cache_repo_name}', details, 259200,
                                             'git_repo_details')
    except ConnectionResetError as cre:
        print('Could not get github details due to ConnectionResetError')
        print(cre)
        api_throttle_active = True
    except RequestException as ce:
        print('Could not get github details due to RequestException')
        print(ce)
        api_throttle_active = True
    except Exception as e:
        print(type(e))
        print(e)
        api_throttle_active = True

    if api_throttle_active:
        print(f'Disabling upstream api queries for 1 hour')
        cnc_utils.set_long_term_cached_value(app_name, 'git_utils_api_throttle', True, 3601,
                                             'git_repo_details')
    return details


def get_repo_commits_url(repo_url):
    url_details = parse_repo_origin_url(repo_url)
    owner = url_details.get('owner', '')
    repo = url_details.get('repo', '')

    return f'https://github.com/{owner}/{repo}/commit/'


def parse_repo_origin_url(repo_url):
    url_details = dict()

    try:
        if repo_url.endswith('.git') and repo_url.startswith('git@'):
            # git@github.com:nembery/Skillets.git
            url_parts = repo_url.split(':')[1].split('/')
            owner = url_parts[0]
            repo = url_parts[1].split('.git')[0]
        elif repo_url.endswith('.git'):
            # https://github.com/owner/repo.git
            url_parts = repo_url.split('/')[-2:]
            owner = url_parts[0]
            repo = url_parts[1].split('.git')[0]
        elif repo_url.endswith('/'):
            # https://github.com/owner/repo/
            url_parts = repo_url.split('/')[-3:]
            owner = url_parts[0]
            repo = url_parts[1].split('.git')[0]
        else:
            # https://github.com/owner/repo ?
            url_parts = repo_url.split('/')[-2:]
            owner = url_parts[0]
            repo = url_parts[1].split('.git')[0]
    except IndexError:
        print('Could not parse repo url!')
        owner = None
        repo = None

    url_details['owner'] = owner
    url_details['repo'] = repo

    return url_details


def update_repo_in_cache(repo_name: str, repo_dir: str, app_dir: str) -> None:
    """
    Updates a single repo_details dict in the imported_repos cached list
    :param repo_name: name of the repo to update
    :param repo_dir: dir of the repo to update
    :param app_dir: current application
    :return: None
    """
    cnc_utils.set_long_term_cached_value(app_dir, f'{repo_name}_detail', None, 0, 'git_repo_details')

    # get updated repo_details
    updated_repo_details = get_repo_details(repo_name, repo_dir, app_dir)

    # now, find and remove the old details
    repos = cnc_utils.get_long_term_cached_value(app_dir, 'imported_repositories')

    # fix for crash when long term cached values may be blank or None
    if repos is not None:
        for r in repos:
            if r.get('name', '') == repo_name:
                repos.remove(r)
                break
    else:
        repos = list()

    # add our new repo details and re-cache
    repos.append(updated_repo_details)
    cnc_utils.set_long_term_cached_value(app_dir, 'imported_repositories', repos, 604800,
                                         'imported_git_repos')