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
import os
import shlex
import subprocess
import traceback
from pathlib import Path
from typing import Union

import requests
import urllib3
from git import GitCommandError
from git import GitError
from git import InvalidGitRepositoryError
from git import NoSuchPathError
from git import Repo
from paramiko import RSAKey
from requests import RequestException

from pan_cnc.lib import cnc_utils
from pan_cnc.lib.exceptions import ImportRepositoryException
from pan_cnc.lib.exceptions import RepositoryPermissionsException

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
        message = clone_repository(repo_dir, repo_name, repo_url)
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
        if 'Permission denied (publickey)' in str(gce):
            raise RepositoryPermissionsException(str(gce))

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
        commits_url = f"https://github.com/{url_details['owner']}/{url_details['repo']}/commit/"
        is_github = True
    elif 'spring.palo' in url:
        link = f"https://spring.paloaltonetworks.com/{url_details['owner']}/{url_details['repo']}"
        commits_url = f"https://spring.paloaltonetworks.com/{url_details['owner']}/{url_details['repo']}/commit/"
    elif 'gitlab' in url:
        link = f"https://gitlab.com/{url_details['owner']}/{url_details['repo']}"
        commits_url = f"https://gitlab.com/{url_details['owner']}/{url_details['repo']}/-/commit/"
    else:
        link = ''
        commits_url = ''

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
    repo_detail['commits_url'] = commits_url

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

    upstream_details = dict()

    if 'github' in url.lower():
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

    repo = Repo(repo_dir)

    try:

        current_branch = repo.active_branch.name

        changes = repo.index.diff(None)
        if len(changes) > 0:
            print('There are local changes that may get lost if we update!')

        checkout = False
        if branch is not None:
            if branch != current_branch:
                print(f'Checking out new branch: {branch}')
                checkout = True
                repo.git.checkout(branch)

                current_branch = branch

        remote_branches = __get_remote_repo_branches(repo)
        if repo.active_branch.name not in remote_branches:
            if checkout:
                return f"Checked out new Branch: {branch}"
            else:
                return 'Local branch is up to date'

        f = repo.git.pull('origin', current_branch)
        repo.git.submodule('update', '--init')
        repo.submodule_update(recursive=True, init=True, force_reset=True, force_remove=True)

    except GitCommandError as gce:
        print(gce)
        print(traceback.format_exc())

        if 'CONFLICT' in str(gce):
            print('undoing pull')
            repo.git.reset('HEAD', '--hard')
            return 'Error: Could not update! Merge Conflict prevented your changes from being accepted upstream!'

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

    if f == 'Already up to date.':
        return "This branch is already up to date"
    elif str(f).startswith('Updating'):
        return "This branch has been updated to Latest"
    else:
        return f

    # if len(f) > 0:
    #     flags = f[0].flags
    #     if flags == 4:
    #         return "This branch is already up to date"
    #     elif flags == 64:
    #         return "This branch has been updated to Latest"
    #     else:
    #         return "Error: Unknown flag returned"

    # return "Unknown Error"


def get_repo_branches_from_dir(repo_dir: str) -> list:
    repo = Repo(repo_dir)
    try:
        g = repo.git
        fc = g.config(['--get', 'remote.origin.fetch'])
        if fc != '+refs/heads/*:refs/remotes/origin/*':
            print('updating from shallow repo')
            g.config(['remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*'])

    except GitCommandError as gce:
        print(gce)
    except GitError as ge:
        print(ge)

    return __get_repo_branches(repo)


def checkout_local_branch(repo_dir: str, branch_name: str) -> bool:
    """
    Creates a local branch and returns True on success. Checks out local branch
    if it already exists

    :param repo_dir: repo directory in which to create a local branch
    :param branch_name: name of the new branch to create
    :return: boolean
    """

    try:
        repo = Repo(repo_dir)
        g = repo.git

        local_branches = repo.git.branch("--format=%(refname:short)")
        if branch_name in local_branches:
            g.checkout(branch_name)
            print(f'Switched to branch {branch_name}')
        else:
            new_branch = g.checkout('HEAD', b=branch_name)
            print(f'checked out new branch {new_branch}')

    except GitCommandError as gce:
        print(gce)
    except GitError as ge:
        print(ge)


def commit_local_changes(repo_dir: str, message: str, file_path: str) -> None:
    try:
        repo = Repo(repo_dir)

        index = repo.index

        # fix for picking up deleted files
        repo.git.add('--all')
        # index.add([file_path])
        #
        index.commit(message=message)

    except GitCommandError as gce:
        print(gce)
    except GitError as ge:
        print(ge)


