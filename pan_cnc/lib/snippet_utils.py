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

import os
from collections import OrderedDict
from pathlib import Path

import oyaml
from django.conf import settings
from jinja2 import Environment
from jinja2.loaders import BaseLoader
from yaml.constructor import ConstructorError
from yaml.error import YAMLError
from yaml.parser import ParserError
from yaml.reader import ReaderError
from yaml.scanner import ScannerError

from . import cnc_utils
from . import jinja_filters
from .exceptions import CCFParserError
from .exceptions import SnippetNotFoundException


def load_service_snippets() -> list:
    """
    Locates all configuration snippets in the mssp/snippets directory. Looks for and loads the .meta-cnc.yaml file
    in each directory. If there is a key called 'type' and the value is 'service' add to the services list and return
    :return: List of services (dict) or empty list if none found - Check README in snippets dir for latest
    dict / YAML format
    """
    services = load_snippets_of_type('service')
    return services


def load_baseline_snippets() -> list:
    services = load_snippets_of_type('baseline')
    return services


def load_template_snippets() -> list:
    services = load_snippets_of_type('templates')
    return services


def load_all_snippets(app_dir) -> list:
    all_snippets = cnc_utils.get_long_term_cached_value(app_dir, 'all_snippets')
    if all_snippets is not None:
        return all_snippets

    print('Getting all snippets again')
    snippet_list = load_snippets_of_type(snippet_type=None, app_dir=app_dir)
    cnc_utils.set_long_term_cached_value(app_dir, 'all_snippets', snippet_list, -1)
    return snippet_list


def load_snippets_by_label(label_name, label_value, app_dir) -> list:
    services = load_snippets_of_type(snippet_type=None, app_dir=app_dir)
    filtered_services = list()
    for service in services:
        if 'labels' in service and label_name in service['labels']:
            if type(service['labels'][label_name]) is str:
                if service['labels'][label_name] == label_value:
                    filtered_services.append(service)
            elif type(service['labels'][label_name]) is list:
                for label_list_value in service['labels'][label_name]:
                    if label_list_value == label_value:
                        filtered_services.append(service)
            else:
                print(f"Unknown label type in .meta-cnc for skillet: {service['name']}")

    return filtered_services


def load_snippets_of_type(snippet_type=None, app_dir=None) -> list:
    """
    Loads a list of snippets of the given type, or all snippets if snippet_type is None
    :param snippet_type: string of the snippet type to field
    :param app_dir: name of the app to load the snippets from
    :return: list of snippet dicts
    """

    snippets_dir = Path(os.path.join(settings.SRC_PATH, app_dir, 'snippets'))

    user_dir = os.path.expanduser('~/.pan_cnc')
    user_snippets_dir = os.path.join(user_dir, app_dir, 'repositories')

    app_snippets = load_snippets_of_type_from_dir(app_dir, snippets_dir, snippet_type)
    user_snippets = load_snippets_of_type_from_dir(app_dir, user_snippets_dir, snippet_type)

    all_snippets = app_snippets + user_snippets
    return all_snippets


def load_snippets_of_type_from_dir(app_name: str, directory: str, snippet_type=None) -> list:
    """
    Loads a list of snippets of the given type, or all snippets if snippet_type is None from a specified directory
    This is useful to load all snippets that come from a specific repository for example
    :param app_name: CNC application name to keep caches seperate by namespace
    :param directory: full path to directory from which to search for meta-cnc files
    :param snippet_type: type of snippet to add to the list if found
    :return: list of snippet objects
    """
    snippet_list = list()

    snippets_dir = Path(directory)

    try:
        snippets_dir.stat()
    except PermissionError:
        print(f'Permission Denied access {snippets_dir}')
        return snippet_list
    except OSError:
        print(f'Could not access {snippets_dir}')
        return snippet_list

    if not snippets_dir.exists():
        print(f'Could not find meta-cnc files in dir {directory}')
        return snippet_list

    snippet_dirs_dict = cnc_utils.get_long_term_cached_value(app_name, f'snippet_types_in_{directory}')

    if snippet_dirs_dict is not None:
        # snippet_types is a dict with a key for each directory
        # each directory value is another dict with keys for each snippet_type
        # snippet_dirs_dict = cache.get('snippet_types')
        if str(snippets_dir) in snippet_dirs_dict:
            snippet_types_dict = snippet_dirs_dict[str(snippets_dir)]
        else:
            snippet_types_dict = dict()

        if snippet_type in snippet_types_dict:
            # print(f'Cache hit for {snippet_type}')
            return snippet_types_dict[snippet_type]

        if snippet_type is None:
            # check for JSON deserialized None value. Will appear here as string 'null'
            if 'null' in snippet_types_dict:
                # print(f'Cache hit for {snippet_type}')
                return snippet_types_dict['null']

        snippet_types_dict[snippet_type] = dict()

    else:
        snippet_types_dict = dict()
        snippet_dirs_dict = dict()

    print(f'Rebuilding Skillet cache for dir {directory}')

    snippet_list = _check_dir(snippets_dir, snippet_type, list())
    snippet_types_dict[snippet_type] = snippet_list
    snippet_dirs_dict[str(snippets_dir)] = snippet_types_dict
    # cache these items indefinitely
    cnc_utils.set_long_term_cached_value(app_name, f'snippet_types_in_{directory}', snippet_dirs_dict, -1)
    return snippet_list


