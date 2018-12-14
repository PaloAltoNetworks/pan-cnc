import oyaml
import os
from django.conf import settings
from pathlib import Path
from jinja2 import Environment
from jinja2.loaders import BaseLoader


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
    services = load_snippets_of_type(snippet_type=None, app_dir=app_dir)
    return services


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
    snippets_dir = Path(os.path.join(settings.SRC_PATH, app_dir, 'snippets'))
    services = list()
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
                            services.append(service_config)
                    else:
                        services.append(service_config)

            except IOError as ioe:
                print('Could not open metadata file in dir %s' % mdf)
                print(ioe)
                continue

    return services


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


def render_snippet_template(service, app_dir, context):
    try:
        template_name = service['snippets'][0]['file']

        template_full_path = os.path.join(service['snippet_path'], template_name)
        with open(template_full_path, 'r') as template:
            template_string = template.read()
            template_template = Environment(loader=BaseLoader()).from_string(template_string)
            rendered_template = template_template.render(context)
            return rendered_template
    except Exception as e:
        print(e)
        print('Caught an error deploying service')
        return None