def __get_repo_branches(repo: Repo) -> list:
    """
    Returns a list of branches for the given Git Repo object
    :param repo: Git Repo object
    :return: list of branch names available
    """

    # keep a list of branches
    branches = list()

    try:
        remote_branches = __get_remote_repo_branches(repo)
        branches.extend(remote_branches)

        local_branches = repo.git.branch("--format=%(refname:short)")
        for local_branch in local_branches.split('\n'):
            if local_branch not in branches:
                branches.append(local_branch)

    except GitCommandError as gce:
        print('Could not get branches from repo')
        print(gce)

    except GitError as ge:
        print('Unknown GitError')
        print(ge)

    finally:
        # always keep at least the current active branch
        branch = repo.active_branch.name
        if branch not in branches:
            branches.append(branch)

        return branches


def __get_remote_repo_branches(repo: Repo) -> list:
    """
    Returns a list of remote branches for the given Git Repo object
    :param repo: Git Repo object
    :return: list of branch names available
    """

    # keep a list of branches
    branches = list()

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

        # this is the first place we attempt to read from upstream. If there's a permissions problem, flag it here
        # and raise an exception where it can be properly handled
        if 'Permission denied (publickey)' in str(gce):
            raise RepositoryPermissionsException(str(gce))

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

    api_throttle_active = cnc_utils.get_long_term_cached_value(app_name, 'git_utils_api_throttle')
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
        print('Disabling upstream api queries for 1 hour')
        cnc_utils.set_long_term_cached_value(app_name, 'git_utils_api_throttle', True, 3601,
                                             'git_repo_details')
    return details


def get_repo_commits_url(repo_url):
    url_details = parse_repo_origin_url(repo_url)
    owner = url_details.get('owner', '')
    repo = url_details.get('repo', '')

    return f'https://github.com/{owner}/{repo}/commit/'


def parse_repo_origin_url(repo_url) -> dict:
    """
    parse a repository clone url and return a dict containing three keys: owner, repo, domain

    :param repo_url: clone url such as  # https://github.com/owner/repo/
    :return: dictionary
    """
    url_details = dict()

    try:

        if repo_url.startswith('git@') and repo_url.endswith('.git'):
            # git@gitlab.com:panw-gse/as/panhandler_test_2.git
            # git@github.com:nembery/Skillets.git
            # git@x.x.x.x:10022:msmihula/radc.git
            repo_url_parts = repo_url.split(':')
            domain = __parse_domain_from_url(repo_url)
            url_parts = repo_url_parts[-1].split('/')

            # fix for https://gitlab.com/panw-gse/as/panhandler/-/issues/41 - ensure we parse owner and repo properly
            if len(url_parts) > 2:
                # git@gitlab.com:panw-gse/as/panhandler_test_2.git
                owner = '/'.join(url_parts[0:-1])
                repo = url_parts[-1].replace('.git', '')
            else:
                # git@github.com:nembery/Skillets.git
                owner = url_parts[0]
                repo = url_parts[1].split('.git')[0]

        elif repo_url.startswith('http') and repo_url.endswith('.git'):
            # https://github.com/owner/repo.git
            # https://gitlab.com/panw-gse/as/panhandler_test_2.git
            # http://x.x.x.x:10080/msmihula/radc
            domain = __parse_domain_from_url(repo_url)
            url_parts = repo_url.split('/')[3:]

            if len(url_parts) > 2:
                owner = '/'.join(url_parts[0:-1])
                repo = url_parts[-1].replace('.git', '')
            else:
                owner = url_parts[0]
                repo = url_parts[1].split('.git')[0]

        elif repo_url.startswith('http') and repo_url.endswith('/'):
            # https://github.com/owner/repo/
            domain = __parse_domain_from_url(repo_url)
            url_parts = repo_url.split('/')[3:-1]

            if len(url_parts) > 2:
                owner = '/'.join(url_parts[0:-1])
                repo = url_parts[-1]
            else:
                owner = url_parts[0]
                repo = url_parts[1]

        elif repo_url.startswith('http'):
            # https://github.com/owner/repo ?
            # https://gitlab.com/panw-gse/as/panhandler_test_2
            domain = __parse_domain_from_url(repo_url)
            url_parts = repo_url.split('/')[3:]

            if len(url_parts) > 2:
                owner = '/'.join(url_parts[0:-1])
                repo = url_parts[-1]
            else:
                owner = url_parts[0]
                repo = url_parts[1]

        else:
            print(f'Repository URL is in an unknown format {repo_url}')
            owner = None
            repo = None
            domain = None

    except IndexError:
        print('Could not parse repo url!')
        owner = None
        repo = None
        domain = None

    url_details['domain'] = domain
    url_details['owner'] = owner
    url_details['repo'] = repo

    return url_details


