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

"""
Palo Alto Networks pan-cnc

pan-cnc is a library to build simple GUIs and workflows primarily to interact with various APIs

Please see http://github.com/PaloAltoNetworks/pan-cnc for more information

This software is provided without support, warranty, or guarantee.
Use at your own risk.
"""

import datetime
import logging
import os
import re
from xml.etree import ElementTree as elementTree

import pan.xapi
from django.core.cache import cache
from jinja2 import BaseLoader
from jinja2 import Environment
from jinja2.exceptions import UndefinedError

from pan_cnc.lib import jinja_filters
from pan_cnc.lib.exceptions import CCFParserError
from pan_cnc.lib.exceptions import TargetCommitException
from pan_cnc.lib.exceptions import TargetConnectionException
from pan_cnc.lib.exceptions import TargetGenericException
from pan_cnc.lib.exceptions import TargetLoginException

xapi_obj = None

logger = logging.getLogger()
logger.setLevel(logging.WARN)

handler = logging.StreamHandler()
logger.addHandler(handler)


def panos_login(pan_device_ip=None, pan_device_username=None, pan_device_password=None) -> (pan.xapi.PanXapi, None):
    """
    Similar to panos_login_verbose but hide exceptions and returns None on errors
    :param pan_device_ip:
    :param pan_device_username:
    :param pan_device_password:
    :return: pan.xapi object or None on error
    """

    try:
        return panos_login_verbose(pan_device_ip, pan_device_username, pan_device_password)
    except TargetConnectionException:
        return None
    except TargetLoginException:
        return None
    except pan.xapi.PanXapiError:
        return None


def panos_login_verbose(pan_device_ip=None, pan_device_username=None, pan_device_password=None) -> pan.xapi.PanXapi:
    """
    Using the pan-xapi to log in to a PAN-OS or Panorama instance. If supplied ip, username, and password are None
    this will attempt to find them via environment variables 'PANORAMA_IP', 'PANORAMA_USERNAME', and 'PANORAMA_PASSWORD'
    :param pan_device_ip: ip address of the target instance
    :param pan_device_username: username to use
    :param pan_device_password: password to use
    :return: PanXapi object
    """
    global xapi_obj
    # if pan_device_ip is not None:
    if xapi_obj is not None:
        if pan_device_ip is not None:
            if xapi_obj.hostname == pan_device_ip and xapi_obj.api_username == pan_device_username \
                    and xapi_obj.api_password == pan_device_password:
                # an IP was specified and we have already connected to it
                # oterhwise, fall through to get credentials and do another connection attempt
                print('Returning cached xapi object')
                return xapi_obj
            else:
                print('Clearing old PanXapi credentials')
                xapi_obj = None
                cache.set('panorama_api_key', None)

        else:
            # no new credentials passed, but we have already connected, return the current connection
            return xapi_obj
    try:
        print(f'performing xapi init for {pan_device_ip}')
        credentials = get_panos_credentials(pan_device_ip, pan_device_username, pan_device_password)
        xapi_obj = pan.xapi.PanXapi(**credentials)
        if 'api_key' not in credentials:
            print('Setting API KEY')
            api_key = xapi_obj.keygen()
            cache.set('panorama_api_key', api_key, timeout=300)

        return xapi_obj

    except pan.xapi.PanXapiError as pxe:
        print('Error logging in to Palo Alto Networks device')
        print(pxe)
        err_msg = str(pxe)

        xapi_obj = None
        cache.set('panorama_api_key', None)

        if '403' in err_msg:
            raise TargetLoginException('Invalid credentials logging into device')
        elif 'Errno 111' in err_msg:
            raise TargetConnectionException('Error contacting the device at the given IP / hostname')
        elif 'Errno 60' in err_msg:
            raise TargetConnectionException('Error contacting the device at the given IP / hostname')
        else:
            raise TargetGenericException(pxe)


def test_panorama() -> None:
    """
    test PAN-OS device auth from environment variables
    :return: None
    """
    xapi = panos_login()
    xapi.op(cmd='show system info', cmd_xml=True)
    print(xapi.xml_result())


def get_panos_credentials(pan_device_ip, pan_device_username, pan_device_password) -> dict:
    """
    Returns a dict containing the panorama or PAN-OS credentials. If supplied args are None, attempt to load them
    via the Environment.
    :param pan_device_ip:
    :param pan_device_username:
    :param pan_device_password:
    :return:
    """
    if pan_device_ip is None or pan_device_username is None or pan_device_password is None:
        # check the env for it if not here
        # FIXME - this should be renamed to TARGET or some other value that is not specific to PANORAMA
        pan_device_ip = os.environ.get('PANORAMA_IP', '0.0.0.0')
        pan_device_username = os.environ.get('PANORAMA_USERNAME', 'admin')
        pan_device_password = os.environ.get('PANORAMA_PASSWORD', 'admin')

    credentials = dict()
    credentials["hostname"] = pan_device_ip
    credentials["api_username"] = pan_device_username
    credentials["api_password"] = pan_device_password

    api_key = cache.get('panorama_api_key', None)
    if api_key is not None:
        print('Using API KEY')
        credentials['api_key'] = api_key

    print(credentials)
    return credentials