def _check_dir(directory: Path, snippet_type: str, snippet_list: list) -> list:
    """
    Recursive function to look for all files in the current directory with a name matching '.meta-cnc.yaml'
    otherwise, iterate through all sub-dirs and skip dirs with name that match '.git', '.venv', and '.terraform'
    will descend into all other dirs and call itself again.
    Returns a list of compiled skillets
    :param directory: PosixPath of directory to begin searching
    :param snippet_type: type of skillet to match
    :param snippet_list: combined list of all loaded skillets
    :return: list of dicts containing loaded skillets
    """

    err_condition = False
    for d in directory.glob('.meta-cnc.y*'):
        snippet_path = str(d.parent.absolute())
        # print(f'snippet_path is {snippet_path}')
        try:
            with d.open(mode='r') as sc:
                raw_service_config = oyaml.safe_load(sc.read())
                service_config = _normalize_snippet_structure(raw_service_config)
                service_config['snippet_path'] = snippet_path
                if snippet_type is not None:
                    if 'type' in service_config and service_config['type'] == snippet_type \
                            and 'name' in service_config:
                        snippet_list.append(service_config)
                else:
                    snippet_list.append(service_config)

        except IOError as ioe:
            print('Could not open metadata file in dir %s' % d.parent)
            print(ioe)
            err_condition = True
            continue
        except ParserError as pe:
            print('Could not parse metadata file in dir %s' % d.parent)
            print(pe)
            err_condition = True
            continue
        except ScannerError as se:
            print('Could not parse meta-cnc file in dir %s' % d.parent)
            print(se)
            continue
        except ConstructorError as ce:
            print('Could not parse metadata file in dir %s' % d.parent)
            print(ce)
            err_condition = True
            continue
        except ReaderError as re:
            print('Could not parse metadata file in dir %s' % d.parent)
            print(re)
            err_condition = True
            continue
        except YAMLError as ye:
            print('YAMLError: Could not parse metadata file in dir %s' % d.parent)
            print(ye)
            err_condition = True
            continue
        except Exception as ex:
            print('Caught unknown exception!')
            print(ex)
            err_condition = True
            continue

    # Do not descend into sub dirs after a .meta-cnc file has already been found
    if snippet_list:
        return snippet_list

    if err_condition:
        return snippet_list

    for d in directory.iterdir():
        if d.is_file():
            continue
        if '.git' in d.name:
            continue
        if '.venv' in d.name:
            continue
        if '.terraform' in d.name:
            continue
        if d.is_dir():
            snippet_list.extend(_check_dir(d, snippet_type, list()))

    return snippet_list


