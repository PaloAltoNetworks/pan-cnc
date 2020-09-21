import json
import os

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from skilletlib import SkilletLoader

from cnc.models import RepositoryDetails
from cnc.models import Skillet
from pan_cnc.lib import cnc_utils


def initialize_default_repositories(app_name) -> None:
    """
    Find any configured repositories in the application configuration
    and build db records for their respective skillets.

    Called from the WelcomeView to ensure all default skillets are found and indexed

    :return: None
    """
    app_config = cnc_utils.get_app_config(app_name)
    if 'repositories' not in app_config:
        return

    for r in app_config['repositories']:
        repo_details = dict()
        repo_details.update(r)

        initialize_repo(repo_details)


def initialize_repo(repo_detail: dict) -> list:
    """
    Initialize a git repository object using the supplied repositories details dictionary object
    :param repo_detail:
    :return: list of Skillets found in that repository
    """
    repo_name = repo_detail.get('name', '')
    (repository_object, created) = RepositoryDetails.objects.get_or_create(
        name=repo_name,
        defaults={'url': repo_detail.get('url', ''),
                  'details_json': json.dumps(repo_detail)
                  }
    )

    if created:
        print(f'Indexing new repository object: {repository_object.name}')
        return refresh_skillets_from_repo(repo_name)

    return load_skillets_from_repo(repo_name)


def load_skillets_from_repo(repo_name: str) -> list:
    """
    returns a list of skillets from the repository as found in the db
    :param repo_name: name of the repository to search
    :return: list of skillet dictionary objects
    """
    all_skillets = list()

    try:
        repo_object = RepositoryDetails.objects.get(name=repo_name)

        repo_skillet_qs = repo_object.skillet_set.all()
        for skillet in repo_skillet_qs:
            all_skillets.append(json.loads(skillet.skillet_json))

        return all_skillets

    except ObjectDoesNotExist:
        return all_skillets
    except ValueError:
        return all_skillets


def update_skillet_cache() -> None:
    """
    Updates the 'all_snippets' key in the cnc cache. This gets called whenever a repository is initialized or updated
    to ensure the legacy cache is always kept up to date
    :return: None
    """
    all_skillets = load_all_skillets(refresh=True)
    # FIXME - this can and will break if every more than one app tries to do this...
    app_name = get_default_app_name()

    # ensure everything gets removed!
    cnc_utils.clear_long_term_cache(app_name)

    cnc_utils.set_long_term_cached_value(app_name, 'all_snippets', all_skillets, -1)
    # db_utils.load_add_skillets saves all_skillets under 'cnc' app name, ensure this is updated here as well...
    cnc_utils.set_long_term_cached_value('cnc', 'all_snippets', all_skillets, -1)
    # remove it all!


def get_repository_details(repository_name: str) -> (dict, None):
    """
    returns the details dict as loaded from the database record for this db
    :param repository_name: name of the repository to find and return
    :return: loaded dict or None if not found
    """

    if RepositoryDetails.objects.filter(name=repository_name).exists():
        try:
            repo_db_record = RepositoryDetails.objects.get(name=repository_name)
            return json.loads(repo_db_record.details_json)
        except ValueError as ve:
            print(ve)
            return None
    else:
        return None


def update_repository_details(repo_name: str, repo_detail: dict) -> None:
    """
    Update the repository details json object on the db record

    :param repo_name: name of the repository object to update
    :param repo_detail: dictionary of repository details includes branches, url, name, commits, etc
    :return: None
    """
    try:
        repo_db_record = RepositoryDetails.objects.get(name=repo_name)
    except ObjectDoesNotExist as odne:
        print(r'Could not update non-existent db record for {repo_name}')
        print(odne)
        return None

    try:
        repo_db_record.details_json = json.dumps(repo_detail)
    except ValueError as ve:
        print(f'Could not update db record with malformed json: {ve}')
        return None

    repo_db_record.save()