def push_service(meta, context, force_sync=False, perform_commit=True) -> bool:
    """
    push_service is a wrapper around push_meta for API compatibility
    :param meta: loaded skillet
    :param context: user_inputs and secrets
    :param force_sync: should we wait for the commit to complete
    :param perform_commit: should we actually commit at all
    :return: bool - True on success, False on failure
    """
    try:
        push_meta(meta, context, force_sync, perform_commit)
    except CCFParserError:
        return False

    return True


def push_meta(meta, context, force_sync=False, perform_commit=True) -> (str, None):
    """
    Push a skillet to a PanXapi connected device
    :param meta: dict containing parsed and loaded skillet
    :param context: all compiled variables from the user interaction
    :param force_sync: should we wait on a successful commit operation or return after queue
    :param perform_commit: should we actually commit or not
    :return: job_id as a str or None if no job_id could be found
    """
    xapi = panos_login()

    if xapi is None:
        raise CCFParserError('Could not login in to Palo Alto Networks Device')

    name = meta['name'] if 'name' in meta else 'unknown'

    # default to None as return value, set to job_id if possible later if a commit was requested
    return_value = None

    # _perform_backup()
    if 'snippet_path' in meta:
        snippets_dir = meta['snippet_path']
    else:
        raise CCFParserError(f'Could not locate .meta-cnc file on filesystem for Skillet: {name}')

    try:
        for snippet in meta['snippets']:
            if 'xpath' not in snippet or 'file' not in snippet:
                print('Malformed meta-cnc error')
                raise CCFParserError(f'Malformed snippet section in meta-cnc file for {name}')

            xpath = snippet['xpath']
            xml_file_name = snippet['file']

            xml_full_path = os.path.join(snippets_dir, xml_file_name)
            with open(xml_full_path, 'r') as xml_file:
                xml_string = xml_file.read()
                environment = Environment(loader=BaseLoader())

                for f in jinja_filters.defined_filters:
                    if hasattr(jinja_filters, f):
                        environment.filters[f] = getattr(jinja_filters, f)

                xml_template = environment.from_string(xml_string)
                xpath_template = environment.from_string(xpath)
                xml_snippet = xml_template.render(context).replace('\n', '')
                xpath_string = xpath_template.render(context)
                print('Pushing xpath: %s' % xpath_string)
                try:
                    xapi.set(xpath=xpath_string, element=xml_snippet)
                    if xapi.status_code == '19' or xapi.status_code == '20':
                        print('xpath is already present')
                    elif xapi.status_code == '7':
                        raise CCFParserError(f'xpath {xpath_string} was NOT found for skillet: {name}')
                except pan.xapi.PanXapiError as pxe:
                    raise CCFParserError(
                        f'Could not push skillet {name} / snippet {xml_file_name}! {pxe}'
                    )
        if perform_commit:

            if 'type' not in meta:
                commit_type = 'commit'
            else:
                if 'panorama' in meta['type']:
                    commit_type = 'commit-all'
                else:
                    commit_type = 'commit'

            if commit_type == 'commit-all':
                print('Performing commit-all in panorama')
                xapi.commit(cmd='<commit-all></commit-all>', sync=True)
            else:
                if force_sync:
                    xapi.commit('<commit></commit>', sync=True)
                else:
                    xapi.commit('<commit></commit>')

            results = xapi.xml_result()
            if force_sync:
                # we have the results of a job id query, the commit results are embedded therein
                doc = elementTree.XML(results)
                embedded_result = doc.find('result')
                if embedded_result is not None:
                    commit_result = embedded_result.text
                    print(f'Commit result is {commit_result}')
                    if commit_result == 'FAIL':
                        raise TargetCommitException(xapi.status_detail)
            else:
                if 'with jobid' in results:
                    result = re.match(r'.* with jobid (\d+)', results)
                    if result is not None:
                        return_value = result.group(1)

            # for gpcs baseline and svc connection network configuration do a scope push to gpcs
            # FIXME - check for 'gpcs' in meta['type'] instead of hardcoded name
            if meta['name'] == 'gpcs_baseline':
                print('push baseline and svc connection scope to gpcs')
                xapi.commit(action='all',
                            cmd='<commit-all><template-stack>'
                                '<name>Service_Conn_Template_Stack</name></template-stack></commit-all>')
                print(xapi.xml_result())

            # for gpcs remote network configuration do a scope push to gpcs
            if meta['name'] == 'gpcs_remote' or meta['name'] == 'gpcs_baseline':
                print('push remote network scope to gpcs')
                xapi.commit(action='all',
                            cmd='<commit-all><shared-policy><device-group>'
                                '<entry name="Remote_Network_Device_Group"/>'
                                '</device-group></shared-policy></commit-all>')
                print(xapi.xml_result())

        return return_value

    except UndefinedError as ue:
        raise CCFParserError(f'Undefined variable in skillet: {ue}')

    except IOError as ioe:
        raise CCFParserError(f'Could not open xml snippet file for reading! {ioe}')

    except pan.xapi.PanXapiError as pxe:
        raise CCFParserError(f'Could not push meta-cnc for skillet {name}! {pxe}')