def __parse_domain_from_url(repo_url: str) -> str:
    """
    parse the domain component from a repository clone url

    :param repo_url: url to be cloned, see examples below
    :return: str containing only the domain name
    """
    # git@gitlab.com:panw-gse/as/panhandler_test_2.git
    # git@github.com:nembery/Skillets.git
    # git@x.x.x.x:10022:xxx/xxx.git
    # https://github.com/owner/repo ?
    # https://gitlab.com/panw-gse/as/panhandler_test_2
    # https://github.com/owner/repo.git
    # https://gitlab.com/panw-gse/as/panhandler_test_2.git
    # http://x.x.x.x:10080/xxx/xxx

    domain = None
    first = ''

    if repo_url.startswith('http') or repo_url.startswith('ssh://') or repo_url.startswith('git://'):
        first = repo_url.split('//')[1]

    elif repo_url.startswith('git@'):
        repo_url_parts = repo_url.split(':')
        first = repo_url_parts[0].replace('git@', '')

    else:
        # this is an unsupported format
        return domain

    if ':' in first:
        second = first.split(':')[0]
    else:
        second = first

    domain = second.split('/')[0]
    return domain


def update_repo_in_cache(repo_name: str, repo_dir: str, app_dir: str) -> None:
    """
    Updates a single repo_details dict in the imported_repos cached list
    :param repo_name: name of the repo to update
    :param repo_dir: dir of the repo to update
    :param app_dir: current application
    :return: None
    """

    # get updated repo_details
    updated_repo_details = get_repo_details(repo_name, repo_dir, app_dir)

    return update_repo_detail_in_cache(updated_repo_details, app_dir)


def update_repo_detail_in_cache(repo_detail: dict, app_dir: str) -> None:
    repo_name = repo_detail['name']

    # re-cache this value
    cnc_utils.set_long_term_cached_value(app_dir, f'{repo_name}_detail', repo_detail, 604800, 'git_repo_details')

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
    repos.append(repo_detail)
    cnc_utils.set_long_term_cached_value(app_dir, 'imported_repositories', repos, 604800,
                                         'imported_git_repos')


def __get_ssh_key_dir() -> str:
    """
    Utility function to return the ssh key directory

    :return: full path to the cnc specific ssh key directory
    """
    user_dir = os.path.expanduser('~/.ssh')

    if not os.path.exists(user_dir):
        os.makedirs(user_dir, mode=0o700)

    return user_dir


def generate_ssh_key(key_name: str) -> str:
    """
    Creates an SSH key pair for use as a read / write deployment key

    :param key_name: Name of the Repository to use
    :return: public key contents as a string
    """

    user_dir = __get_ssh_key_dir()

    private_key_path = os.path.join(user_dir, key_name)
    pub_key_path = os.path.join(user_dir, key_name + '.pub')

    # check if this already exists
    if os.path.exists(pub_key_path):
        with open(pub_key_path, 'r') as pkp:
            pub_key = pkp.read()

        return pub_key

    private_key = RSAKey.generate(bits=2048)
    private_key.write_private_key_file(private_key_path, password=None)

    pub = RSAKey(filename=private_key_path, password=None)

    public_key_contents = f'{pub.get_name()} {pub.get_base64()} PAN_CNC'
    with open(pub_key_path, 'w') as pkp:
        pkp.write(public_key_contents)

    return public_key_contents


def get_default_ssh_pub_key():
    """
    Return the contents of the default ssh public key

    :return: public key as a string
    """

    return generate_ssh_key('id_rsa')


def get_ssh_pub_key_path(repo_name: str) -> str:
    """
    Gets the ssh public key path, generating the key if necessary

    :param repo_name: name of the repository
    :return: path to the public key as a string
    """
    ssh_dir = __get_ssh_key_dir()

    pub_key_path = os.path.join(ssh_dir, repo_name + '.pub')
    if not os.path.exists(pub_key_path):
        generate_ssh_key(repo_name)

    return pub_key_path


