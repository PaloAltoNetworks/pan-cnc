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


import json
import os

import requests
from jinja2 import BaseLoader
from jinja2 import Environment
from urllib3.exceptions import HTTPError
from requests.exceptions import MissingSchema
from requests.exceptions import RequestException

from pan_cnc.lib import jinja_filters
from pan_cnc.lib import output_utils
from pan_cnc.lib.exceptions import CCFParserError


def execute_all(meta_cnc, app_dir, context):
    """
    Performs all REST operations defined in this meta-cnc file
    Each 'snippet' in the 'snippets' stanza in the .meta-cnc file will be executed in turn
    each entry in the 'snippets' stanza MUST have at least:
        'name', 'rest_path', and 'rest_operation'
    For a POST operation it must also include a 'payload' key

    * The path can include jinja2 variables as well as the payload file. Both will be interpolated before executing
    This allows things like the hostname, etc to be captured in the variables or target section

    :param meta_cnc: a parsed .meta-cnc.yaml file (self.service in class based Views)
    :param app_dir: which app_dir is this (panhandler, vistoq, etc) defined as self.app_dir on view classes
    :param context: fully populated workflow from the calling view (self.get_workflow() on the view class)
    :return: string suitable for presentation to the user
    """
    if 'snippet_path' in meta_cnc:
        snippets_dir = meta_cnc['snippet_path']
    else:
        # snippets_dir = Path(os.path.join(settings.BASE_DIR, app_dir, 'snippets', meta_cnc['name']))
        raise CCFParserError('Could not locate .meta-cnc for REST execution')

    response = dict()
    response['status'] = 'success'
    response['message'] = 'A-OK'
    response['snippets'] = dict()

    session = requests.Session()

    # create our jinja env and load filters only once
    environment = Environment(loader=BaseLoader())

    for f in jinja_filters.defined_filters:
        if hasattr(jinja_filters, f):
            environment.filters[f] = getattr(jinja_filters, f)

    try:
        # execute our rest call for each item in the 'snippets' stanza of the meta-cnc file
        for snippet in meta_cnc['snippets']:
            if 'path' not in snippet:
                print('Malformed meta-cnc error')
                raise CCFParserError

            name = snippet.get('name', '')

            # allow snippets to be skipped using the 'when' attribute
            if 'when' in snippet:
                when_template = environment.from_string(snippet.get('when', ''))
                when_result = str(when_template.render(context))
                if when_result.lower() == 'false' or when_result.lower() == 'no':
                    print(f'Skipping snippet {name} due to when condition false')
                    continue

            rest_path = snippet.get('path', '/api').strip().replace('\n', '').replace(' ', '')
            rest_op = str(snippet.get('operation', 'get')).lower()
            payload_name = snippet.get('payload', '')
            header_dict = snippet.get('headers', dict())

            # fix for issue #42
            if type(header_dict) is not dict:
                header_dict = dict()

            # FIXME - implement this to give some control over what will be sent to rest server
            content_type = snippet.get('content_type', '')
            accepts_type = snippet.get('accepts_type', '')

            headers = dict()
            if content_type:
                headers["Content-Type"] = content_type

            if accepts_type:
                headers['Accepts-Type'] = accepts_type

            path_template = environment.from_string(rest_path)
            url = path_template.render(context)

            for k, v in header_dict.items():
                v_template = environment.from_string(v)
                v_interpolated = v_template.render(context)
                print(f'adding {k} as {v_interpolated} to headers')
                headers[k] = v_interpolated

            # keep track of response text or json object
            r = ''
            if rest_op == 'post' and payload_name != '':
                payload_path = os.path.join(snippets_dir, payload_name)
                with open(payload_path, 'r') as payload_file:
                    payload_string = payload_file.read()
                    payload_template = environment.from_string(payload_string)
                    payload_interpolated = payload_template.render(context)
                    if 'Content-Type' in headers and 'form' in headers['Content-Type']:
                        print('Loading json data from payload')
                        try:
                            payload = json.loads(payload_interpolated)
                        except ValueError:
                            print('Could not load payload as json data!')
                            payload = payload_interpolated
                    else:
                        payload = payload_interpolated

                    res = session.post(url, data=payload, verify=False, headers=headers)
                    if res.status_code != 200:
                        print('Found a non-200 response status_code!')
                        print(res.status_code)
                        response['snippets'][name] = res.text
                        response['status'] = 'error'
                        response['message'] = res.status_code
                        break

                    if res.headers.get('content-type') == 'application/json':
                        try:
                            r = res.json()
                        except ValueError:
                            print('Could not parse JSON response from request')
                            r = res.text
                    else:
                        r = res.text

            elif rest_op == 'get':
                print(f'Performing REST get for snippet: {name}')
                res = session.get(url, verify=False)
                if res.headers.get('content-type') == 'application/json':
                    try:
                        r = res.json()
                    except ValueError:
                        r = res.text
                else:
                    r = res.text

                if res.status_code != 200:
                    response['status'] = 'error'
                    response['message'] = res.status_code
                    response['snippets'][name] = r
                    break

            else:
                print('Unknown REST operation found')
                response['status'] = 'Error'
                response['message'] = 'Unknown REST operation found'
                return response

            # collect the response text or json and continue
            response['snippets'][name] = dict()
            response['snippets'][name]['results'] = r
            response['snippets'][name]['outputs'] = dict()

            if 'outputs' in snippet:
                outputs = output_utils.parse_outputs(meta_cnc, snippet, r)
                response['snippets'][name]['outputs'] = outputs
                context.update(outputs)

        # return all the collected response
        return response

    except HTTPError as he:
        response['status'] = 'error'
        response['message'] = str(he)
        return response
    except requests.exceptions.ConnectionError as ce:
        response['status'] = 'error'
        response['message'] = str(ce)
        return response
    except MissingSchema as ms:
        response['status'] = 'error'
        response['message'] = ms
        return response
    except RequestException as re:
        response['status'] = 'error'
        response['message'] = re
        return response

