from git import Repo
import requests
from pan_cnc.lib import cnc_utils


def get_repo_details(repo_name, repo_dir):

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

    upstream_details = get_repo_upstream_details(repo_name, url)
    if 'description' in upstream_details:
        repo_detail['description'] = upstream_details['description']
    else:
        repo_detail['description'] = branch

    return repo_detail


def update_repo(repo_dir):
    repo = Repo(repo_dir)
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

    details = cnc_utils.get_cached_value(f'git_utils_upstream_{repo_name}')
    if details is not None:
        return details

    details = dict()

    if 'github' in repo_url:
        url_parts = repo_url.split('/')[-2:]
        owner = url_parts[0]
        repo = url_parts[1].split('.git')[0]

        api_url = f'https://api.github.com/repos/{owner}/{repo}'
        detail_string = requests.get(api_url, verify=False)
        details = detail_string.json()
        cnc_utils.set_cached_value(f'git_utils_upstream_{repo_name}', details)

    return details