def get_ssh_priv_key_path(repo_name: str) -> str:
    """
    Gets the ssh private key path, generating the key if necessary

    :param repo_name: name of the repository
    :return: path to the public key as a string
    """
    ssh_dir = __get_ssh_key_dir()

    priv_key_path = os.path.join(ssh_dir, repo_name)
    if not os.path.exists(priv_key_path):
        generate_ssh_key(repo_name)

    return priv_key_path


def push_local_changes(repo_dir: str, key_path: str) -> (bool, str):
    """
    Attempt to push local commits upstream using the provided deploy key

    :param repo_dir: directory of the repository to push
    :param key_path: path to the private key to use for deployment
    :return: tuple of success: bool and message: str
    """

    repo = Repo(repo_dir)

    output = ''
    success = True

    try:
        push_info_list = repo.remote().push(repo.active_branch)

        for pi in push_info_list:
            output += f'{pi.summary}\n'
            if pi.flags >= 1024:
                success = False

    except GitCommandError as gce:
        print(gce)
        return False, gce
    except GitError as ge:
        print(ge)
        return False, ge
    except Exception as e:
        print(e)
        return False, e

    return success, output


def get_git_status(repo_dir) -> str:
    """
    Simple function to return the git status from a repository

    :param repo_dir: directory to a valid git repo
    :return: status as a str, blank str on error
    """
    try:
        repo = Repo(repo_dir)
        return repo.git.status()
    except GitError as git_error:
        print(git_error)
        return ''


def ensure_known_host(url: str) -> (Union[bool, None], str):
    """
    Perform an ssh-keyscan against the target domain and add the results into the known_hosts files if not found

    :param url: url of the git repository to scan
    :return: Tuple of (Success:true / Failure:False / No-op:None, message)
    """

    url_parts = parse_repo_origin_url(url)
    domain = url_parts['domain']

    print(f'Checking {domain} host key')

    if domain is None:
        return False, f'Could not parse domain from {url}'

    ssh_dir = __get_ssh_key_dir()
    known_hosts_path = os.path.join(ssh_dir, 'known_hosts')

    quoted_domain = shlex.quote(domain)

    try:
        print(f'Running keyscan on domain: {quoted_domain}')
        keyscan_results = subprocess.check_output(f'ssh-keyscan -t rsa {quoted_domain} 2>/dev/null', shell=True)
        found_keys = keyscan_results.decode('utf-8').strip()
        # partial fix for Gl #28 - do not add blank results to known_hosts
        if not found_keys:
            # FW Policy may disable ssh-keyscan, check for domain and pass if it's already been found
            if __check_know_hosts(domain):
                print('keyscan failed, but we do have a domain entry in known hosts...check FW Policy for this domain')
                return None, f'Doamin: {domain} is already known'
            else:
                # we have no keyscan results and this domain is not already known, so nothing we can do here...
                print('keyscan failed, but there is no domain entry in known hosts...check FW Policy for this domain')
                return False, f'Could not get keyscan results for domain: {quoted_domain} - Check Firewall / GP Policy'

        # we have a keyscan result - check if it's already known
        if __check_know_hosts(found_keys):
            print(f'Domain {domain} is already known by this key')
            return None, f'Doamin: {domain} is already known'

        # we have a keyscan that is not already known, add it to the file
        print(f'Adding {found_keys} to known_hosts file')

        # detect if this file ends with a newline or not, we may need to add it during the append
        with open(known_hosts_path, 'r') as khp:
            if khp.read().endswith('\n'):
                needs_newline = ''
            else:
                needs_newline = '\n'

        # now append the found_keys along with a leading newline if necessary
        with open(known_hosts_path, 'a') as khp:
            khp.write(f'{needs_newline}{found_keys}\n')

        return True, found_keys

    except subprocess.CalledProcessError as cpe:
        print(cpe)
        return False, str(cpe)


def __check_know_hosts(domain_or_key: str) -> bool:
    """
    Checks known hosts file for a str and return true if found.
    This is used to check if a domain is already known, or if a ssh-key belonging to a domain is found...

    :param domain_or_key: domain name or ssh-key to check
    :return: bool true if found in known_host file already
    """

    ssh_dir = __get_ssh_key_dir()
    known_hosts_path = os.path.join(ssh_dir, 'known_hosts')

    # touch known hosts file if it does not exist
    if not os.path.exists(known_hosts_path):
        with open(known_hosts_path, 'a'):
            pass

        os.chmod(known_hosts_path, mode=0o644)
        return False

    with open(known_hosts_path, 'r') as khp:
        for line in khp:
            if domain_or_key in line:
                return True

    return False