def debug_meta(meta: dict, context: dict) -> dict:
    rendered_snippets = dict()

    if 'snippet_path' in meta:
        snippets_dir = meta['snippet_path']
    else:
        return rendered_snippets

    for snippet in meta['snippets']:
        if 'xpath' not in snippet or 'file' not in snippet:
            print('Malformed meta-cnc error')
            raise CCFParserError

        xpath = snippet['xpath']
        xml_file_name = snippet['file']
        snippet_name = snippet['name']

        try:
            xml_full_path = os.path.abspath(os.path.join(snippets_dir, xml_file_name))
            with open(xml_full_path, 'r') as xml_file:
                xml_string = xml_file.read()
                environment = Environment(loader=BaseLoader())

                for f in jinja_filters.defined_filters:
                    if hasattr(jinja_filters, f):
                        environment.filters[f] = getattr(jinja_filters, f)

                xml_template = environment.from_string(xml_string)
                xpath_template = environment.from_string(xpath)
                xml_snippet = xml_template.render(context)
                xpath_string = xpath_template.render(context)
                rendered_snippets[snippet_name] = dict()
                rendered_snippets[snippet_name]['xpath'] = xpath_string
                rendered_snippets[snippet_name]['xml'] = xml_snippet
        except FileNotFoundError:
            err = f'Could not find file from path: {xml_full_path} from snippet: {snippet_name}'
            print(err)
            raise CCFParserError(err)
        except OSError:
            err = f'Unknown Error loading snippet: {snippet_name} from file {xml_file_name}'
            print(err)
            raise CCFParserError(err)

    return rendered_snippets


def validate_snippet_present(service, context) -> bool:
    """
    Checks all xpaths in the service to validate if they are already present in panorama
    Status codes documented here:
        https://www.paloaltonetworks.com/documentation/71/pan-os/xml-api/pan-os-xml-api-error-codes
    :param service: dict of service params generared by snippet_utils.load_snippet_with_name()
    :param context: dict containing all jinja variables as key / value pairs
    :return: boolean True if found, false if any xpath is not found
    """
    xapi = panos_login()
    if xapi is None:
        print('Could not login to Palo Alto Networks device')
        raise TargetConnectionException

    try:
        for snippet in service['snippets']:
            if 'xpath' not in snippet:
                print('Malformed meta-cnc error')
                raise CCFParserError

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


def get_device_groups_from_panorama() -> list:
    """
    Return a list of device groups from panorama instance
    :return: List of dicts containing device group entries
    """
    xapi = panos_login()
    device_group_xpath = "/config/devices/entry[@name='localhost.localdomain']/device-group"

    services = list()

    try:
        xapi.get(device_group_xpath)
        xml = xapi.xml_result()
    except pan.xapi.PanXapiError as pxe:
        print('Could not get device groups from Panorama')
        print(pxe)
        return services

    doc = elementTree.fromstring(xml)
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


def get_vm_auth_key_from_panorama() -> str:
    """
    Queries a Panorama instance to generate a new VM Auth key
    :return: string results from panorama (still needs parsed to pull out raw auth key)
    """
    xapi = panos_login()

    if xapi is None:
        print('Could not login into PAN-OS target')
        raise TargetConnectionException

    try:
        xapi.op(cmd='<request><bootstrap><vm-auth-key><generate>'
                    '<lifetime>24</lifetime></generate></vm-auth-key></bootstrap></request>')
        # FIXME - check status code here and do the right thing
        print(xapi.status_code)
        print(xapi.status_detail)
        return xapi.xml_result()
    except pan.xapi.PanXapiError as pxe:
        print('Could not get vm-auth-key!')
        print(pxe)
        raise TargetConnectionException


def perform_backup() -> str:
    """
    Saves a named backup on the PAN-OS device. The format for the backup is 'panhandler-20190424000000.xml'
    :return:  xml results from the op command sequence
    """
    xapi = panos_login()
    d = datetime.datetime.today()
    tstamp = d.strftime('%Y%m%d%H%M%S')
    cmd = f'<save><config><to>panhandler-{tstamp}.xml</to></config></save>'
    try:
        xapi.op(cmd=cmd)
        return xapi.xml_result()
    except pan.xapi.PanXapiError as pxe:
        raise TargetConnectionException(f'Could not perform backup: {pxe}')