def refresh_skillets_from_repo(repo_name: str) -> list:
    all_skillets = list()

    user_dir = os.path.expanduser('~/.pan_cnc')

    app_name = get_default_app_name()
    snippets_dir = os.path.join(user_dir, app_name, 'repositories')
    repo_dir = os.path.join(snippets_dir, repo_name)

    try:
        repo_object = RepositoryDetails.objects.get(name=repo_name)

        sl = SkilletLoader()

        found_skillets = sl.load_all_skillets_from_dir(repo_dir)

        for skillet_object in found_skillets:
            skillet_name = skillet_object.name
            (skillet_record, created) = Skillet.objects.get_or_create(
                name=skillet_name,
                defaults={
                    'skillet_json': json.dumps(skillet_object.skillet_dict),
                    'repository_id': repo_object.id,
                }
            )

            if not created:
                # check if skillet contents have been updated
                found_skillet_json = json.dumps(skillet_object.skillet_dict)
                if skillet_record.skillet_json != found_skillet_json:
                    skillet_record.skillet_json = found_skillet_json
                    skillet_record.save()

        for db_skillet in repo_object.skillet_set.all():
            found = False
            for found_skillet in found_skillets:
                if db_skillet.name == found_skillet.name:
                    found = True
                    continue

            if not found:
                db_skillet.delete()

        update_skillet_cache()

        return load_skillets_from_repo(repo_name)

    except ObjectDoesNotExist:
        return all_skillets


def load_skillet_by_name(skillet_name: str) -> (dict, None):
    try:
        skillet = Skillet.objects.get(name=skillet_name)
        return json.loads(skillet.skillet_json)
    except ObjectDoesNotExist:
        return None
    except ValueError:
        print('Could not parse Skillet metadata in load_skillet_by_name')
        return None


def load_all_skillet_label_values(label_name):
    labels_list = list()
    skillets = load_all_skillets()

    for skillet in skillets:
        if 'labels' not in skillet:
            continue

        labels = skillet.get('labels', [])

        for label_key in labels:
            if label_key == label_name:

                if type(labels[label_name]) is str:
                    label_value = labels[label_name]
                    if label_value not in labels_list:
                        labels_list.append(label_value)

                elif type(labels[label_name]) is list:
                    for label_list_value in labels[label_name]:
                        if label_list_value not in labels_list:
                            labels_list.append(label_list_value)

    return labels_list


def load_all_skillets(refresh=False) -> list:
    """
    Returns a list of skillet dictionaries
    :param refresh: Boolean flag whether to use the cache or force a cache refresh
    :return: skillet dictionaries
    """
    if refresh is False:
        cached_skillets = cnc_utils.get_long_term_cached_value('cnc', 'all_snippets')
        if cached_skillets is not None:
            return cached_skillets

    skillet_dicts = list()
    skillets = Skillet.objects.all()
    for skillet in skillets:
        skillet_dicts.append(json.loads(skillet.skillet_json))

    cnc_utils.set_long_term_cached_value('cnc', 'all_snippets', skillet_dicts, -1)
    return skillet_dicts


def load_skillets_with_label(label_name, label_value):
    filtered_skillets = list()
    all_skillets = load_all_skillets()

    for skillet in all_skillets:
        if 'labels' in skillet and label_name in skillet['labels']:
            if type(skillet['labels'][label_name]) is str:

                if skillet['labels'][label_name] == label_value:
                    filtered_skillets.append(skillet)

            elif type(skillet['labels'][label_name]) is list:
                for label_list_value in skillet['labels'][label_name]:
                    if label_list_value == label_value:
                        filtered_skillets.append(skillet)

    return filtered_skillets


def get_default_app_name():
    if len(settings.INSTALLED_APPS_CONFIG) != 1:
        raise Exception('Cannot get default app configuration, please specify the app you need')

    for k, v in settings.INSTALLED_APPS_CONFIG.items():
        return k
