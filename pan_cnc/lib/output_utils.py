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
import xml.etree.ElementTree as elementTree
from base64 import urlsafe_b64encode
from xml.etree.ElementTree import ParseError

from jsonpath_ng import parse

from pan_cnc.lib.exceptions import CCFParserError


def parse_outputs(meta: dict, snippet: dict, results: str) -> dict:
    """
    Parse the results object and return a list of outputs as defined in the meta-cnc structure
    Example:
    - name: system_info
        path: /api/?type=op&cmd=<show><system><info></info></system></show>&key={{ api_key }}
        output_type: xml
        outputs:
          - name: hostname
            capture_pattern: result/system/hostname
          - name: uptime
            capture_pattern: result/system/uptime
          - name: sw_version
            capture_pattern: result/system/sw-version

    JSON Example:
  - name: addresses
    path: https://{{ TARGET_IP }}/restapi/9.0/Objects/Addresses?location=vsys&vsys=vsys1&key={{ api_key }}
    output_type: json
    outputs:
      - name: addresses
        capture_pattern: $.result.entry[*].'@name'
    """
    outputs = dict()

    if 'outputs' not in snippet:
        print(f"No outputs defined in meta-cnc.yaml for skillet {meta['name']}")
        return outputs

    if 'output_type' not in snippet:
        print(f"No output_type defined in meta-cnc.yaml for skillet {meta['name']}")
        return outputs

    if snippet['output_type'] == 'xml':
        outputs = _handle_xml_outputs(snippet, results)
    elif snippet['output_type'] == 'base64':
        outputs = _handle_base64_outputs(snippet, results)
    elif snippet['output_type'] == 'json':
        outputs = _handle_json_outputs(snippet, results)
    elif snippet['output_type'] == 'text':
        # FR: allow output_type = 'text'
        outputs = _handle_text_outputs(snippet, results)

    return outputs


def _handle_text_outputs(snippet: dict, results: str) -> dict:
    """
    Parse the results string as a text blob into a single variable.

    - name: system_info
      path: /api/?type=op&cmd=<show><system><info></info></system></show>&key={{ api_key }}
      output_type: text
      outputs:
        - name: system_info_as_xml

    :param snippet: snippet definition from the Skillet
    :param results: results string from the action
    :return: dict of outputs, in this case a single entry
    """
    snippet_name = snippet['name']
    outputs = dict()

    if 'outputs' not in snippet:
        print('No outputs defined in this snippet')
        return outputs

    outputs_config = snippet.get('outputs', [])
    first_output = outputs_config[0]
    output_name = first_output.get('name', snippet_name)
    outputs[output_name] = results
    return outputs


def _handle_xml_outputs(snippet: dict, results: str) -> dict:
    """
    Parse the results string as an XML document
    Example .meta-cnc snippets section:
    snippets:

  - name: system_info
    path: /api/?type=op&cmd=<show><system><info></info></system></show>&key={{ api_key }}
    output_type: xml
    outputs:
      - name: hostname
        capture_pattern: result/system/hostname
      - name: uptime
        capture_pattern: result/system/uptime
      - name: sw_version
        capture_pattern: result/system/sw-version

    :param snippet: snippet definition from the .meta-cnc snippets section
    :param results: string as returned from some action, to be parsed as XML document
    :return: dict containing all outputs found from the capture pattern in each output
    """
    outputs = dict()

    snippet_name = 'unknown'
    if 'name' in snippet:
        snippet_name = snippet['name']

    try:
        xml_doc = elementTree.fromstring(results)
        if 'outputs' not in snippet:
            print('No outputs defined in this snippet')
            return outputs

        for output in snippet['outputs']:
            if 'name' not in output or 'capture_pattern' not in output:
                continue

            var_name = output['name']
            capture_pattern = output['capture_pattern']
            # FR #81 - add ability to capture list from output
            # outputs[var_name] = xml_doc.findtext(capture_pattern)
            print(results)
            entries = xml_doc.findall(capture_pattern)
            print(entries)
            if len(entries) == 1:
                outputs[var_name] = entries.pop().text
            else:
                capture_list = list()
                for entry in entries:
                    print('checking entry')
                    print(entry)
                    print(elementTree.tostring(entry))
                    capture_list.append(entry.text)

                outputs[var_name] = capture_list

    except ParseError:
        print('Could not parse XML document in output_utils')
        # just return blank outputs here
        raise CCFParserError(f'Could not parse output as XML in {snippet_name}')

    return outputs


def _handle_base64_outputs(snippet: dict, results: str) -> dict:
    """
    Parses results and returns a dict containing base64 encoded values
    :param snippet: snippet definition from the .meta-cnc snippets section
    :param results: string as returned from some action, to be encoded as base64
    :return: dict containing all outputs found from the capture pattern in each output
    """

    outputs = dict()

    snippet_name = 'unknown'

    if 'name' in snippet:
        snippet_name = snippet['name']

    try:
        if 'outputs' not in snippet:
            print(f'No output defined in this snippet {snippet_name}')
            return outputs

        for output in snippet['outputs']:
            if 'name' not in output:
                continue

            results_as_bytes = bytes(results, 'utf-8')
            encoded_results = urlsafe_b64encode(results_as_bytes)
            var_name = output['name']
            outputs[var_name] = encoded_results.decode('utf-8')

    except TypeError:
        raise CCFParserError(f'Could not base64 encode results {snippet_name}')

    return outputs


def _handle_json_outputs(snippet: dict, results: str) -> dict:
    outputs = dict()

    snippet_name = 'unknown'

    if 'name' in snippet:
        snippet_name = snippet['name']

    try:
        if 'outputs' not in snippet:
            print(f'No output defined in this snippet {snippet_name}')
            return outputs

        for output in snippet['outputs']:
            if 'name' not in output:
                print('malformed outputs in skillet definition')
                continue

            json_object = json.loads(results)
            var_name = output['name']
            # Fix for #96 - allow default capture pattern of the root object
            capture_pattern = output.get('capture_pattern', '$')
            jsonpath_expr = parse(capture_pattern)
            result = jsonpath_expr.find(json_object)
            if len(result) == 1:
                outputs[var_name] = result[0].value
            else:
                # FR #81 - add ability to capture from a list
                capture_list = list()
                for r in result:
                    capture_list.append(r.value)

                outputs[var_name] = capture_list

    except ValueError as ve:
        print('Caught error converting results to json')
        outputs['system'] = str(ve)
    except Exception as e:
        print('Unknown exception here!')
        print(e)
        outputs['system'] = str(e)

    return outputs