def debug_snippets_in_repo(directory: Path, err_list: list) -> list:
    """
    Recursive function to look for all files in the current directory with a name matching '.meta-cnc.yaml'
    otherwise, iterate through all sub-dirs and skip dirs with name that match '.git', '.venv', and '.terraform'
    will descend into all other dirs and call itself again.
    Returns a list of skillet errors
    :param directory: PosixPath of directory to begin searching
    :param err_list: combined list of all skillet errors
    :return: list of dicts containing skillet errors
    """

    err_condition = False
    err_detail = dict()
    for d in directory.glob('.meta-cnc.y*'):
        snippet_path = str(d.parent.absolute())
        err_detail['path'] = snippet_path
        print(f'debug snippet_path: {snippet_path}')
        try:
            with d.open(mode='r') as sc:
                raw_service_config = oyaml.safe_load(sc.read())
                errs = _debug_skillet_structure(raw_service_config)
                if errs:
                    err_condition = True
                    err_detail['severity'] = 'warn'
                    err_detail['err_list'] = errs

        except IOError as ioe:
            err = 'Could not open metadata file in dir %s' % d.parent
            print(ioe)
            err_condition = True
            err_detail['severity'] = 'error'
            err_detail['err_list'] = [err, str(ioe)]
            continue
        except ParserError as pe:
            err = 'Could not parse metadata file in dir %s' % d.parent
            print(pe)
            err_condition = True
            err_detail['severity'] = 'error'
            err_detail['err_list'] = [err, str(pe)]
            continue
        except ScannerError as se:
            err = 'Could not parse meta-cnc file in dir %s' % d.parent
            print(se)
            err_condition = True
            err_detail['severity'] = 'error'
            err_detail['err_list'] = [err, str(se)]
            continue
        except ConstructorError as ce:
            err = 'Could not parse metadata file in dir %s' % d.parent
            print(ce)
            err_condition = True
            err_detail['severity'] = 'error'
            err_detail['err_list'] = [err, str(ce)]
            continue
        # catch everything else that should be generated from oyaml libraries
        except YAMLError as ye:
            err = 'YAMLError: Could not parse metadata file in dir %s' % d.parent
            print(ye)
            err_condition = True
            err_detail['severity'] = 'error'
            err_detail['err_list'] = [err, str(ye)]
            continue

    # Do not descend into sub dirs after a .meta-cnc file has already been found
    if err_condition:
        err_list.append(err_detail)
        return err_list

    for d in directory.iterdir():
        if d.is_file():
            continue
        if '.git' in d.name:
            continue
        if '.venv' in d.name:
            continue
        if '.terraform' in d.name:
            continue
        if d.is_dir():
            err_list.extend(debug_snippets_in_repo(d, list()))

    return err_list


def load_snippet_with_name(snippet_name, app_dir) -> (dict, None):
    """
    Returns a service (dict) that has a 'name' attribute matching 'snippet_name'. Service is a dict containing keys:
    'name (str)', 'description (str)', 'label (str)', 'variables (list)', and 'snippets (list)'.
    :return: Service dict or None if none found
    """
    print(f'checking in app_dir {app_dir} for snippet {snippet_name}')
    services = load_all_snippets(app_dir)
    for service in services:
        if service['name'] == snippet_name:
            return service

    print('Could not find service with name: %s' % snippet_name)
    return None


def get_snippet_metadata(snippet_name, app_name) -> (str, None):
    """
    Returns the snippet metadata as a str
    :param snippet_name: name of the snippet
    :param app_name: name of the current CNC application
    :return: str of .meta-cnc.yaml file
    """
    skillet = load_snippet_with_name(snippet_name, app_name)
    if skillet is not None and 'snippet_path' in skillet:
        parent = Path(skillet['snippet_path'])
        if parent.exists():
            # handle .yaml and .yml if possible
            mdfs = list(parent.glob('.meta-cnc.y*'))
            if len(mdfs) == 1:
                mdf = mdfs[0]
            else:
                print('Could not find meta-cnc.yaml')
                return None
            if mdf.exists() and mdf.is_file():
                try:
                    with mdf.open('r') as sc:
                        data = sc.read()
                        snippet_data = oyaml.safe_load(data)
                        if 'name' in snippet_data and snippet_data['name'] == snippet_name:
                            print(f'Found {snippet_name} at {parent.absolute()}')
                            return data
                        else:
                            print('name mismatch loading .meta-cnc file')
                except IOError as ioe:
                    print('Could not open metadata file in dir %s' % mdf)
                    print(ioe)
                    return None
                except ParserError as pe:
                    print(pe)
                    print('Could not parse metadata file')
                    return None
            else:
                print('.meta-cnc cannot be found in this dir')
    else:
        print('Returned .meta-cnc contents was None')

    return None


def render_snippet_template(service, app_dir, context, template_file='') -> str:
    try:
        if template_file == '':
            if 'snippets' not in service:
                print('No snippets defined in meta-cnc.yaml file! Cannot determine what to render...')
                raise SnippetNotFoundException

            template_name = service['snippets'][0]['file']
        else:
            template_name = template_file

        if 'snippet_path' in service:
            template_full_path = os.path.join(service['snippet_path'], template_name)
        else:
            raise CCFParserError('Could not locate .meta-cnc')

        print(template_full_path)
        with open(template_full_path, 'r') as template:
            template_string = template.read()
            environment = Environment(loader=BaseLoader())

            for f in jinja_filters.defined_filters:
                if hasattr(jinja_filters, f):
                    environment.filters[f] = getattr(jinja_filters, f)

            template_template = environment.from_string(template_string)
            rendered_template = template_template.render(context)
            return rendered_template
    except Exception as e:
        print(e)
        print('Caught an error rendering snippet')
        if 'snippet_path' in service:
            print(f"Caught error rendering snippet at path: {service['snippet_path']}")

        return 'Error'


