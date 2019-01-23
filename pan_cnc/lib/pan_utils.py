import logging
import os
from pathlib import Path
from xml.etree import ElementTree as et

import pan.xapi
from django.conf import settings
from django.core.cache import cache
from jinja2 import Environment, BaseLoader

from pan_cnc.lib.exceptions import TargetConnectionException

xapi_obj = None

logger = logging.getLogger()
logger.setLevel(logging.WARN)

handler = logging.StreamHandler()
logger.addHandler(handler)


def panorama_login(panorama_ip=None, panorama_username=None, panorama_password=None):
    global xapi_obj
    try:
        if xapi_obj is None:
            print('xapi not init yet')
            credentials = get_panorama_credentials(panorama_ip, panorama_username, panorama_password)
            xapi_obj = pan.xapi.PanXapi(**credentials)
            if 'api_key' not in credentials:
                print('Setting API KEY')
                api_key = xapi_obj.keygen()
                cache.set('panorama_api_key', api_key, timeout=300)
        else:
            print('Found it in memory!')

        return xapi_obj

    except pan.xapi.PanXapiError as pxe:
        print('Got error logging in to Panorama')
        print(pxe)
        # reset to None here to force re-auth next time
        xapi_obj = None
        return None


def test_panorama():
    xapi = panorama_login()
    xapi.op(cmd='show system info', cmd_xml=True)
    print(xapi.xml_result())


def get_panorama_credentials(panorama_ip, panorama_username, panorama_password):
    if panorama_ip is None or panorama_username is None or panorama_password is None:
        # check the env for it if not here
        panorama_ip = os.environ.get('PANORAMA_IP', '0.0.0.0')
        panorama_username = os.environ.get('PANORAMA_USERNAME', 'admin')
        panorama_password = os.environ.get('PANORAMA_PASSWORD', 'admin')

    credentials = dict()
    credentials["hostname"] = panorama_ip
    credentials["api_username"] = panorama_username
    credentials["api_password"] = panorama_password

    api_key = cache.get('panorama_api_key')
    if api_key is not None:
        print('Using API KEY')
        credentials['api_key'] = api_key

    print(credentials)
    return credentials


def push_service(service, context):
    xapi = panorama_login()

    if xapi is None:
        print('Could not login in to Panorama')
        return False

    if 'snippet_path' in service:
        snippets_dir = service['snippet_path']
    else:
        snippets_dir = Path(os.path.join(settings.BASE_DIR, 'mssp', 'snippets', service['name']))

    try:
        for snippet in service['snippets']:
            xpath = snippet['xpath']
            xml_file_name = snippet['file']

            xml_full_path = os.path.join(snippets_dir, xml_file_name)
            with open(xml_full_path, 'r') as xml_file:
                xml_string = xml_file.read()
                xml_template = Environment(loader=BaseLoader()).from_string(xml_string)
                xpath_template = Environment(loader=BaseLoader()).from_string(xpath)
                xml_snippet = xml_template.render(context).replace('\n', '')
                xpath_string = xpath_template.render(context)
                print('Pushing xpath: %s' % xpath_string)
                xapi.set(xpath=xpath_string, element=xml_snippet)
                if xapi.status_code == '19' or xapi.status_code == '20':
                    print('xpath is already present')
                elif xapi.status_code == '7':
                    print('xpath was NOT found')
                    return False

        xapi.commit('<commit/>', sync=True)
        print(xapi.xml_result())
        return True

    except IOError as ioe:
        print('Could not open xml snippet file for reading!!!')
        # FIXME - raise a decent error here
        return False

    except pan.xapi.PanXapiError as pxe:
        print('Could not push service snippet!')
        print(pxe)
        return False


def validate_snippet_present(service, context):
    """
    Checks all xpaths in the service to validate if they are already present in panorama
    Status codes documented here:
        https://www.paloaltonetworks.com/documentation/71/pan-os/xml-api/pan-os-xml-api-error-codes
    :param service: dict of service params generared by snippet_utils.load_snippet_with_name()
    :param context: dict containing all jinja variables as key / value pairs
    :return: boolean True if found, false if any xpath is not found
    """
    xapi = panorama_login()
    if xapi is None:
        print('Could not login to Panorama')
        raise TargetConnectionException

    try:
        for snippet in service['snippets']:
            xpath = snippet['xpath']
            xpath_template = Environment(loader=BaseLoader()).from_string(xpath)
            xpath_string = xpath_template.render(context)
            xapi.get(xpath=xpath_string)
            if xapi.status_code == '19' or xapi.status_code == '20':
                print('xpath is already present')
            elif xapi.status_code == '7':
                print('xpath was NOT found')
                return False

        # all xpaths were found
        return True

    except pan.xapi.PanXapiError as pxe:
        print('Could not validate snippet was present!')
        print(pxe)
        raise TargetConnectionException


def get_device_groups_from_panorama():
    xapi = panorama_login()
    device_group_xpath = "/config/devices/entry[@name='localhost.localdomain']/device-group"

    services = list()

    try:
        xapi.get(device_group_xpath)
        xml = xapi.xml_result()
    except pan.xapi.PanXapiError as pxe:
        print('Could not get device groups from Panorama')
        print(pxe)
        return services

    doc = et.fromstring(xml)
    for dg in doc:
        if 'name' in dg.attrib:
            service = dict()
            for tag in dg.findall('./tag/entry'):
                if 'name' in tag.attrib and ':' in tag.attrib['name']:
                    k, v = tag.attrib['name'].split(':')
                    service[k] = v
                    service['name'] = dg.attrib['name']

            services.append(service)

    return services


def get_vm_auth_key_from_panorama():
    xapi = panorama_login()
    try:
        xapi.op(cmd='<request><bootstrap><vm-auth-key><generate>'
                    '<lifetime>2</lifetime></generate></vm-auth-key></bootstrap></request>')
        print(xapi.status_code)
        print(xapi.status_detail)
        return xapi.xml_result()
    except pan.xapi.PanXapiError as pxe:
        print('Could not get vm-auth-key!')
        print(pxe)
        raise TargetConnectionException
