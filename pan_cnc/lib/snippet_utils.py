import oyaml
import os
from django.conf import settings
from django.core.cache import cache
from pathlib import Path
from jinja2 import Environment
from jinja2.loaders import BaseLoader
from . import jinja_filters


def load_service_snippets():
    """
    Locates all configuration snippets in the mssp/snippets directory. Looks for and loads the metadata.yaml file
    in each directory. If there is a key called 'type' and the value is 'service' add to the services list and return
    :return: List of services (dict) or empty list if none found - Check README in snippets dir for latest
    dict / YAML format
    """
    services = load_snippets_of_type('service')
    return services


def load_baseline_snippets():
    services = load_snippets_of_type('baseline')
    return services


def load_template_snippets():
    services = load_snippets_of_type('templates')
    return services


def load_all_snippets(app_dir):
    # cache and keep all snippets when type == none
    if cache.has_key('all_snippets'):
        snippet_list = cache.get('all_snippets', []) 
        if snippet_list:
            return snippet_list
    
    snippet_list = load_snippets_of_type(snippet_type=None, app_dir=app_dir)
    cache.set('all_snippets', snippet_list)
    return snippet_list


def load_snippets_by_label(label_name, label_value, app_dir):
    services = load_snippets_of_type(snippet_type=None, app_dir=app_dir)
    filtered_services = list()
    for service in services:
        if 'labels' in service and label_name in service['labels']:
            if service['labels'][label_name] == label_value:
                filtered_services.append(service)

    return filtered_services


def load_snippets_of_type(snippet_type=None, app_dir=None):
    """
    Loads a list of snippets of the given type, or all snippets of snippet_type is None
    :param snippet_type: string of the snippet type to field
    :param app_dir: name of the app to load the snippets from
    :return: list of snippet dicts
    """
 
    snippet_list = list() 
   
    snippets_dir = Path(os.path.join(settings.SRC_PATH, app_dir, 'snippets'))
    for d in snippets_dir.rglob('./*'):
        mdf = os.path.join(d, 'metadata.yaml')
        if os.path.isfile(mdf):
            snippet_path = os.path.dirname(mdf)
            try:
                with open(mdf, 'r') as sc:
                    service_config = oyaml.load(sc.read())
                    service_config['snippet_path'] = snippet_path
                    if snippet_type is not None:
                        if 'type' in service_config and service_config['type'] == snippet_type:
                            snippet_list.append(service_config)
                    else:
                        snippet_list.append(service_config)

            except IOError as ioe:
                print('Could not open metadata file in dir %s' % mdf)
                print(ioe)
                continue

    return snippet_list


def load_snippet_with_name(snippet_name, app_dir):
    """
    Returns a service (dict) that has a 'name' attribute matching 'snippet_name'. Service is a dict containing keys:
    'name (str)', 'description (str)', 'label (str)', 'variables (list)', and 'snippets (list)'.
    :return: Service dict or None if none found
    """
    services = load_all_snippets(app_dir)
    for service in services:
        if service['name'] == snippet_name:
            return service

    print('Could not find service with name: %s' % snippet_name)
    return None


def get_snippet_metadata(snippet_name, app_dir):
    """
    Returns the snippet metadata as a str
    :param snippet_name: name of the snippet
    :param app_dir: current app
    :return: str of metadata.yaml file
    """
    snippets_dir = Path(os.path.join(settings.SRC_PATH, app_dir, 'snippets'))
    for d in snippets_dir.rglob('./*'):
        mdf = os.path.join(d, 'metadata.yaml')
        if os.path.isfile(mdf):
            snippet_path = os.path.dirname(mdf)
            try:
                with open(mdf, 'r') as sc:
                    snippet_data = oyaml.load(sc.read())
                    if 'name' in snippet_data and snippet_data['name'] == snippet_name:
                        print(f'Found {snippet_name} at {snippet_path}')
                        sc.seek(0)
                        return sc.read()
            except IOError as ioe:
                print('Could not open metadata file in dir %s' % mdf)
                print(ioe)
                return None

    return None


def render_snippet_template(service, app_dir, context, template_file=''):
    try:
        if template_file == '':
            template_name = service['snippets'][0]['file']
        else:
            template_name = template_file

        if 'snippet_path' in service:
            template_full_path = os.path.join(service['snippet_path'], template_name)
        else:
            template_full_path = Path(os.path.join(settings.SRC_PATH, app_dir, 'snippets', template_name))

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
        return None


def resolve_dependencies(snippet, app_dir, dependencies):
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
            # inception time
            return resolve_dependencies(parent_snippet, app_dir, dependencies)

    # always reverse the list as we need to walk this list from deep to shallow
    dependencies.reverse()
    return dependencies