def resolve_dependencies(snippet, app_dir, dependencies) -> list:
    """
    Takes a snippet object and resolved all dependencies. Will return a list of dependencies

    all_deps = snippet_utils.resolve_dependencies(snippet_object, 'app_nane', [])

    :param snippet: OrderedDict Snippet Metadata
    :param app_dir: directory in which to load all snippets
    :param dependencies: found list of names of snippets on which this snippet depends
    :return: list of names upon which this snippet is dependent. Each item in the list has a dependency on the item
    that immediately after it in the list.
    """

    print('Resolving dependencies for snippet: %s' % snippet)
    if dependencies is None or type(dependencies) is not list:
        dependencies = list()

    if 'extends' in snippet and snippet['extends'] is not None:
        parent_snippet_name = snippet['extends']
        print(parent_snippet_name)
        if parent_snippet_name not in dependencies:
            dependencies.append(parent_snippet_name)
            parent_snippet = load_snippet_with_name(snippet['extends'], app_dir)
            if parent_snippet is None:
                print(f"Could not load the snippet named by the extends from {snippet['name']}")
                raise SnippetNotFoundException

            # inception time
            return resolve_dependencies(parent_snippet, app_dir, dependencies)

    # always reverse the list as we need to walk this list from deep to shallow
    dependencies.reverse()
    return dependencies


def invalidate_snippet_caches(app_name: str) -> None:
    """
    Clears the long term cache file
    :param app_name: name of the CNC application
    :return: None
    """
    cnc_utils.set_long_term_cached_value(app_name, f'all_snippets', None, 0)
    cnc_utils.set_long_term_cached_value(app_name, f'snippet_types', None, 0)

    # also clear the in memory cache as well
    # FIXME - try to be smarter about what we evict from the cache!
    cnc_utils.evict_cache_items_of_type(app_name, cache_type='snippet')
    # cache_key = f'{app_name}_cache'
    # cache.set(cache_key, dict())


def load_all_labels(app_dir: str) -> list:
    """
    Returns a list of labels defined across all snippets
    for example:
    labels:
        label_name: label_value

    will add 'label_name' to the list

    :param app_dir: application directory where to search all snippets
    :return: list of strings representing all found label keys
    """
    labels = list()
    snippets = load_all_snippets(app_dir)
    for snippet in snippets:
        if 'labels' not in snippet:
            continue

        labels = snippet.get('labels', [])
        for label_name in labels:
            labels.append(label_name)

    return labels


def load_all_label_values(app_dir: str, label_name: str) -> list:
    """
    Returns a list of label values defined across all snippets with a given label
    for example:
    labels:
        label_name: label_value

    will add 'label_name' to the list

    :param app_dir: application directory where to search all snippets
    :param label_name: name of the label to search for
    :return: list of strings representing all found label values for given key
    """
    labels_list = list()
    snippets = load_all_snippets_with_label_key(app_dir, label_name)
    for snippet in snippets:
        if 'labels' not in snippet:
            continue

        labels = snippet.get('labels', [])
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


def load_all_snippets_with_label_key(app_dir: str, label: str):
    """
    Returns a list of snippets that have a label key == label
    :param app_dir: application directory where to search for snippets
    :param label: name of the label key to search
    :return: list of dicts representing loaded .meta-cnc definitions
    """
    snippets_with_label = list()
    snippets = load_all_snippets(app_dir)
    for snippet in snippets:
        if 'labels' not in snippet:
            continue

        labels = snippet.get('labels', [])
        for label_name in labels:
            if label_name == label:
                snippets_with_label.append(snippet)

    return snippets_with_label


def load_all_snippets_without_label_key(app_dir: str, label: str) -> list:
    """
    Returns a list of snippets that do not have a label key == label
    :param app_dir: application directory where to search for snippets
    :param label: name of the label key to search
    :return: list of dicts representing loaded .meta-cnc definitions
    """
    snippets_with_label = list()
    snippets = load_all_snippets(app_dir)
    for snippet in snippets:
        if 'labels' not in snippet:
            continue

        labels = snippet.get('labels', [])
        found = False
        for label_name in labels:
            if label_name == label:
                found = True

        if not found:
            # ignore meta-cnc files with a type of 'app'
            if 'type' in snippet and snippet['type'] != 'app':
                snippets_with_label.append(snippet)

    return snippets_with_label


def _normalize_snippet_structure(skillet: dict) -> dict:
    """
    Attempt to resolve common configuration file format errors
    :param skillet: a loaded skillet/snippet
    :return: skillet/snippet that has been 'fixed'
    """

    if skillet is None:
        skillet = dict()

    if type(skillet) is not dict:
        skillet = dict()

    if 'name' not in skillet:
        skillet['name'] = 'Unknown Skillet'

    if 'label' not in skillet:
        skillet['label'] = 'Unknown Skillet'

    if 'type' not in skillet:
        skillet['type'] = 'template'

    if 'depends' not in skillet:
        skillet['depends'] = list()

    elif not isinstance(skillet['depends'], list):
        skillet['depends'] = list()

    elif isinstance(skillet['depends'], list):
        for depends in skillet['depends']:
            if not isinstance(depends, dict):
                print('Removing Invalid Depends Definition')
                print(type(depends))
                skillet['depends'].remove(depends)

            else:
                if not {'url', 'name'}.issubset(depends):
                    print('Removing Invalid Depends Definition - incorrect attributes')
                    print('Required "url" and "name" to be present. "branch" is optional')
                    print(depends)

                else:
                    if depends['url'] is None or depends['url'] == '' \
                            or depends['name'] is None or depends['name'] == '':
                        print('Removing Invalid Depends Definition - incorrect attribute values')
                        print('Required "url" and "name" to be not be blank or None')
                        print(depends)

    # first verify the variables stanza is present and is a list
    if 'variables' not in skillet:
        skillet['variables'] = list()

    elif skillet['variables'] is None:
        skillet['variables'] = list()

    elif type(skillet['variables']) is not list:
        skillet['variables'] = list()

    elif type(skillet['variables']) is list:
        for variable in skillet['variables']:
            if type(variable) is not dict:
                print('Removing Invalid Variable Definition')
                print(type(variable))
                skillet['variables'].remove(variable)

            else:
                if 'name' not in variable:
                    variable['name'] = 'Unknown variable'

                if 'type_hint' not in variable:
                    variable['type_hint'] = 'text'

                if 'default' not in variable:
                    variable['default'] = ''

    # verify labels stanza is present and is a OrderedDict
    if 'labels' not in skillet:
        skillet['labels'] = OrderedDict()

    elif skillet['labels'] is None:
        skillet['labels'] = OrderedDict()

    elif type(skillet['labels']) is not OrderedDict and type(skillet['labels']) is not dict:
        skillet['labels'] = OrderedDict()

    # ensure we have a collection label
    if 'collection' not in skillet['labels'] or type(skillet['labels']['collection']) is None:
        # do not force a collection for 'app' type skillets as these aren't meant to be shown to the end user
        if skillet['type'] != 'app':
            skillet['labels']['collection'] = list()
            skillet['labels']['collection'].append('Unknown')

    elif type(skillet['labels']['collection']) is str:
        new_collection = list()
        old_value = skillet['labels']['collection']
        new_collection.append(old_value)
        skillet['labels']['collection'] = new_collection

    # verify snippets stanza is present and is a list
    if 'snippets' not in skillet:
        skillet['snippets'] = list()

    elif skillet['snippets'] is None:
        skillet['snippets'] = list()

    elif type(skillet['snippets']) is not list:
        skillet['snippets'] = list()

    return skillet


def _debug_skillet_structure(skillet: dict) -> list:
    """
    Verifies the structure of a skillet and returns a list of errors or warning if found, None otherwise
    :param skillet: loaded skillet
    :return: list of errors or warnings if found
    """

    errs = list()

    if skillet is None:
        errs.append('Skillet is blank or could not be loaded')
        return errs

    if type(skillet) is not dict:
        errs.append('Skillet is malformed')
        return errs

    # verify labels stanza is present and is a OrderedDict
    if 'labels' not in skillet:
        errs.append('No labels attribute present in skillet')
    else:
        if 'collection' not in skillet['labels']:
            errs.append('No collection defined in skillet')

    if 'label' not in skillet:
        errs.append('No label attribute in skillet')

    if 'type' not in skillet:
        errs.append('No type attribute in skillet')
    else:
        valid_types = ['panos', 'panorama', 'panorama-gpcs', 'pan_validation',
                       'python3', 'rest', 'terraform', 'template', 'workflow', 'docker']
        if skillet['type'] not in valid_types:
            errs.append(f'Unknown type {skillet["type"]} in skillet')

    return errs
