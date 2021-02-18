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

import copy
import json
import os
import re
import tempfile
from collections import OrderedDict
from typing import Any

from celery.result import AsyncResult
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.validators import MaxLengthValidator
from django.core.validators import MaxValueValidator
from django.core.validators import MinLengthValidator
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
from django.core.validators import URLValidator
from django.forms import Form
from django.forms import fields
from django.forms.widgets import CheckboxSelectMultiple
from django.forms.widgets import EmailInput
from django.forms.widgets import HiddenInput
from django.forms.widgets import NumberInput
from django.forms.widgets import PasswordInput
from django.forms.widgets import RadioSelect
from django.forms.widgets import Textarea
from django.http import JsonResponse
from django.shortcuts import HttpResponse
from django.shortcuts import HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import RedirectView
from django.views.generic import TemplateView
from django.views.generic import View
from django.views.generic.edit import FormView
from skilletlib import SkilletLoader
from skilletlib.exceptions import LoginException
from skilletlib.exceptions import PanoplyException
from skilletlib.exceptions import TargetConnectionException
from skilletlib.exceptions import TargetGenericException
from skilletlib.panoply import Panos
from skilletlib.skillet.panos import PanosSkillet
from skilletlib.skillet.python3 import Python3Skillet
from skilletlib.skillet.rest import RestSkillet
from skilletlib.snippet.workflow import WorkflowSnippet

from pan_cnc.lib import cnc_utils
from pan_cnc.lib import db_utils
from pan_cnc.lib import git_utils
from pan_cnc.lib import output_utils
from pan_cnc.lib import snippet_utils
from pan_cnc.lib import task_utils
from pan_cnc.lib import widgets
from pan_cnc.lib.exceptions import CCFParserError
from pan_cnc.lib.exceptions import SnippetRequiredException
from pan_cnc.lib.validators import Cidr
from pan_cnc.lib.validators import FqdnOrIp
from pan_cnc.lib.validators import JSONValidator
from pan_cnc.tasklibs import docker_utils


class CNCBaseAuth(LoginRequiredMixin, View):
    """
    Base Authentication Mixin - This can be overrode to provide some specific authentication implementation
    """
    login_url = '/login'
    app_dir = ''
    header = ''

    # always gets called on authenticated views
    def dispatch(self, request, *args, **kwargs):
        if self.app_dir != '':
            self.request.session['current_app_dir'] = self.app_dir

        else:
            self.app_dir = self.request.session.get('current_app_dir', '')

        if request.method.lower() == 'get':
            if 'last_page' not in self.request.session:
                print('Seeding last_page session attribute')
                self.request.session['last_page'] = '/'

        return super().dispatch(request, *args, **kwargs)

    def save_workflow_to_session(self) -> None:
        """
        Save the current user input to the session
        :return: None
        """
        if self.app_dir in self.request.session:
            print('updating workflow')
            current_workflow = self.request.session[self.app_dir]

        elif 'current_app_dir' in self.request.session:
            if self.request.session['current_app_dir'] in self.request.session:
                current_workflow = self.request.session[self.app_dir]

            else:
                current_workflow = dict()

        else:
            print('saving new workflow')
            current_workflow = dict()

        if hasattr(self, 'service') and self.service is not None:

            if 'variables' in self.service and self.service['variables'] is not None and \
                    type(self.service['variables']) is list:

                for variable in self.service['variables']:
                    if not isinstance(variable, dict):
                        continue

                    var_name = variable['name']
                    var_type = variable['type_hint']

                    if var_type == 'hidden' or var_type == 'disabled':
                        # fix for https://gitlab.com/panw-gse/as/panhandler/-/issues/45
                        # do not care about hidden values and adding back into workflow, for non-text hidden values
                        # such as list, this will cause the list to be inserted as a json string
                        # hidden values are only rendered to be used as a source for dynamic entries anyway
                        # per https://github.com/PaloAltoNetworks/panhandler/issues/192

                        # additional fix for https://gitlab.com/panw-gse/as/panhandler/-/issues/135
                        # add the default values to the context, but ignore what may arrive from the form
                        # further, do not overwrite values that may already be there, i.e. from another captured_output
                        if var_name not in current_workflow:
                            current_workflow[var_name] = variable.get('default', '')

                        continue

                    elif var_type == 'file':
                        try:

                            if var_name in self.request.FILES:
                                f = self.request.FILES[var_name]
                                d = self.service.get('snippet_path', None)
                                tmp_fd, tmp_file = tempfile.mkstemp(prefix='.cnc_tmp_', dir=d)

                                with open(tmp_file, 'wb+') as destination:
                                    for chunk in f.chunks():
                                        destination.write(chunk)

                                os.close(tmp_fd)
                                current_workflow[var_name] = tmp_file

                                # keep track of uploaded files and attempt to delete them on logout
                                uploaded_files = self.request.session.get('uploads', list())
                                uploaded_files.append(tmp_file)

                                self.request.session['uploads'] = uploaded_files

                        except OSError as ose:
                            print('Could not save file!')
                            print(ose)
                            raise RuntimeError('Could not save file')

                        continue

                    if var_name in self.request.POST:
                        # fix for #64 handle checkbox as list

                        if var_type == 'list' or var_type == 'checkbox':
                            var_as_list = self.request.POST.getlist(var_name, list())
                            var_as_list.sort()
                            current_workflow[var_name] = var_as_list

                        else:
                            current_workflow[var_name] = self.request.POST.get(var_name)

                    else:
                        if var_type in ['checkbox', 'list']:
                            current_workflow[var_name] = []

                        elif var_type == 'text' and variable.get('source', False):
                            # we have multiple fields here, let's grab all the values and store them in a dict
                            source = current_workflow.get(variable.get('source', []))

                            if source is None:
                                current_workflow[var_name] = dict()
                                continue

                            user_inputs = dict()
                            if isinstance(source, list):
                                source.sort()

                                for item in source:
                                    item_name = f'{var_name}_{item}'
                                    if item_name in self.request.POST:
                                        user_inputs[item] = self.request.POST.get(item_name)
                            else:
                                user_inputs[source] = self.request.POST.get(f'{var_name}_{source}', '')

                            current_workflow[var_name] = user_inputs

            # ensure we always capture the current snippet if set on this class!
            if self.snippet != '':
                current_workflow['snippet_name'] = self.snippet

        self.request.session[self.app_dir] = current_workflow

    def save_value_to_workflow(self, var_name, var_value) -> None:
        """
        Save a specific key value pair to the current workflow session cache

        :param var_name: variable name to use
        :param var_value: value of the variable to store
        :return: None
        """

        workflow = self.get_workflow()
        workflow[var_name] = var_value
        self.request.session[self.app_dir] = workflow
        self.request.session.modified = True

    def save_dict_to_workflow(self, dict_to_save: dict) -> None:
        """
        Saves all values from a dict into the session_cache / workflow
        :param dict_to_save: a dict of key / value pairs to save
        :return: None
        """

        workflow = self.get_workflow()
        for k in dict_to_save:
            workflow[k] = dict_to_save[k]

        # explicitly set this here
        self.request.session[self.app_dir] = workflow

    def get_workflow(self) -> dict:
        """
        Return the workflow from the session cache
        :return:
        """
        if self.app_dir in self.request.session:
            return self.request.session[self.app_dir]
        else:
            self.request.session[self.app_dir] = dict()
            return self.request.session[self.app_dir]

    def get_snippet_variables_from_workflow(self, skillet=None):
        """
        Returns only the values from the context or the currently loaded environment
        for each variable in the skillet

        :param skillet: optional skillet dict to include
        :return: dict containing the variables defined in the skillet with values from the context or the env
        """

        if skillet is None:
            skillet = {}
        combined_workflow = self.get_snippet_context()
        snippet_vars = dict()

        if skillet == {}:
            if hasattr(self, 'service'):
                skillet = self.service
            elif hasattr(self, 'meta'):
                skillet = self.meta
            else:
                return snippet_vars

        if 'variables' in skillet and skillet['variables'] is not None and \
                type(skillet['variables']) is list:

            for variable in skillet['variables']:
                if 'name' not in variable:
                    continue
                var_name = variable['name']
                if var_name in combined_workflow:
                    snippet_vars[var_name] = combined_workflow[var_name]
                else:
                    # always grab all variables even if hidden
                    snippet_vars[var_name] = variable['default']

        return snippet_vars

    def get_snippet_context(self) -> dict:
        """
        Convenience method to return the current workflow and env secrets in a single context
        useful for rendering snippets that require values from both

        :return: dict containing env secrets and workflow values
        """

        context = dict()
        context.update(self.get_environment_secrets())
        context.update(self.get_workflow())
        return context

    def get_terraform_context(self) -> dict:
        """
        Legacy terraform projects still expect to have access to the full context, so we need get_snippet_context
        However, we also need any hidden or disabled variables from the skillet as well, so pull in
        get_snippet_variables_from_workflow as well

        :return: dict containing full context + skillet variables with default values
        """
        combined_vars = self.get_snippet_context()

        snippet_vars = self.get_snippet_variables_from_workflow()

        combined_vars.update(snippet_vars)

        return combined_vars

    def get_value_from_workflow(self, var_name: str, default=None) -> Any:
        """
        Return the variable value either from the workflow (if it's already been saved there)
        or from the environment, if it happens to be configured there

        :param var_name: name of variable to find and return
        :param default: default value if nothing has been saved to the workflow or configured in the environment
        :return: value of variable
        """
        session_cache = self.get_workflow()
        secrets = self.get_environment_secrets()

        if var_name in secrets:
            return secrets[var_name]
        elif var_name in session_cache:
            return session_cache[var_name]
        else:
            return default

    def pop_value_from_workflow(self, var_name, default='') -> Any:
        """
        Return the variable value either from the workflow (if it's already been saved there)
        or the default. If found, go ahead and remove it,

        :param var_name: name of variable to find and return
        :param default: default value if nothing has been saved to the workflow or configured in the environment
        :return: value of variable
        """

        return self.get_workflow().pop(var_name, default)

    def get_environment_secrets(self) -> dict:
        """
        Returns a dict containing the currently loaded environment secrets

        :return: dict with key value pairs of secrets
        """
        default = dict()
        if 'environments' not in self.request.session or 'current_env' not in self.request.session:
            return default

        current_env = self.request.session['current_env']
        if current_env not in self.request.session['environments']:
            print('Environments are incorrectly loaded')
            return default

        e = self.request.session['environments'][current_env]
        if 'secrets' not in e:
            print('Environment secrets are incorrectly loaded')
            return default

        if type(e['secrets']) is not dict:
            return default

        return e['secrets']

    def get_value_from_environment(self, var_name, default) -> Any:
        """
        Return the specified value from the environment secrets dict

        :param var_name: name of the key to lookup
        :param default: what to return if the key was not found
        :return: value of the specified secret key
        """
        if 'environments' not in self.request.session or 'current_env' not in self.request.session:
            return default

        current_env = self.request.session['current_env']
        if current_env not in self.request.session['environments']:
            print('Environments are incorrectly loaded')
            return default

        e = self.request.session['environments'][current_env]
        if 'secrets' not in e:
            print('Environment secrets are incorrectly loaded')
            return default

        if var_name in e['secrets']:
            return e['secrets'][var_name]
        else:
            print('Not found in ENV, returning default')
            return default

    def page_title(self):
        default = 'PAN CNC'
        app_dir = ''

        if 'app_dir' in self.request.session:
            app_dir = self.request.session.get('app_dir', '')
        elif 'current_app_dir' in self.request.session:
            app_dir = self.request.session.get('current_app_dir', '')
        elif self.app_dir != '':
            app_dir = self.app_dir

        if app_dir != '':
            app_config = cnc_utils.get_app_config(app_dir)
            if 'label' in app_config:
                return app_config['label']
            elif 'name' in app_config:
                return app_config['name']
            else:
                return default

        return default

    def get_header(self) -> str:
        workflow_name = self.request.session.get('workflow_name', None)
        next_step = self.request.session.get('workflow_ui_step', None)

        header = self.header
        if workflow_name is not None:
            workflow_skillet_dict = self.load_skillet_by_name(workflow_name)

            if workflow_skillet_dict is not None:
                workflow_label = workflow_skillet_dict.get('label', self.header)
                if hasattr(self, 'meta') and isinstance(self.meta, dict):
                    skillet_label = self.meta.get('label', '')
                elif hasattr(self, 'service') and isinstance(self.service, dict):
                    skillet_label = self.service.get('label', '')
                elif self.get_value_from_workflow('snippet_name', None) is not None:
                    skillet_label = self.get_value_from_workflow('snippet_name')
                else:
                    skillet_label = ''

                if skillet_label == '':
                    header = workflow_label
                else:
                    header = f'{workflow_label} / {skillet_label}'

        if next_step is None:
            return header
        else:
            return f"Step {next_step}: {header}"

    def clean_up_workflow(self) -> None:
        self.request.session.pop('next_step', None)
        self.request.session.pop('last_step', None)
        self.request.session.pop('next_url', None)
        self.request.session.pop('workflow_ui_step', None)
        self.request.session.pop('workflow_name', None)
        self.request.session.pop('workflow_skillet', None)

    def error_out(self, message: str) -> str:
        messages.add_message(self.request, messages.ERROR, message)
        # clean up any workflow related items
        self.clean_up_workflow()
        # try to grab a sensible next page to redirect to
        next_url = self.request.session.pop('last_page', '/')
        return next_url

    def load_skillet_by_name(self, skillet_name) -> (dict, None):
        """
        Default method to load a skillet by name, child applications can override how skillets are found, stored, and
        cached, so we will let them override this method to provide their own functionality

        :param skillet_name: name of the skillet to load (from the name attribute in the metadata file)
        :return: skillet metadata dict if not found
        """

        # if a workflow skillet is found on the session, check if the name matches and return if so. This
        # ensures skillets required for a workflow that may be from a submodule are preferred over other
        # skillets that may have the same name
        workflow_skillet = self.request.session.get('workflow_skillet', {})
        if skillet_name == workflow_skillet.get('name', ''):
            return workflow_skillet

        return snippet_utils.load_snippet_with_name(skillet_name, self.app_dir)


class CNCView(CNCBaseAuth, TemplateView):
    """
    Base View that only renders a template. Use or override this class if you want to include a custom
    HTML page in your app
    """
    template_name = "pan_cnc/index.html"
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    help_text = ''

    def set_last_page_visit(self) -> None:
        """
        Called on all templateView children (CNCView). Will track the last page visited. Override this in children
        to not track that pageview

        By default always called on get_context_data

        :return: None
        """
        print(f'Capturing last page visit to {self.request.path}')
        self.request.session['last_page'] = self.request.path

    def get_context_data(self, **kwargs):
        """
        This gets called just before the template is rendered. Use this to add any data to the context dict that will
        be passed to the template. Any keys defined in the context dict will be directly available in the template.
        context['test'] = '123' can be accessed like so in an HTML template:
        <p>The value of test is {{ test }}</p>

        :param kwargs:
        :return: dict
        """
        context = super().get_context_data(**kwargs)
        context['base_html'] = self.base_html
        context['app_dir'] = self.app_dir

        self.set_last_page_visit()

        return context


class CNCBaseFormView(CNCBaseAuth, FormView):
    """
    Base class for most CNC view functions. Will find a 'snippet' from either the POST or the session cache
    and load it into a 'service' attribute.
    GET will create a dynamic form based on the loaded snippet
    POST will save all user input into the session and redirect to next_url

    Variables defined in __init__ are instance specific variables while variables defined immediately following
    this docstring are class specific variables and will be shared with child classes

    """
    # base form class, you should not need to override this
    form_class = Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'PAN-OS Utils'
    # title to show on dynamic form
    title = 'Title'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = None
    # the action of the form if it needs to differ (it shouldn't)
    action = '/'
    # the app dir should match the app name and is used to load app specific snippets
    app_dir = ''
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = ''
    # help link is a link that will provide more context to the user
    help_link_title = ''
    help_link = ''
    # where to redirect to
    success_url = '/'

    def __init__(self, **kwargs):
        # fields to render and fields to filter should never be shared to child classes
        # list of fields to NOT render in this instance
        self._fields_to_filter = list()
        # list of fields to ONLY render in this instance - only eval'd if fields_to_filter is blank or []
        self._fields_to_render = list()

        # currently loaded service should also never be shared
        self._service = dict()
        # name of the snippet to find and load into the service
        self._snippet = ''

        # dict of form values to pre-populate if not found in the session/workflow
        self.prepopulated_form_values = dict()
        # call the super
        super().__init__(**kwargs)

    @property
    def fields_to_render(self) -> list:
        return self._fields_to_render

    @fields_to_render.setter
    def fields_to_render(self, value):
        self._fields_to_render = value

    @property
    def fields_to_filter(self):
        return self._fields_to_filter

    @fields_to_filter.setter
    def fields_to_filter(self, value):
        self._fields_to_filter = value

    @property
    def service(self):
        return self._service

    @service.setter
    def service(self, value):
        self._service = value

    @property
    def snippet(self):
        return self._snippet

    @snippet.setter
    def snippet(self, value):
        self._snippet = value

    def get_snippet(self):
        """
        This is always called on both GET and POST. Most of the time, the snippet attribute will be set directly
        in the pan_cnc.yaml file. However, there are times where the snippet is dynamically chosen by the user
        so it will only be available in the POSTed data, or possibly saved in the session previously
        :return:
        """
        print('Getting snippet here in CNCBaseFormView:get_snippet')
        if 'snippet_name' in self.request.POST:
            print('found snippet defined in the POST')
            self.snippet = self.request.POST['snippet_name']

        elif self.snippet != '':
            return self.snippet

        elif self.app_dir in self.request.session:
            session_cache = self.request.session[self.app_dir]

            if 'snippet_name' in session_cache:
                print('found snippet defined in the session')
                self.snippet = session_cache['snippet_name']

        # default case is to use the snippet defined directly on the class
        print(f'Returning snippet: {self.snippet}')
        return self.snippet

    def get_context_data(self, **kwargs) -> dict:
        """
        Loads relevant configuration into the context for the page render
        :param kwargs:
        :return:
        """

        context = dict()

        if 'form' in kwargs:
            # this is being called from a validation error!
            form = kwargs['form']

        else:
            # Generate the dynamic form based on the snippet name found and returned from get_snippet
            form = self.generate_dynamic_form()

        context['form'] = form
        context['header'] = self.header
        context['title'] = self.title
        context['base_html'] = self.base_html
        context['app_dir'] = self.app_dir
        context['snippet_name'] = self.get_snippet()
        context['view'] = self

        return context

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests:
            This will show the form. Get the current snippet, load and parse the snippet, get the context
            including the dynamically generated form, then render the page
        """
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        try:
            snippet: str = self.get_snippet()

            if snippet != '':
                self.service: dict = self.load_skillet_by_name(snippet)

                if self.service is None:
                    messages.add_message(self.request, messages.ERROR,
                                         f'Process Error - Snippet with name: {snippet} not found')
                    return HttpResponseRedirect('/')

                # always render the form for pan_validation as this type will dynamically add fields
                if self.service.get('type', '') == 'pan_validation':
                    return self.render_to_response(self.get_context_data())

                # if we have NO variables or only hidden variables, then continue right to the post
                # otherwise, we need to render the form field
                for v in self.service.get('variables', []):
                    if v.get('type_hint', 'text') != 'hidden':
                        return self.render_to_response(self.get_context_data())

                return self.post(request)

            else:
                messages.add_message(self.request, messages.ERROR, 'Process Error - Snippet not found')
                return HttpResponseRedirect('/')

        except SnippetRequiredException:
            print('Snippet was not defined here!')
            messages.add_message(self.request, messages.ERROR, 'Process Error - Snippet not found')
            return HttpResponseRedirect('/')

        except CCFParserError:
            print('Could not load CCF Metadata!')
            messages.add_message(self.request, messages.ERROR, 'Process Error - Could not load CCF')
            return HttpResponseRedirect('/')

    def post(self, request, *args, **kwargs) -> Any:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid. If valid, save variables to the session
        and call form_valid
        """
        self.service = self.load_skillet_by_name(self.get_snippet())
        form = self.generate_dynamic_form(self.request.POST)

        try:

            if form.is_valid():
                # load the snippet into the class attribute here so it's available to all other methods throughout the
                # call chain in the child classes
                # go ahead and save all our current POSTed variables to the session for use later
                self.save_workflow_to_session()

                return self.form_valid(form)

            else:
                print('This form is not valid!')
                return self.form_invalid(form)

        except (TypeError, KeyError) as te:
            print('Caught error checking Form input values')
            print(te)
            messages.add_message(self.request, messages.ERROR, 'Could not validate Form')
            return self.form_invalid(form)

    def render_snippet_template(self) -> str:
        """
        Convenience method to render the defined snippet. By default this will render the first snippet defined in the
        metdata.xml file. An optional argument can be added to render a specific file if desired
        :return: string containing rendered snippet template
        """

        if 'variables' not in self.service:
            print('Service not loaded on this class!')
            return ''

        template = snippet_utils.render_snippet_template(self.service, self.app_dir, self.get_workflow())
        return template

    @staticmethod
    def __get_choice_list_from_source(source_list: (list, str)) -> list:
        """
        Internal method to return a list of tuples from the supplied source option.

        This allows some flexibility for the builder. The following syntax is now supported:
        source:
          - interface1
          - interface2

        source:
          - key: some key
            value: some value
          - key: another key
            value: another value

        source:
          - random_key_name: some key
            random_value_name: some value
          - random_key_name: another key
            random_value_name: another value

        :param source_list:
        :return:
        """

        def __get_choice_from_item(this_item: Any) -> tuple:
            """ private method to get a choice tuple from the item """

            if isinstance(this_item, dict):
                keys = [*this_item]
                if 'key' in keys and 'value' in keys:
                    return this_item['value'], this_item['key']
                elif len(keys) >= 2:
                    return this_item[keys[1]], this_item[keys[0]]

            elif isinstance(this_item, str):
                return this_item, this_item

            return ()

        choices_list = list()
        if isinstance(source_list, list):
            # source_list.sort()

            for item in source_list:
                choice = __get_choice_from_item(item)

                if choice:
                    choices_list.append(choice)

        else:
            choice = __get_choice_from_item(source_list)
            if choice:
                choices_list.append(choice)

        return choices_list

    def generate_dynamic_form(self, data=None) -> Form:
        """
        The heart of this class. This will generate a Form object based on the value of the self.snippet
        All variables defined in a snippet .meta-cnc.yaml file will be converted into a form field depending on it's
        type_hint. The initial value of the variable will be the value of the 'default' key defined in the metadata file
        or the value of a secret from the currently loaded environment if it contains the same name.

        :return: Form object
        """
        dynamic_form = Form(data=data)

        if self.service is None:
            # A GET call will find and load a snippet, then use the snippet_utils library to load that snippet
            # into the self.service attribute
            print('There is no metadata defined here :-/')
            return dynamic_form

        if not isinstance(self.service, dict):
            print('Metadata incorrectly loaded or defined')
            return dynamic_form

        if 'variables' not in self.service:
            print('No variables defined in metadata')
            return dynamic_form

        if self.service['variables'] is None:
            print('No variables defined in metadata')
            return dynamic_form

        if type(self.service['variables']) is not list:
            print('Malformed variables defined in metadata')
            return dynamic_form

        if 'type' not in self.service:
            print('No type defined in metadata')
            return dynamic_form

        # Get all of the variables defined in the self.service
        for variable in self.service['variables']:
            if type(variable) is not OrderedDict:

                if type(variable) is not dict:
                    print('Variable configuration is incorrect')
                    print(type(variable))
                    continue

            if len(self.fields_to_filter) != 0:
                if variable['name'] in self.fields_to_filter:
                    print('Skipping render of variable %s' % variable['name'])
                    continue

            elif len(self.fields_to_render) != 0:
                if variable['name'] not in self.fields_to_render:
                    print('Skipping render of variable %s' % variable['name'])
                    continue

            required_keys = {'name', 'description'}

            if not required_keys.issubset(variable.keys()):
                print('Variable does not contain required keys: name, description')
                continue

            field_name = variable.get('name', '')

            if type(field_name) is not str and type(field_name) is not int:
                print('Variable name is not a str')
                continue

            type_hint = variable.get('type_hint', 'text')
            description = variable.get('description', '')
            variable_default = variable.get('default', '')

            if not variable_default:
                variable_default = ''

            required = variable.get('required', False)
            force_default = variable.get('force_default', False)

            help_text = variable.get('help_text', '')

            if force_default:
                print('Using variable as default')
                default = variable_default

            else:
                # if the user has entered this before, let's grab it from the session
                default = self.get_value_from_workflow(field_name, None)
                # not entered before, do we have it in the prepopulated_form_values dict?
                if default is None:
                    if field_name in self.prepopulated_form_values:
                        default = self.prepopulated_form_values[field_name]
                    else:
                        default = variable_default

            # Figure out which type of widget should be rendered
            # Valid widgets are dropdown, text_area, password and defaults to a char field
            if type_hint == 'dropdown' and 'dd_list' in variable:
                dd_list = variable['dd_list']
                choices_list = list()

                for item in dd_list:
                    if 'key' in item and 'value' in item:

                        if default == item['key'] and default != item['value']:
                            # user set the key as the default and not the value, just fix it for them here
                            default = item['value']

                        choice = (item['value'], item['key'])
                        choices_list.append(choice)

                dynamic_form.fields[field_name] = fields.ChoiceField(choices=tuple(choices_list), label=description,
                                                                     initial=default, required=required,
                                                                     help_text=help_text)

            # FR #85 - Add dynamic dropdown / radio / checkbox
            elif type_hint == 'dropdown' and 'source' in variable:
                source = variable.get('source', None)
                source_list = self.get_value_from_workflow(source, None)
                if source_list is not None:

                    choices_list = self.__get_choice_list_from_source(source_list)

                    dynamic_form.fields[field_name] = fields.ChoiceField(choices=tuple(choices_list), label=description,
                                                                         initial=default, required=required,
                                                                         help_text=help_text)

                else:
                    # if source is empty, then render a text input only...
                    dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                       initial=default,
                                                                       required=required,
                                                                       help_text=help_text)

            elif type_hint == "text_area" or type_hint == 'textarea':
                # Fix for FR: #97 - add rows / cols to text_area
                attrs = dict()

                if 'attributes' in variable and type(variable['attributes']) is dict:
                    attrs['rows'] = variable['attributes'].get('rows', 10)
                    attrs['cols'] = variable['attributes'].get('cols', 40)

                dynamic_form.fields[field_name] = fields.CharField(widget=Textarea(attrs=attrs), label=description,
                                                                   initial=default, required=required,
                                                                   help_text=help_text)
            elif type_hint == 'json':

                # Fix for #176 - add rows / cols to json
                attrs = dict()

                if 'attributes' in variable and type(variable['attributes']) is dict:
                    attrs['rows'] = variable['attributes'].get('rows', 10)
                    attrs['cols'] = variable['attributes'].get('cols', 40)

                dynamic_form.fields[field_name] = fields.CharField(widget=Textarea(attrs=attrs), label=description,
                                                                   initial=default, required=required,
                                                                   validators=[JSONValidator],
                                                                   help_text=help_text)
            elif type_hint == "list":
                attrs = dict()
                attrs['data-widget_type'] = 'list'
                dynamic_form.fields[field_name] = fields.CharField(widget=widgets.ListInput(attrs=attrs),
                                                                   label=description,
                                                                   initial=default, required=required,
                                                                   help_text=help_text)
            elif type_hint == "email":
                dynamic_form.fields[field_name] = fields.CharField(widget=EmailInput, label=description,
                                                                   initial=default, required=required,
                                                                   help_text=help_text)
            elif type_hint == "ip_address":
                dynamic_form.fields[field_name] = fields.GenericIPAddressField(label=description,
                                                                               initial=default, required=required,
                                                                               help_text=help_text)
            elif type_hint == "number":
                attrs = dict()

                if 'attributes' in variable:
                    if 'min' in variable['attributes'] and 'max' in variable['attributes']:
                        attrs['min'] = variable['attributes']['min']
                        attrs['max'] = variable['attributes']['max']
                        dynamic_form.fields[field_name] = fields.IntegerField(widget=NumberInput(attrs=attrs),
                                                                              label=description,
                                                                              initial=default, required=required,
                                                                              validators=[
                                                                                  MaxValueValidator(attrs['max']),
                                                                                  MinValueValidator(attrs['min'])],
                                                                              help_text=help_text)
                else:
                    dynamic_form.fields[field_name] = fields.IntegerField(widget=fields.NumberInput(),
                                                                          label=description,
                                                                          initial=default, required=required,
                                                                          help_text=help_text)
            # add support for float per #103
            elif type_hint == "float":
                attrs = dict()

                if 'attributes' in variable:
                    if 'min' in variable['attributes'] and 'max' in variable['attributes']:
                        attrs['min'] = variable['attributes']['min']
                        attrs['max'] = variable['attributes']['max']
                        dynamic_form.fields[field_name] = fields.FloatField(widget=fields.NumberInput(attrs=attrs),
                                                                            label=description,
                                                                            initial=default, required=required,
                                                                            validators=[
                                                                                MaxValueValidator(attrs['max']),
                                                                                MinValueValidator(attrs['min'])],
                                                                            help_text=help_text)
                else:
                    dynamic_form.fields[field_name] = fields.FloatField(widget=fields.NumberInput(),
                                                                        label=description,
                                                                        initial=default, required=required,
                                                                        help_text=help_text)

            elif type_hint == "fqdn_or_ip":
                dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                   initial=default,
                                                                   validators=[FqdnOrIp], required=required,
                                                                   help_text=help_text)

            elif type_hint == "cidr":
                dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                   initial=default,
                                                                   validators=[Cidr], required=required,
                                                                   help_text=help_text)
            elif type_hint == "password":
                dynamic_form.fields[field_name] = fields.CharField(widget=PasswordInput(render_value=True),
                                                                   initial=default,
                                                                   label=description, required=required,
                                                                   help_text=help_text)
            elif type_hint == "radio" and "rad_list" in variable:
                rad_list = variable['rad_list']
                choices_list = list()

                for item in rad_list:
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)

                dynamic_form.fields[field_name] = fields.ChoiceField(widget=RadioSelect, choices=choices_list,
                                                                     label=description, initial=default,
                                                                     required=required,
                                                                     help_text=help_text)
            # FR #85 - Add dynamic dropdown / radio / checkbox
            elif type_hint == "radio" and "source" in variable:
                source = variable.get('source', None)
                source_list = self.get_value_from_workflow(source, [])
                if source_list is not None:
                    choices_list = self.__get_choice_list_from_source(source_list)

                    dynamic_form.fields[field_name] = fields.ChoiceField(widget=RadioSelect, choices=choices_list,
                                                                         label=description, initial=default,
                                                                         required=required,
                                                                         help_text=help_text)
                else:
                    # if source is empty, then render a text input only...
                    dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                       initial=default,
                                                                       required=required,
                                                                       help_text=help_text)

            elif type_hint == "checkbox" and "cbx_list" in variable:
                cbx_list = variable['cbx_list']
                choices_list = list()

                for item in cbx_list:
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)
                dynamic_form.fields[field_name] = fields.MultipleChoiceField(widget=CheckboxSelectMultiple,
                                                                             choices=choices_list,
                                                                             label=description, initial=default,
                                                                             required=required,
                                                                             help_text=help_text)
            # FR #85 - Add dynamic dropdown / radio / checkbox
            elif type_hint == 'checkbox' and 'source' in variable:
                source = variable.get('source', None)
                source_list = self.get_value_from_workflow(source, [])
                if source_list is not None:
                    choices_list = self.__get_choice_list_from_source(source_list)

                    dynamic_form.fields[field_name] = fields.MultipleChoiceField(widget=CheckboxSelectMultiple,
                                                                                 choices=choices_list,
                                                                                 label=description, initial=default,
                                                                                 required=required,
                                                                                 help_text=help_text)
                else:
                    # if source is empty, then render a text input only...
                    dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                       initial=default,
                                                                       required=required,
                                                                       help_text=help_text)

            elif type_hint == 'disabled':
                dynamic_form.fields[field_name] = fields.CharField(label=description, initial=default,
                                                                   disabled=True, required=required,
                                                                   help_text=help_text)

            elif type_hint == 'file':
                dynamic_form.fields[field_name] = fields.FileField(label=description, required=required,
                                                                   help_text=help_text)

            elif type_hint == 'url':
                dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                   initial=default,
                                                                   required=required,
                                                                   validators=[
                                                                       URLValidator(message='Entry must be '
                                                                                            'a valid URL',
                                                                                    code='invalid_format')
                                                                   ],
                                                                   help_text=help_text)
            elif type_hint == 'hidden':
                # FIX for #192
                dynamic_form.fields[field_name] = fields.CharField(initial=default, required=False,
                                                                   widget=HiddenInput())
                # continue

            else:
                # default input type if text
                validators = list()
                if 'allow_special_characters' in variable and variable['allow_special_characters'] is False:
                    validators.append(RegexValidator(
                        regex=r'^[a-zA-Z0-9-_ \.]*$',
                        message='Only Letters, number, hyphens, '
                                'underscores and spaces are '
                                'allowed',
                        code='invalid_format'
                    ))
                if 'attributes' in variable:
                    if 'min' in variable['attributes'] and type(variable['attributes']['min']) is int:
                        validators.append(
                            MinLengthValidator(
                                variable['attributes']['min']
                            )
                        )
                    if 'max' in variable['attributes'] and type(variable['attributes']['max']) is int:
                        validators.append(
                            MaxLengthValidator(
                                variable['attributes']['max']
                            )
                        )
                # implement multiple inputs as a dict from a source list
                if 'source' in variable:
                    source = self.get_value_from_workflow(variable['source'], [])

                    # it's possible to have a single element list
                    if type(source) is not list:
                        item = source
                        source = list()
                        source.append(item)

                    source.sort()

                    for item in source:
                        if type(default) is dict and item in default:
                            item_value = default[item]
                        elif type(default) is dict:
                            # item is not in dict here
                            item_value = ''
                        else:
                            item_value = default
                        item_description = f'{description} {item}'
                        item_name = f'{field_name}_{item}'
                        dynamic_form.fields[item_name] = fields.CharField(label=item_description,
                                                                          initial=item_value,
                                                                          required=required,
                                                                          validators=validators,
                                                                          help_text=help_text)
                else:
                    dynamic_form.fields[field_name] = fields.CharField(label=description,
                                                                       initial=default,
                                                                       required=required,
                                                                       validators=validators,
                                                                       help_text=help_text)

                # fix for #118 - add ability to toggle visibility based on value of another field
            toggle_hint = variable.get('toggle_hint', {})

            #     toggle_hint:
            #       source: bgp_type
            #       value: disable
            # OR
            #     toggle_hint:
            #       source: bgp_type
            #       value:
            #         - value1
            #         - value2

            if toggle_hint != {} and type(toggle_hint) is dict:
                f = dynamic_form.fields[field_name]
                w = f.widget

                toggle_hint_value = toggle_hint.get('value', '')
                if type(toggle_hint_value) is list:
                    toggle_hint_value_str = ','.join(toggle_hint_value)
                else:
                    toggle_hint_value_str = toggle_hint_value

                w.attrs.update({'data-source': toggle_hint.get('source', '')})
                w.attrs.update({'data-value': toggle_hint_value_str})

        return dynamic_form

    def form_valid(self, form):
        """
        Called once the form has been submitted
        :param form: dynamic form
        :return: rendered html response or redirect
        """
        return HttpResponseRedirect(self.next_url)


class ChooseSnippetByLabelView(CNCBaseFormView):
    """

    A subclass of the CNCBaseFormView that adds a label_name and label_value attributes. This will
    load the form as it's parent, but will also override or add a form_field called 'snippet_name' with a
    dropdown list of all snippets found with a label_name with a value or label_value

    This is useful to build a form that allows the user to choose a snippet to load based on some arbitrary group
    of snippets (i.e. all snippets with a label like 'category: internet_service'

    """
    label_name = ''
    label_value = ''

    def get_snippet(self) -> str:
        """
        Always return a blank snippet name - ensure we do not pick up an old selection from the POST or session cache
        :return:
        """
        return ''

    def generate_dynamic_form(self, data=None):
        """
        Generates a form with only 1 option - snippet_name
        :return: Form Object
        """

        form = Form(data=data)
        if self.label_name == '' or self.label_value == '':
            print('No Labels to use to filter!')
            return form

        services = snippet_utils.load_snippets_by_label(self.label_name, self.label_value, self.app_dir)

        # we need to construct a new ChoiceField with the following basic format
        # snippet_name = fields.ChoiceField(choices=(('gold', 'Gold'), ('silver', 'Silver'), ('bronze', 'Bronze')))
        choices_list = list()
        # grab each service and construct a simple tuple with name and label, append to the list
        for service in services:
            choice = (service['name'], service['label'])
            choices_list.append(choice)

        # let's sort the list by the label attribute (index 1 in the tuple)
        choices_list = sorted(choices_list, key=lambda k: k[1])
        # convert our list of tuples into a tuple itself
        choices_set = tuple(choices_list)
        # make our new field
        new_choices_field = fields.ChoiceField(choices=choices_set, label='Template Name')
        # set it on the original form, overwriting the hardcoded GSB version

        form.fields['snippet_name'] = new_choices_field

        return form

    def post(self, request, *args, **kwargs) -> Any:
        """
        Parent class assumes a snippet has been loaded as a service already and uses that to capture all user input
        In most cases, a snippet chooser may not
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        form = self.get_form()

        if form.is_valid():
            if self.app_dir in self.request.session:
                current_workflow = self.request.session[self.app_dir]
            else:
                current_workflow = dict()

            if 'snippet_name' in self.request.POST:
                print('Adding snippet_name')
                current_workflow['snippet_name'] = self.request.POST.get('snippet_name')

            self.request.session[self.app_dir] = current_workflow

            return self.form_valid(form)
        else:
            return self.form_invalid(form)


class ChooseSnippetView(CNCBaseFormView):
    """

    A subclass of the CNCBaseFormView that adds a label_name and label_value attributes. This will
    load the form as it's parent, but will also override or add a form_field based on the value of the
    customize_field label with a dropdown list of all snippets found with a customize_label_name
    with a value of customize_label_value.

    This will also load all other form fields defined in the .meta-cnc.yaml file

    This is useful to build a form that allows the user to choose a snippet to load based on some arbitrary group
    of snippets (i.e. all snippets with a label like 'category: internet_service'

    """
    snippet = ''

    def get_snippet(self):
        return self.snippet

    def generate_dynamic_form(self, data=None):
        form = super().generate_dynamic_form(data=data)
        if self.service is None:
            return form

        if 'labels' in self.service \
                and isinstance(self.service['labels'], dict) \
                and 'customize_field' in self.service['labels']:
            labels = self.service['labels']
            if not {'customize_label_name', 'customize_label_value'}.issubset(labels):
                print('Malformed Configure Service Picker!')

            custom_field = labels['customize_field']
            label_name = labels['customize_label_name']
            label_value = labels['customize_label_value']
            services = snippet_utils.load_snippets_by_label(label_name, label_value, self.app_dir)
        else:
            custom_field = 'snippet_name'
            services = snippet_utils.load_snippets_of_type('service', self.app_dir)

        # we need to construct a new ChoiceField with the following basic format
        # snippet_name = fields.ChoiceField(choices=(('gold', 'Gold'), ('silver', 'Silver'), ('bronze', 'Bronze')))
        choices_list = list()
        # grab each service and construct a simple tuple with name and label, append to the list
        for service in services:
            choice = (service['name'], service['label'])
            choices_list.append(choice)

        # let's sort the list by the label attribute (index 1 in the tuple)
        choices_list = sorted(choices_list, key=lambda k: k[1])
        # convert our list of tuples into a tuple itself
        choices_set = tuple(choices_list)
        # make our new field
        new_choices_field = fields.ChoiceField(choices=choices_set, label='Template Name')
        # set it on the original form, overwriting the hardcoded GSB version

        form.fields[custom_field] = new_choices_field

        return form


class ProvisionSnippetView(CNCBaseFormView):
    """
    Provision Snippet View - This view uses the Base Auth and Form View
    The posted view is actually a dynamically generated form so the Form will actually be blank
    use form_valid as it will always be true in this case.
    """
    snippet = ''
    header = 'Execute Skillet'
    title = 'Customize Variables'

    def get_context_data(self, **kwargs):

        if self.service is not None and self.service != {}:

            if 'type' not in self.service:
                return super().get_context_data(**kwargs)

            if self.service['type'] == 'template':
                self.header = 'Render Template'
                self.title = f"Customize Template: {self.service['label']}"
            elif self.service['type'] == 'panos':
                self.header = 'PAN-OS Configuration'
                self.title = f"Customize PAN-OS Skillet: {self.service['label']}"
            elif self.service['type'] == 'panorama':
                self.header = 'Panorama Configuration'
                self.title = f"Customize Panorama Skillet: {self.service['label']}"
            elif self.service['type'] == 'terraform':
                self.header = 'Deploy with Terraform'
                self.title = self.service.get('label', '')
            elif self.service['type'] == 'pan_validation':
                self.header = 'Validate Configuration'
                self.title = self.service.get('label', '')
            elif self.service['type'] == 'rest':
                self.header = 'REST API'
                self.title = self.service.get('label', '')
            elif self.service['type'] == 'workflow':
                self.header = 'Workflow'
                self.title = self.service['label']

                # Make it a fresh start when doing a new workflow for #147
                if self.app_dir in self.request.session:
                    print('Clearing context for new workflow')
                    self.request.session[self.app_dir] = dict()

            else:
                # May need to add additional types here
                t = self.service['type']
                self.header = 'Provision'
                self.title = self.service.get('label', '')
                print(f'Found unknown type {t} for form customization in ProvisionSnippetView:get_context_data')

        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        service_name = self.get_value_from_workflow('snippet_name', '')

        # Check if the user has configured a snippet via the .pan-cnc.yaml file
        if self.snippet != '':
            service_name = self.snippet

        if service_name == '':
            # FIXME - add an ERROR page and message here
            print('No Service ID found!')
            return super().form_valid(form)

        if self.service is None:
            print('Unknown Error, Skillet was None')
            messages.add_message(self.request, messages.ERROR, 'Process Error - No Skillet was loaded')
            return self.form_invalid(form)

        if self.service['type'] == 'template':

            # fix for #40 - Use skilletlib or template type skillets to pick up inline type templates that use
            # 'element' instead of 'file'
            sl = SkilletLoader()
            template_skillet = sl.create_skillet(self.service)

            # make all variables available as top-level and also under the 'context' attribute for compatibility
            # with output_templates
            template_snippet_context = self.get_snippet_variables_from_workflow()
            template_context = dict()
            template_context['context'] = template_snippet_context
            template_context.update(template_snippet_context)

            try:
                results = template_skillet.execute(template_context)
            except BaseException as be:
                print(be)
                return HttpResponseRedirect(self.error_out(str(be)))

            output_template = results.get('template', '')

            snippet = template_skillet.snippet_stack[0]

            context = dict()
            context['output_template'] = output_template

            if not output_template.startswith('<div'):
                context['output_template_markup'] = False
            else:
                context['output_template_markup'] = True

            captured_outputs = False
            if 'outputs' in results and type(results['outputs']) is dict:
                if len(results['outputs']) > 0:
                    captured_outputs = True
                for k, v in results['outputs'].items():
                    self.save_value_to_workflow(k, v)

            context['captured_outputs'] = captured_outputs
            context['base_html'] = self.base_html

            self.header = f"Results for {self.service['label']}"
            if 'template_title' in snippet:
                context['title'] = snippet['template_title']
            else:
                context['title'] = "Rendered Output"

            context['results'] = output_template
            context['view'] = self
            return render(self.request, 'pan_cnc/results.html', context)

        elif self.service['type'] == 'rest':
            # Found a skillet type of 'rest'
            rest_skillet = RestSkillet(self.service)
            results = rest_skillet.execute(self.get_snippet_variables_from_workflow())

            context = dict()
            context['base_html'] = self.base_html
            # fix for #65 - show nicer output for rest type skillet
            context['results'] = json.dumps(results, indent=2)
            context['view'] = self
            skillet_label = self.service.get('label', 'Skillet')
            context['title'] = f'Successfully Executed {skillet_label}'

            if 'snippets' not in results:
                print('Result from rest_utils is malformed')
                messages.add_message(self.request, messages.ERROR, 'Could not successfully execute SKillet')
                return self.form_invalid(form)

            else:
                captured_outputs = False
                if 'outputs' in results and type(results['outputs']) is dict:
                    if len(results['outputs']) > 0:
                        captured_outputs = True
                    for k, v in results['outputs'].items():
                        self.save_value_to_workflow(k, v)

            context['captured_outputs'] = captured_outputs

            if 'output_template' in results:
                if not results['output_template'].startswith('<div'):
                    context['output_template_markup'] = False
                else:
                    context['output_template_markup'] = True

                context['output_template'] = results['output_template']

            return render(self.request, 'pan_cnc/results.html', context)

        elif self.service['type'] == 'python3':
            print('Launching python3 init')
            context = super().get_context_data()
            context['base_html'] = self.base_html

            if task_utils.python3_check_no_requirements(self.service):
                context['title'] = f"Executing Skillet: {self.service['label']}"
                r = task_utils.python3_execute_bare(self.service, self.get_snippet_variables_from_workflow())
                self.request.session['task_next'] = ''

            elif task_utils.python3_init_complete(self.service):
                context['title'] = f"Executing Skillet: {self.service['label']}"
                r = task_utils.python3_execute(self.service, self.get_snippet_variables_from_workflow())
                self.request.session['task_next'] = ''
            else:
                context['title'] = f"Preparing environment for: {self.service['label']}"
                context['auto_continue'] = True
                r = task_utils.python3_init(self.service)
                self.request.session['task_next'] = 'python3_execute'

            self.request.session['task_id'] = r.id
            self.request.session['task_app_dir'] = self.app_dir
            self.request.session['task_base_html'] = self.base_html
            return render(self.request, 'pan_cnc/results_async.html', context)

        elif self.service['type'] == 'workflow':
            # Found a skillet type of 'workflow'
            return HttpResponseRedirect('/workflow/0')
        elif self.service['type'] == 'terraform':
            self.request.session['next_url'] = self.next_url
            return HttpResponseRedirect('/terraform')

        elif self.service['type'] == 'docker':
            print('Launching Docker Skillet')
            context = super().get_context_data()
            context['base_html'] = self.base_html

            context['title'] = f"Executing Skillet: {self.service['label']}"
            r = task_utils.skillet_execute(self.service, self.get_snippet_variables_from_workflow())

            self.request.session['task_next'] = ''
            self.request.session['task_id'] = r.id
            self.request.session['task_app_dir'] = self.app_dir
            self.request.session['task_base_html'] = self.base_html
            return render(self.request, 'pan_cnc/results_async.html', context)

        elif self.service['type'] == 'panos':

            # init the panos_skillet type
            panos_skillet = PanosSkillet(self.service)
            # do we need to always how the target_ip, etc form?
            require_ui = False
            # check workflow first
            workflow_name = self.request.session.get('workflow_name', None)
            if workflow_name is None or workflow_name == '':
                # if we are NOT in a workflow, then we will always show the UI
                require_ui = True
            else:
                # we are in a workflow, so let's check if this is only going to do some op commands and such
                # any set or edit type commands will require a commit or backup option

                for snippet in panos_skillet.get_snippets():
                    if snippet.metadata.get('cmd') not in ('op', 'get', 'show', 'parse'):
                        # any other cmd types will require a commit or backup operation option shown to the user
                        require_ui = True
                        break

            if not require_ui:
                # verify we have what we need in the context
                if not {'TARGET_IP', 'TARGET_USERNAME', 'TARGET_PASSWORD'}.issubset(self.get_workflow().keys()):
                    require_ui = True

            if require_ui:
                # after all that, we need to ask the user some questions before we continue...
                self.request.session['next_url'] = self.next_url
                return HttpResponseRedirect('/editTarget')

            # no need to ask for information again, just run the skillet and print the results...
            try:
                p = Panos(api_username=self.get_value_from_workflow('TARGET_USERNAME', 'admin'),
                          api_password=self.get_value_from_workflow('TARGET_PASSWORD', 'admin'),
                          api_port=self.get_value_from_workflow('TARGET_PORT', 443),
                          hostname=self.get_value_from_workflow('TARGET_IP', ''),
                          )
            except TargetConnectionException:
                return HttpResponseRedirect(self.error_out('Connection Refused Error, check the IP and try again'))

            except LoginException:
                return HttpResponseRedirect(self.error_out(
                    'Invalid Credentials, ensure your username and password are correct'))

            except TargetGenericException as tge:
                return HttpResponseRedirect(self.error_out(f'Unknown Connection Error: {tge}'))

            except Exception as e:
                return HttpResponseRedirect(self.error_out(f'Unknown Connection Error: {e}'))

            panos_skillet.panoply = p
            panos_skillet.initialize_context(dict())

            outputs = panos_skillet.execute(self.get_snippet_variables_from_workflow())
            result = outputs.get('result', 'failure')
            if result != 'success':
                messages.add_message(self.request, messages.ERROR, 'Skillet did not execute successfully!')
                return self.form_invalid(form)

            # save outputs wherever possible
            captured_outputs = False
            if 'outputs' in outputs and type(outputs['outputs']) is dict:
                captured_outputs = True
                for k, v in outputs['outputs'].items():
                    self.save_value_to_workflow(k, v)

            context = dict()
            context['base_html'] = self.base_html
            context['results'] = json.dumps(outputs, indent=2)
            context['view'] = self
            context['title'] = f'Successfully Executed {self.service.get("label")}'
            context['captured_outputs'] = captured_outputs

            if 'output_template' in outputs:
                context['title'] = 'PAN-OS Skillet Results'
                output_template = outputs['output_template']
                context['output_template'] = output_template

                if not output_template.startswith('<div'):
                    context['output_template_markup'] = False
                else:
                    context['output_template_markup'] = True

            return render(self.request, 'pan_cnc/results.html', context)

        else:

            # CNC apps may create custom hard coded workflows by setting a 'next_url' attribute
            # in the .pan_cnc.yaml file. Let's make sure to capture this before redirecting to editTargetView
            self.request.session['next_url'] = self.next_url
            return HttpResponseRedirect('/editTarget')


class EditTargetView(CNCBaseAuth, FormView):
    """
    Edit or update the current target
    """
    # base form class, you should not need to override this
    form_class = Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/panos_target_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'PAN-OS Skillet'
    # title to show on dynamic form
    title = 'Title'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = None
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = 'The Target is the PAN-OS device where the configured template will be applied. ' \
                'The supplied username needs to have API access rights. \n\n Commit options allows you ' \
                'to control how the commit operation happens. A fast commit will queue the commit and return ' \
                'immediately with a job id. No commit will push configuration changes to the device but will not' \
                'perform a commit. Commit and wait to finish will only return after the commit operation has fully' \
                'completed. This may take some time depending on the platform, however you will immediately see any' \
                'commit or validation errors. \n\n Perform Backup will record a on-device backup prior to any changes' \
                'being pushed to the device. To view the backups, you may use the `load config from` CLI command.'
    help_link_title = 'More information'
    help_link = 'https://panhandler.readthedocs.io/en/master/using.html'

    meta = None

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests
            Ensure we have a snippet_name in the workflow somewhere, otherwise, we need to redirect out of here
            Fixes issue where a user goes to the editTarget URL directly
        """
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name == '':
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

        meta = self.load_skillet_by_name(snippet_name)
        if meta is None:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Could not load meta')

        self.meta = meta
        return self.render_to_response(self.get_context_data())

    def post(self, request, *args, **kwargs):
        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name == '':
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

        meta = self.load_skillet_by_name(snippet_name)
        if meta is None:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Could not load meta')
            return HttpResponseRedirect('/')

        self.meta = meta

        form = self.generate_dynamic_form(self.request.POST)

        try:
            if form.is_valid():
                # load the snippet into the class attribute here so it's available to all other methods throughout the
                # call chain in the child classes
                # go ahead and save all our current POSTed variables to the session for use later
                self.save_workflow_to_session()

                return self.form_valid(form)
            else:
                print('This form is not valid!')
                return self.form_invalid(form)
        except BaseException as te:
            messages.add_message(self.request, messages.ERROR, str(te))
            return self.form_invalid(form)

    def generate_dynamic_form(self, data=None) -> Form:

        form = Form(data=data)

        meta = self.meta
        if meta is None:
            raise SnippetRequiredException('Could not find a valid skillet!!')

        target_ip_label = 'Target IP'
        target_port_label = 'Target Port'
        target_username_label = 'Target Username'
        target_password_label = 'Target Password'
        if 'type' in meta:
            if meta['type'] == 'panos':
                target_ip_label = 'PAN-OS IP'
                target_username_label = 'PAN-OS Username'
                target_password_label = 'PAN-OS Password'
            elif meta['type'] == 'panorama':
                target_ip_label = 'Panorama IP'
                target_username_label = 'Panorama Username'
                target_password_label = 'Panorama Password'
            elif meta['type'] == 'panorama-gpcs':
                target_ip_label = 'Panorama IP'
                target_username_label = 'Panorama Username'
                target_password_label = 'Panorama Password'

        target_ip = self.get_value_from_workflow('TARGET_IP', '')
        target_port = self.get_value_from_workflow('TARGET_PORT', 443)
        target_username = self.get_value_from_workflow('TARGET_USERNAME', '')
        target_password = self.get_value_from_workflow('TARGET_PASSWORD', '')

        target_ip_field = fields.CharField(label=target_ip_label, initial=target_ip, required=True,
                                           validators=[FqdnOrIp])
        # FR #82 - Add port to EditTarget Screen
        target_port_field = fields.IntegerField(label=target_port_label, initial=target_port, required=True,
                                                validators=[
                                                    MaxValueValidator(65535),
                                                    MinValueValidator(0)])
        target_username_field = fields.CharField(label=target_username_label, initial=target_username, required=True)
        target_password_field = fields.CharField(widget=PasswordInput(render_value=True), required=True,
                                                 label=target_password_label,
                                                 initial=target_password)

        debug_field = fields.CharField(initial='False', widget=HiddenInput())

        form.fields['TARGET_IP'] = target_ip_field
        form.fields['TARGET_PORT'] = target_port_field
        form.fields['TARGET_USERNAME'] = target_username_field
        form.fields['TARGET_PASSWORD'] = target_password_field
        form.fields['debug'] = debug_field

        if 'type' in meta and 'pan' in meta['type']:
            # add option to perform commit operation or not
            saved_perform_commit = self.get_value_from_workflow('perform_commit', 'no_commit')
            saved_perform_backup = self.get_value_from_workflow('perform_backup', False)

            choices_list = list()

            choices_list.append(('no_commit', 'Do not Commit. Push changes only'))
            choices_list.append(('sync_commit', 'Commit and wait to finish'))

            choices_set = tuple(choices_list)

            # fix for #156 - only sync_commit for gpcs type skillets
            # fix for #204 - allow no_commit option for gpcs - gpcs can be sync_commit or not_commit onlu
            if 'gpcs' not in meta['type']:
                choices_list.append(('commit', 'Fast Commit. Do not wait on commit to finish'))

            perform_commit = fields.ChoiceField(choices=choices_set, label='Commit Options',
                                                initial=saved_perform_commit)

            form.fields['perform_commit'] = perform_commit

            perform_backup = fields.BooleanField(label='Perform Backup', initial=saved_perform_backup,
                                                 label_suffix='', required=False)

            form.fields['perform_backup'] = perform_backup

        return form

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')

        if 'form' in kwargs:
            form = kwargs.get('form')
        else:
            form = self.generate_dynamic_form()

        header = 'Edit Target'
        title = 'Configure Target information'

        meta = self.meta

        if 'label' in meta:
            header = f"Set Target for {meta['label']}"

        context['form'] = form
        context['base_html'] = self.base_html
        context['env_name'] = env_name
        context['header'] = header
        context['title'] = title
        return context

    def form_valid(self, form):
        """
        form_valid is always called on a blank / new form, so this is essentially going to get called on every POST
        self.request.POST should contain all the variables defined in the service identified by the hidden field
        'service_id'
        :param form: blank form data from request
        :return: render of a success template after service is provisioned
        """

        snippet_name = self.get_value_from_workflow('snippet_name', '')

        if snippet_name == '':
            return HttpResponseRedirect(self.error_out('No Skillet provided!'))

        meta = self.load_skillet_by_name(snippet_name)

        if meta is None:
            return HttpResponseRedirect(self.error_out('Could not load Skillet!'))

        # Grab the values from the form, this is always hard-coded in this class
        target_ip = self.request.POST.get('TARGET_IP', None)
        target_port = self.request.POST.get('TARGET_PORT', 443)
        target_username = self.request.POST.get('TARGET_USERNAME', None)
        target_password = self.request.POST.get('TARGET_PASSWORD', None)
        debug = self.request.POST.get('debug', False)

        # capture backup and commit preferences for future use
        if 'type' in meta and 'pan' in meta['type']:
            saved_perform_commit = self.request.POST.get('perform_commit', 'commit')
            saved_perform_backup = self.request.POST.get('perform_backup', False)
            self.save_value_to_workflow('perform_commit', saved_perform_commit)
            self.save_value_to_workflow('perform_backup', saved_perform_backup)

        self.save_value_to_workflow('TARGET_IP', target_ip)
        self.save_value_to_workflow('TARGET_PORT', target_port)
        self.save_value_to_workflow('TARGET_USERNAME', target_username)

        if debug == 'True' or debug is True:
            return self.debug_skillet(target_ip, target_username, target_password, meta, form)

        err_condition = False
        if target_ip is None or target_ip == '':
            form.add_error('TARGET_IP', 'Host entry cannot be blank')
            err_condition = True

        if target_username is None or target_username == '':
            form.add_error('TARGET_USERNAME', 'Username cannot be blank')
            err_condition = True

        if target_password is None or target_password == '':
            form.add_error('TARGET_PASSWORD', 'Password cannot be blank')
            err_condition = True

        if err_condition:
            return self.form_invalid(form)

        print(f'logging in to pan device with {target_ip}')
        try:

            p = Panos(api_username=target_username,
                      api_password=target_password,
                      api_port=target_port,
                      hostname=target_ip
                      )
        except TargetConnectionException:
            form.add_error('TARGET_IP', 'Connection Refused Error, check the IP and try again')
            return self.form_invalid(form)
        except LoginException:
            form.add_error('TARGET_USERNAME', 'Invalid Credentials, ensure your username and password are correct')
            form.add_error('TARGET_PASSWORD', 'Invalid Credentials, ensure your username and password are correct')
            return self.form_invalid(form)
        except TargetGenericException as tge:
            form.add_error('TARGET_IP', f'Unknown Connection Error: {tge}')
            return self.form_invalid(form)
        except Exception as e:
            form.add_error('TARGET_IP', f'Unknown Connection Error: {e}')
            return self.form_invalid(form)

        # check if type is 'panos' and if the user wants to perform a commit or not
        # check if perform commit is set
        perform_commit_str = self.request.POST.get('perform_commit', 'commit')

        perform_commit = False
        force_sync = False

        if perform_commit_str == 'commit':
            perform_commit = True
        elif perform_commit_str == 'no_commit':
            perform_commit = False
        elif perform_commit_str == 'sync_commit':
            perform_commit = True
            force_sync = True

        perform_backup_str = self.request.POST.get('perform_backup', 'off')
        perform_backup = False

        if perform_backup_str == 'on':
            perform_backup = True

        print(f'Got a perform_commit of {perform_commit}')
        if perform_backup:
            print('Performing configuration backup before Configuration Push')
            try:
                p.backup_config()
            except PanoplyException:
                return HttpResponseRedirect(self.error_out('Connected to Device but could not perform backup!'))

        try:
            panos_skillet = PanosSkillet(self.meta, p)
            outputs = panos_skillet.execute(self.get_snippet_variables_from_workflow())
            result = outputs.get('result', 'failure')
            # save outputs wherever possible
            if 'outputs' in outputs and type(outputs['outputs']) is dict:
                for k, v in outputs['outputs'].items():
                    self.save_value_to_workflow(k, v)

            if result != 'success':
                print(outputs)
                return HttpResponseRedirect(self.error_out('Could not execute Skillet on device!'))

            elif result == 'success' and perform_commit:
                commit_result = p.commit(force_sync)

                if force_sync:
                    messages.add_message(self.request, messages.SUCCESS, 'Configuration Pushed successfully')
                else:
                    # messages.add_message(self.request, messages.SUCCESS, 'Configuration Push Queued successfully')
                    jobid_match = re.match(r'.* with jobid (\d+)', commit_result)
                    if jobid_match is not None:
                        job_id = jobid_match.group(1)
                        if job_id is not None:
                            messages.add_message(self.request, messages.SUCCESS,
                                                 f'Configuration Push Queued successfully with Job ID: {job_id}')

                # check for gpcs skillet type and perform the appropriate commit option
                if 'gpcs' in self.meta['type']:
                    gpcs_commit_result = p.commit_gpcs(force_sync)
                    print(gpcs_commit_result)
                    if force_sync:
                        messages.add_message(self.request, messages.SUCCESS,
                                             'Prisma-Access Configuration Pushed successfully')
                    else:
                        messages.add_message(self.request, messages.SUCCESS,
                                             'Prisma-Access Configuration Queued successfully')

            else:
                if 'changed' in outputs and outputs['changed']:
                    messages.add_message(self.request, messages.SUCCESS,
                                         'Configuration added to Candidate Config successfully')
                else:
                    messages.add_message(self.request, messages.SUCCESS,
                                         'Skillet Executed Successfully with no changes')

        except PanoplyException as pe:
            return HttpResponseRedirect(self.error_out(f'Error Executing Skillet on Device! {pe}'))

        if 'output_template' in outputs:
            context = self.get_context_data()
            context['title'] = 'PAN-OS Skillet Results'
            output_template = outputs['output_template']
            context['output_template'] = output_template

            if not output_template.startswith('<div'):
                context['output_template_markup'] = False
            else:
                context['output_template_markup'] = True

            return render(self.request, 'pan_cnc/results.html', context=context)

        # fix for #72, in non-workflow case, revert to using our captured last_page visit
        # next_url = self.pop_value_from_workflow('next_url', None)
        next_step = self.request.session.get('next_step', None)
        if next_step is not None:
            # this is a workflow
            return HttpResponseRedirect(f'/workflow/{next_step}')

        # this is not a workflow, check for next_url captured in session
        next_url = self.request.session.get('next_url', None)
        if next_url is None:
            next_url = self.request.session.get('last_page', '/')
            return HttpResponseRedirect(next_url)

        print(f'Redirecting to {next_url}')
        return HttpResponseRedirect(f"{next_url}")

    def debug_skillet(self, target_ip, target_username, target_password, meta, form):
        context = dict()
        context['base_html'] = self.base_html
        changes = dict()
        try:
            initial_context = self.get_snippet_variables_from_workflow()

            initial_context['ip_address'] = target_ip
            initial_context['username'] = target_username
            initial_context['password'] = target_password

            # https://gitlab.com/panw-gse/as/panhandler/-/issues/32
            # Show when conditional output as well as variable parsing etc...
            sl = SkilletLoader()

            panos_skillet = sl.create_skillet(meta)

            try:
                # this will contact the device and gather information and grab the device config
                skillet_context = panos_skillet.initialize_context(initial_context)

            except TargetConnectionException as tce:
                messages.add_message(self.request, messages.ERROR, f'Could not authenticate to device: {tce}')
                return self.form_invalid(form)

            for snippet in panos_skillet.get_snippets():
                change = dict()

                snippet.render_metadata(skillet_context)
                changes[snippet.name] = change
                change['metadata'] = snippet.metadata
                change['json'] = json.dumps(snippet.metadata, indent=4)
                change['when'] = True

                if not snippet.should_execute(skillet_context):
                    change['message'] = 'This snippet would be skipped due to when conditional'
                    change['when'] = False
                    continue

                if 'cmd' in snippet.metadata and \
                        snippet.metadata['cmd'] in ('op', 'set', 'edit', 'override', 'move', 'rename',
                                                    'clone', 'delete'):

                    change['message'] = 'This destructive snippet would be executed'

                else:
                    try:
                        (output, status) = snippet.execute(skillet_context)
                        # capture all outputs
                        snippet_outputs = snippet.get_default_output(output, status)
                        captured_outputs = snippet.capture_outputs(output, status)

                        skillet_context.update(snippet_outputs)
                        skillet_context.update(captured_outputs)

                        change['message'] = 'This snippet was executed to gather results'
                        change['captured_outputs'] = captured_outputs
                        change['captured_outputs_json'] = json.dumps(captured_outputs, indent=4)

                    except PanoplyException as pe:
                        change['message'] = str(pe)

        except CCFParserError as cpe:
            label = meta['label']
            messages.add_message(self.request, messages.ERROR, f'Could not debug Skillet: {label}')
            context['results'] = str(cpe)
            return render(self.request, 'pan_cnc/results.html', context=context)

        context['results'] = changes
        context['meta'] = meta
        context['target_ip'] = target_ip
        self.request.session['last_page'] = f'/{self.app_dir}/skillet/{panos_skillet.name}'
        return render(self.request, 'pan_cnc/debug_panos_skillet.html', context=context)


class EditTerraformView(CNCBaseAuth, FormView):
    # base form class, you should not need to override this
    form_class = Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'Terraform'
    # title to show on dynamic form
    title = 'Choose the action to perform'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = None
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = 'Choose which action you would like to perform on the selected Terraform template.'

    # keep current skillet metadata around
    meta = dict()

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests
            Ensure we have a snippet_name in the workflow somewhere, otherwise, we need to redirect out of here
            Fixes issue where a user goes to the terraform URL directly
        """
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name != '':
            self.meta = self.load_skillet_by_name(snippet_name)
            return self.render_to_response(self.get_context_data())
        else:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')
        form = Form()

        default_choice = 'validate'
        choices_list = list()
        choices_list.append(('validate', 'Validate, Init, and Apply'))
        choices_list.append(('refresh', 'Refresh Current Status'))
        choices_list.append(('destroy', 'Destroy'))

        if task_utils.terraform_state_exists(self.meta):
            messages.add_message(self.request, messages.INFO,
                                 'Found existing Terraform State! Choose Manual Override to backup state and create a '
                                 'new Terraform State')
            choices_list.append(('override', 'Manual Override'))
            default_choice = 'override'

        choices_set = tuple(choices_list)
        terraform_action_list = fields.ChoiceField(choices=choices_set, label='Terraform Command Sequence',
                                                   initial=default_choice)
        form.fields['terraform_action'] = terraform_action_list
        context['form'] = form
        context['base_html'] = self.base_html
        context['env_name'] = env_name
        context['header'] = self.get_header()
        context['title'] = self.title
        return context

    def form_valid(self, form):

        snippet_name = self.get_value_from_workflow('snippet_name', '')
        terraform_action = self.request.POST.get('terraform_action', 'validate')

        if snippet_name != '':
            meta = self.load_skillet_by_name(snippet_name)
            # fix for panhandler #170 - self.meta not being set prevents vars from being set in context
            # for terraform destroy
            self.meta = meta
        else:
            raise SnippetRequiredException

        context = super().get_context_data()
        context['header'] = self.get_header()

        if terraform_action == 'override':
            print('Overriding existing terraform state')
            context['title'] = 'Executing Task: Terraform Init with Override'
            new_name = task_utils.override_tfstate(meta)
            messages.add_message(self.request, messages.INFO,
                                 f'Existing Terraform state backed up to {new_name}')

            r = task_utils.perform_init(meta, self.get_snippet_variables_from_workflow())
            self.request.session['task_next'] = 'terraform_validate'

        elif terraform_action == 'validate':
            print('Launching terraform init')
            context['title'] = 'Executing Task: Terraform Init'
            context['auto_continue'] = True
            r = task_utils.perform_init(meta, self.get_snippet_variables_from_workflow())
            self.request.session['task_next'] = 'terraform_validate'
        elif terraform_action == 'refresh':
            print('Launching terraform refresh')
            context['title'] = 'Executing Task: Terraform Refresh'
            r = task_utils.perform_refresh(meta, self.get_snippet_variables_from_workflow())
            self.request.session['task_next'] = 'terraform_output'
        elif terraform_action == 'destroy':
            print('Launching terraform destroy')
            context['title'] = 'Executing Task: Terraform Destroy'
            r = task_utils.perform_destroy(meta, self.get_snippet_variables_from_workflow())
            self.request.session['task_next'] = ''
        else:
            self.request.session['task_next'] = ''
            # should not get here!
            context = super().get_context_data()
            context['title'] = 'Error: Unknown action supplied'
            context['header'] = 'Terraform Template'
            context['results'] = 'Could not launch init task!'
            return render(self.request, 'pan_cnc/results.html', context)

        if r is None:
            context['results'] = 'Could not launch init task!'
            return render(self.request, 'pan_cnc/results.html', context)

        context['results'] = 'task id: %s' % r.id
        # now save needed information to gather the output of the celery tasks
        # and allow us to proceed to the next task
        self.request.session['task_id'] = r.id

        self.request.session['task_app_dir'] = self.app_dir
        self.request.session['task_base_html'] = self.base_html
        return render(self.request, 'pan_cnc/results_async.html', context)


class ErrorView(CNCBaseAuth, RedirectView):
    """
    Cleans up after an error condition
    """

    def get_redirect_url(self, *args, **kwargs):
        self.clean_up_workflow()
        next_url = self.request.session.pop('last_page', '/')
        return next_url


class CancelTaskView(CNCBaseAuth, RedirectView):
    """
    Cancels the currently running Task
    """

    def get_redirect_url(self, *args, **kwargs):

        # clean up the workflow if any is found...
        self.clean_up_workflow()
        if 'task_id' in self.request.session:
            task_id = self.request.session['task_id']
            task = AsyncResult(task_id)

            try:
                if task.state == 'PROGRESS':
                    output = task.info
                    pid_matches = re.match(r'CNC: Spawned Process: (\d+)', output)
                    if pid_matches is not None:
                        pid_str = pid_matches[1]
                        pid = int(pid_str)
                        print(f'Terminating Child process: {pid}')
                        os.kill(pid, 9)

            except TypeError as te:
                print(te)
                pass
            except ValueError as ve:
                print(ve)
                pass
            except ProcessLookupError as pe:
                print(pe)
                pass

            task.revoke(terminate=True)
            task_utils.purge_all_tasks()
            self.request.session.pop('task_id')
            messages.add_message(self.request, messages.INFO, 'Cancelled Task Successfully')
        else:
            messages.add_message(self.request, messages.ERROR, 'No Task found to cancel')

        return '/'


class NextTaskView(CNCView):
    template_name = 'pan_cnc/results_async.html'
    header = 'Task'

    def __init__(self, **kwargs):
        # what's our app_dir, # this is usually dynamically set in urls.py, however, this is not a view that the
        # app builder will over configure in a pan-cnc.yaml file, so we do not have access to the current app name
        # it should be set in the request session though, so grab it there and set it here for all other things to
        # just work
        self._app_dir = ''
        self._base_html = 'pan_cnc/base.html'

        super().__init__(**kwargs)

    @property
    def base_html(self):
        return self._base_html

    @base_html.setter
    def base_html(self, value):
        self._base_html = value

    @property
    def app_dir(self):
        return self._app_dir

    @app_dir.setter
    def app_dir(self, value):
        self._app_dir = value

    def get_app_dir(self):
        if 'current_app_dir' in self.request.session:
            print('Using current_app_dir in NextTaskView')
            self.app_dir = self.request.session['current_app_dir']
            print(f"app_dir is {self.app_dir}")
            return self.app_dir

        if 'task_app_dir' in self.request.session:
            self.app_dir = self.request.session['task_app_dir']
            return self.app_dir
        else:
            return 'pan_cnc'

    def get_base_html(self):
        if 'task_base_html' in self.request.session:
            self.base_html = self.request.session['task_base_html']
            return self.base_html
        else:
            return 'pan_cnc'

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests
            Ensure we have a snippet_name in the workflow somewhere, otherwise, we need to redirect out of here
            Fixes issue where a user goes to the next_task URL directly
        """
        try:
            # attempt to locate the current snippet, if not found then we have a flow error, redirect back to the
            # beginning
            self.get_snippet()
            return self.render_to_response(self.get_context_data())
        except SnippetRequiredException:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

    def get_snippet(self):
        # only get the snippet from the session
        app_dir = self.get_app_dir()
        if app_dir in self.request.session:
            session_cache = self.request.session[app_dir]
            if 'snippet_name' in session_cache:
                print('returning snippet name: %s from session cache' % session_cache['snippet_name'])
                return session_cache['snippet_name']
            else:
                raise SnippetRequiredException
        else:
            print('snippet is not set in NextTaskView:get_snippet')
            raise SnippetRequiredException

    def get_header(self) -> str:

        header = super().get_header()

        task_next = self.request.session['task_next']

        if 'terraform' in task_next:

            if header == 'Task':
                # we are not in a workflow
                header = 'Terraform'

            if 'init' in task_next:
                new_header = f'{header} / Init'
            elif 'validate' in task_next:
                new_header = f'{header} / Validate'
            elif 'plan' in task_next:
                new_header = f'{header} / Plan'
            elif 'apply' in task_next:
                new_header = f'{header} / Apply'
            elif 'output' in task_next:
                new_header = f'{header} / Output'
            else:
                new_header = f'{header} / {task_next}'

        elif 'python' in task_next:
            if header == 'Task':
                # we are not in a workflow
                header = 'Python3'

            new_header = f'{header} / Script execution progress'
        else:
            new_header = f'{header} / Task execution progress'

        return new_header

    def get_context_data(self, **kwargs):
        self.app_dir = self.get_app_dir()
        skillet = self.load_skillet_by_name(self.get_snippet())
        context = dict()
        context['base_html'] = self.base_html

        if 'task_next' not in self.request.session or \
                self.request.session['task_next'] == '':
            context['results'] = 'Could not find next task to execute!'
            context['completed'] = True
            context['error'] = True
            return context

        task_next = self.request.session['task_next']

        context['header'] = self.get_header()

        #
        # terraform tasks
        #
        if task_next == 'terraform_validate':
            r = task_utils.perform_validate(skillet, self.get_snippet_variables_from_workflow(skillet=skillet))
            new_next = 'terraform_plan'
            title = 'Executing Task: Validate'

            # skip right over the results if all is well
            context['auto_continue'] = True
        elif task_next == 'terraform_plan':
            r = task_utils.perform_plan(skillet, self.get_snippet_variables_from_workflow(skillet=skillet))
            new_next = 'terraform_apply'
            title = 'Executing Task: Plan'

        elif task_next == 'terraform_apply':
            r = task_utils.perform_apply(skillet, self.get_snippet_variables_from_workflow(skillet=skillet))
            new_next = 'terraform_output'
            title = 'Executing Task: Apply'
        elif task_next == 'terraform_output':
            r = task_utils.perform_output(skillet, {})
            # output is run sync so we have the results here
            # capture outputs before returning to the results_async page
            result = r.get(timeout=10.0, interval=1.0)
            output = 'Captured output from terraform'
            err = ''
            try:
                json_status = json.loads(result)
                print('---------------------------------')
                print(json_status)
                print('---------------------------------')
                if 'out' in json_status:
                    print('Setting up output')
                    output = json_status['out']
                    try:
                        output_object = json.loads(output)
                        for k in output_object:
                            print(f'Saving key {k} to workflow')
                            self.save_value_to_workflow(k, output_object[k]["value"])

                    except ValueError:
                        print('Could not parse terraform output')

                if 'err' in json_status:
                    err = json_status['err']

            except ValueError as ve:
                print(ve)
                print('Could not get outputs')

            context['title'] = 'Collecting Terraform Outputs'
            if err and not output:
                context['results'] = err
            else:
                context['results'] = output

            context['completed'] = True
            self.request.session['task_id'] = ''
            self.request.session['task_next'] = ''
            return context

        #
        # python3 tasks
        #

        elif task_next == 'python3_execute':
            r = task_utils.python3_execute(skillet, self.get_snippet_variables_from_workflow(skillet=skillet))
            new_next = ''
            title = f"Executing Script: {skillet['label']}"

        #
        # Default catch all
        #

        else:
            self.request.session['task_next'] = ''
            context['results'] = 'Could not launch init task!'
            context['error'] = 1
            return context

        context['title'] = title
        context['results'] = 'task id: %s' % r.id
        self.request.session['task_id'] = r.id
        self.request.session['task_next'] = new_next
        return context


class TaskLogsView(CNCBaseAuth, View):

    def get(self, request, *args, **kwargs) -> Any:
        logs_output = dict()
        if 'task_id' in request.session:
            task_id = request.session['task_id']
            task_next = request.session.get('task_next', '')
            logs_output['task_id'] = task_id
            task_result = AsyncResult(task_id)

            print(task_result.info)

            if task_result.ready():
                try:
                    res = json.loads(task_result.result)
                    out = res.get('out', '')
                    err = res.get('err', '')
                    rc = res.get('returncode', '250')

                    outputs = dict()
                    # fix for panhandler #168 - do not attempt output capture with no returned output
                    if task_next == '' and out != '':
                        print('Last task, checking for output')
                        # The task is complete, now check if we need to do any output capturing from this task
                        # first, load the correct skillet from the session, check for 'snippets' stanza and
                        # and if any of them require output parsing
                        # if outputs remains blank (no output parsing for any snippet, then discard and return the 'out'
                        # directly
                        skillet_name = self.get_value_from_workflow('snippet_name', '')
                        if skillet_name != '':
                            meta = self.load_skillet_by_name(skillet_name)
                            # fix for #101 - panhandler runs python scripts in a virtual env directly and does not
                            # use skilletlib. As such, the output capturing does not happen using newer skilletlib
                            # methods. This code takes the python skillet and treats it as a template skillet. This
                            # works because we have the script output, so assign it to the template snippet 'element'
                            # then 'execute' it, which will grab all the outputs along the way
                            if meta['type'] == 'python3':
                                # create the object
                                python_skillet = Python3Skillet(meta)
                                # this is a temporary fix as skilletlib does not execute python skillets (yet)
                                # execute will simply returrn the python3_output text through capture_outputs etc
                                results = python_skillet.execute({'python3_output': out})
                                captured_outputs = False
                                if 'outputs' in results and type(results['outputs']) is dict:
                                    if len(results['outputs']) > 0:
                                        captured_outputs = True
                                        # outputs.update(results['outputs'])
                                    for k, v in results['outputs'].items():
                                        self.save_value_to_workflow(k, v)

                                logs_output['captured_outputs'] = captured_outputs

                                if 'output_template' in results:
                                    logs_output['output_template'] = results['output_template']

                            # not a python skillet - FIXME - review for other types as well
                            elif 'snippets' in meta:
                                for snippet in meta['snippets']:
                                    if 'output_type' in snippet and 'name' in snippet:
                                        print('getting output from last task')
                                        snippet_output = output_utils.parse_outputs(meta, snippet, out)
                                        outputs.update(snippet_output)

                                if outputs:
                                    self.save_dict_to_workflow(outputs)
                                    # print(self.request.session)
                        else:
                            print('Could not load a valid snippet for output capture!')

                    if out == '' and err == '' and rc == 0:
                        logs_output['output'] = 'Task Completed Successfully'
                    else:
                        if outputs:
                            logs_output['output'] = f'{out}\n{err}'
                            logs_output['captured_output'] = "Successfully captured the following variables:\n\n"
                            logs_output['captured_output'] += json.dumps(outputs, indent=4)
                        else:
                            logs_output['output'] = f'{out}\n{err}'

                    logs_output['returncode'] = rc

                except TypeError as te:
                    print(te)
                    logs_output['output'] = task_result.result
                except ValueError as ve:
                    print(ve)
                    logs_output['output'] = task_result.result

                # remove task_id from session as this one is completed!
                self.request.session.pop('task_id')
                logs_output['status'] = 'exited'
            elif task_result.failed():
                logs_output['status'] = 'exited'
                logs_output['output'] = 'Task Failed, check logs for details'
                self.clean_up_workflow()
            elif task_result.status == 'PROGRESS':
                logs_output['status'] = task_result.state
                task_output = str(task_result.info)
                logs_output['output'] = task_utils.clean_task_output(task_output)

            else:
                logs_output['output'] = 'Task is still Running'
                logs_output['status'] = task_result.state

            if 'task_logs' not in request.session:
                request.session['task_logs'] = dict()

            request.session['task_logs'][task_id] = logs_output
        else:
            logs_output['status'] = 'exited'
            logs_output['output'] = 'No task found'
            logs_output['returncode'] = 255

        try:
            logs_out_str = json.dumps(logs_output)
        except TypeError as te:
            print('Error serializing json output!')
            print(te)
            print(logs_output)
            # smother all issues
            logs_output['output'] = 'Error converting object'
            logs_output['status'] = 'exited'
            logs_output['returncode'] = 255
            self.clean_up_workflow()
            return HttpResponse(json.dumps(logs_output), content_type="application/json")

        return HttpResponse(logs_out_str, content_type="application/json")


#
#
# Workflow Views
#
#

class WorkflowView(CNCBaseAuth, RedirectView):
    """
    Load a workflow and redirect to the next step
    """
    meta = dict()

    def get_redirect_url(self, *args, **kwargs):

        current_step_str = self.kwargs.get('step', 0)
        print(f"Current step is {current_step_str}")
        try:
            current_step = int(current_step_str)
        except ValueError:
            return self.error_out('Could not find current workflow state')

        if current_step == 0:
            self.request.session['workflow_ui_step'] = 1
            # get the actual workflow skillet that was selected
            skillet_name = self.get_value_from_workflow('snippet_name', '')
            # let's save this for later when we are on step #2 or later
            self.request.session['workflow_name'] = skillet_name

        else:
            previous_ui_step = self.request.session.get('workflow_ui_step', 1)
            ui_step = previous_ui_step + 1
            self.request.session['workflow_ui_step'] = ui_step
            # no longer on step 0, so the saved snippet name will not point us back to the origin
            # workflow we need
            print("Getting our original workflow name out of the session")
            skillet_name = self.request.session.get('workflow_name', None)
            if skillet_name is None:
                return self.error_out('Process Error - No Workflow found!')

        print(f"found workflow skillet name {skillet_name}")
        self.meta = self.load_skillet_by_name(skillet_name)

        if self.meta is None:
            return self.error_out('Process Error - No skillet could be loaded')

        if 'snippets' not in self.meta or 'type' not in self.meta:
            return self.error_out('Malformed Skillet!')

        if self.meta['type'] != 'workflow':
            return self.error_out('Process Error - not a Workflow Skillet!')

        if len(self.meta['snippets']) <= current_step:
            print('All done here! Redirect to last captured page')
            self.request.session.pop('next_step', '')
            self.request.session.pop('last_step', '')
            self.request.session.pop('next_url', '')
            self.request.session.pop('workflow_ui_step', '')
            self.request.session.pop('workflow_name', '')
            last_page = self.request.session.pop('last_page', '/')
            return last_page

        if 'name' not in self.meta['snippets'][current_step]:
            return self.error_out('Malformed .meta-cnc workflow step')

        # there is no guarantee this skillet will actually run due to when conditionals, set the value to None
        # and check later
        # current_skillet_name = self.meta['snippets'][current_step]['name']
        current_skillet_name = None
        current_skillet_type = None

        # find which step we should execute
        context = self.get_workflow()
        index = current_step

        sl = SkilletLoader(self.meta['snippet_path'])

        for snippet_def in self.meta['snippets'][index:]:
            # instantiate a snippet class so we can evaluate the context to determine if we should execute this one
            # or another skillet later in the list
            snippet = WorkflowSnippet(self.meta['snippets'][current_step], skillet=None, skillet_loader=None)
            if snippet.should_execute(context):
                current_skillet_name = snippet.name
                # find and load the next skillet here so we can gather it's type
                private_skillet = sl.get_skillet_with_name(current_skillet_name, include_resolved_skillets=True)
                if private_skillet:
                    self.request.session['workflow_skillet'] = private_skillet.skillet_dict
                else:
                    # we we do not have a private / resolved submodule skillet, then the
                    # normal load_skillet_by_name call will find it
                    self.request.session.pop('workflow_skillet', None)

                skillet = self.load_skillet_by_name(snippet.name)

                # ensure we perform the workflow transforms here before we continue
                skillet_context = snippet.transform_context(context)
                self.save_dict_to_workflow(skillet_context)

                if skillet is not None:
                    current_skillet_type = skillet.get('type', None)
                break
            else:
                print('Skipping next step due to when conditional')

            current_step = current_step + 1

        if current_skillet_name is None:
            # there are no more skillets to run
            print('All done here!')
            messages.add_message(self.request, messages.INFO, 'Workflow Completed Successfully')
            self.request.session['next_step'] = None
            self.request.session['last_step'] = None
            self.request.session.pop('next_step', None)
            self.request.session.pop('last_step', None)
            self.request.session.pop('workflow_ui_step', None)
            return self.request.session.get('last_page', '/')

        print(f"Current skillet name is {current_skillet_name}")
        next_step = current_step + 1

        print(f"next step is {next_step}")
        self.save_value_to_workflow('snippet_name', current_skillet_name)
        # we don't have access to the workflow cache from the view, so save our next step directly to the
        # session - We might have to revisit this once we allow multi apps per instance
        if next_step == len(self.meta['snippets']):
            print('SETTING LAST STEP')
            self.request.session['last_step'] = next_step
            self.request.session['next_step'] = next_step
            self.request.session['next_url'] = f'/workflow/{next_step}'
        elif next_step > len(self.meta['snippets']):
            print('All done here!')
            self.request.session['next_step'] = None
            self.request.session['last_step'] = None
            self.request.session.pop('next_step')
            self.request.session.pop('last_step')

        else:
            print('No last step here!')
            self.request.session.pop('last_step', None)
            self.request.session['next_step'] = next_step
            self.request.session['next_url'] = f'/workflow/{next_step}'

        # self.save_workflow_to_session()

        if current_skillet_type is None:
            return '/provision'
        elif current_skillet_type == 'pan_validation':
            # fixme - very ugly mixing of code here, this should be pushed up into panhandler
            # of the validate stuff should be pushed here
            return f'/panhandler/validate/{current_skillet_name}'
        else:
            return '/provision'


#
#
# Environment Management Views
#
#


class EnvironmentBase(CNCBaseAuth, View):
    """
    Base for all environment related views, ensure we always redirect to unlock_envs if no environment is currently
    loaded
    """

    def __init__(self):
        self.e = dict()
        super().__init__()

    def dispatch(self, request, *args, **kwargs):
        self.e = request.session.get('environments', '')
        if self.e == '':
            return HttpResponseRedirect('/unlock_envs')

        return super().dispatch(request, *args, **kwargs)

    def get_header(self):
        if hasattr(self, 'header'):
            return self.header
        else:
            return 'PAN-CNC'


class GetSecretView(EnvironmentBase):

    def post(self, request, *args, **kwargs) -> JsonResponse:
        res = dict()
        res['v'] = ''
        res['status'] = 'error'

        if 'k' not in request.POST:
            print('Could not find required params in POST in GetSecretView')
            return JsonResponse(res)

        secret_name = request.POST['k']
        env_name = request.POST['e']

        if env_name == '' or env_name is None:
            env_name = request.session['current_env']

        if env_name in self.e and secret_name in self.e[env_name]['secrets']:
            secret_value = self.e[env_name]['secrets'][secret_name]
            res['v'] = secret_value
            res['status'] = 'success'
            return JsonResponse(res)
        else:
            res['status'] = 'k not found'
            return JsonResponse(res)


class UnlockEnvironmentsView(CNCBaseAuth, FormView):
    """
    unlock an environment
    """
    success_url = 'list_envs'
    template_name = 'pan_cnc/dynamic_form.html'
    # base form class, you should not need to override this
    form_class = Form
    base_html = 'pan_cnc/base.html'
    header = 'Unlock Environments'
    title = 'Enter master passphrase to unlock the environments configuration'
    help_text = """
                    This form will unlock your Environment. If you have not created an Environment, a new one will be
                    created using the password supplied below.

                    Creating an environment allows you to keep passwords and other data specific to an environment
                    in one place. The environments file is encrypted and placed in your home directory for safe keeping.
                """

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        form = Form()

        unlock_field = fields.CharField(widget=PasswordInput, label='Master Passphrase')
        form.fields['password'] = unlock_field

        user = self.request.user
        if not cnc_utils.check_user_secret(str(user.id)):
            context['header'] = 'Create a new Passphrase protected Environment'
            context['title'] = 'Set new Master Passphrase'
            verify_field = fields.CharField(widget=PasswordInput, label='Verify Master Passphrase')
            form.fields['verify'] = verify_field
        else:
            context['header'] = self.header
            context['title'] = self.title

        context['form'] = form
        context['base_html'] = self.base_html
        return context

    def post(self, request, *args, **kwargs) -> Any:
        form = self.get_form()

        if form.is_valid():
            print('checking passphrase')
            if 'password' in request.POST:
                password = request.POST['password']

                user = request.user
                # check if new environment should be created
                if not cnc_utils.check_user_secret(str(user.id)):
                    if 'verify' not in request.POST or request.POST['verify'] == '':
                        messages.add_message(request, messages.ERROR, 'Passwords Verification failed!')
                        return self.form_invalid(form)

                    verify = request.POST['verify']

                    if password != verify:
                        messages.add_message(request, messages.ERROR, 'Passwords do not match!')
                        return self.form_invalid(form)

                    if cnc_utils.create_new_user_environment_set(str(user.id), password):
                        messages.add_message(request, messages.SUCCESS,
                                             'Created New Env with supplied master passphrase')

                print('Getting environment configs')
                envs = cnc_utils.load_user_secrets(str(user.id), password)
                if envs is None:
                    messages.add_message(request, messages.ERROR, 'Incorrect Password')
                    return self.form_invalid(form)

                session = request.session
                session['environments'] = envs
                session['passphrase'] = password
                env_names = envs.keys()
                if len(env_names) > 0:
                    session['current_env'] = list(env_names)[0]

            return self.form_valid(form)
        else:
            print('nope')
            return self.form_invalid(form)


class ListEnvironmentsView(EnvironmentBase, TemplateView):
    """
    List all Environments
    """
    template_name = 'pan_cnc/list_environments.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        envs = self.request.session.get('environments')
        context['envs'] = envs
        return context


class EditEnvironmentsView(EnvironmentBase, FormView):
    """
    Edit or update an environment
    """
    success_url = '/edit_env'
    template_name = 'pan_cnc/edit_env.html'
    # base form class, you should not need to override this
    form_class = Form
    base_html = 'pan_cnc/base.html'

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')
        form = Form()
        secret_label = fields.CharField(label='Key')
        secret_data = fields.CharField(label='Value')
        env_name_field = fields.CharField(widget=HiddenInput, initial=env_name)
        form.fields['secret_label'] = secret_label
        form.fields['secret_data'] = secret_data
        form.fields['environment'] = env_name_field
        context['form'] = form
        context['base_html'] = self.base_html
        context['env_name'] = env_name
        environments = self.request.session.get('environments', {})
        environment = environments.get(env_name, {})
        context['environment'] = environment
        return context

    def form_valid(self, form):
        current_env = self.request.POST.get('environment', '')
        passphrase = self.request.session.get('passphrase', '')
        if current_env == '':
            messages.add_message(self.request, messages.ERROR, 'No Environment currently loaded!')
            return self.form_invalid(form)

        all_env = self.request.session.get('environments', '')
        if all_env == '':
            messages.add_message(self.request, messages.ERROR, 'Environments are locked or not present')
            return self.form_invalid(form)

        if current_env not in all_env:
            messages.add_message(self.request, messages.ERROR,
                                 'Environments are misconfigured! Reload a new Env to continue')
            return self.form_invalid(form)

        env = all_env[current_env]
        if 'secrets' not in env:
            env['secrets'] = dict()

        if 'secret_label' not in self.request.POST or 'secret_data' not in self.request.POST:
            messages.add_message(self.request, messages.ERROR, 'Incorrect data in POST')
            return self.form_invalid(form)

        secret_label = self.request.POST['secret_label']
        secret_data = self.request.POST['secret_data']
        env['secrets'][secret_label] = secret_data
        all_env[current_env] = env
        if cnc_utils.save_user_secrets(str(self.request.user.id), all_env, passphrase):
            self.request.session['environments'] = all_env
            messages.add_message(self.request, messages.SUCCESS, 'Updated Environment!')
            return HttpResponseRedirect(f'/edit_env/{current_env}')
        else:
            messages.add_message(self.request, messages.ERROR, 'Could not save secrets!')
            return self.form_invalid(form)


class CreateEnvironmentsView(EnvironmentBase, FormView):
    """
    Creates a new Environment
    """
    success_url = '/edit_env'
    template_name = 'pan_cnc/dynamic_form.html'
    # base form class, you should not need to override this
    form_class = Form
    base_html = 'pan_cnc/base.html'
    header = 'New Environment'

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        clone_name = self.kwargs.get('clone', None)
        form = Form()
        environment_name = fields.CharField(label='Name')
        environment_description = fields.CharField(widget=Textarea, label='Description')
        if clone_name:
            clone_name_field = fields.CharField(widget=HiddenInput, initial=clone_name)
            form.fields['clone'] = clone_name_field
            context['title'] = f'Clone Environment from {clone_name}'
        else:
            context['title'] = 'Create New Environment'

        context['header'] = self.header
        form.fields['name'] = environment_name
        form.fields['description'] = environment_description
        context['form'] = form

        context['base_html'] = self.base_html
        return context

    def form_valid(self, form):
        name = self.request.POST.get('name', '')
        description = self.request.POST.get('description', '')
        clone = self.request.POST.get('clone', '')
        passphrase = self.request.session.get('passphrase', '')
        if name == '' or description == '':
            messages.add_message(self.request, messages.ERROR, 'Invalid Form Data')
            return self.form_invalid(form)

        all_env = self.request.session.get('environments', '')
        if all_env == '':
            messages.add_message(self.request, messages.ERROR, 'Environments are locked or not present')
            return self.form_invalid(form)

        if clone != '':
            if clone not in all_env:
                messages.add_message(self.request, messages.ERROR,
                                     'Environments are misconfigured! Reload a new Env to continue')
                return self.form_invalid(form)

            new_secrets = copy.deepcopy(all_env[clone]['secrets'])
            all_env[name] = cnc_utils.create_environment(name, description, new_secrets)
            messages.add_message(self.request, messages.SUCCESS, 'Cloned Environment Successfully from %s' % clone)
        else:
            all_env[name] = cnc_utils.create_environment(name, description, {})
            messages.add_message(self.request, messages.SUCCESS, 'Created Environment Successfully')

        if not cnc_utils.save_user_secrets(str(self.request.user.id), all_env, passphrase):
            messages.add_message(self.request, messages.ERROR, 'Could not save Environment')

        self.request.session['environments'] = all_env
        self.request.session['current_env'] = name
        return HttpResponseRedirect(f'/edit_env/{name}')


class LoadEnvironmentView(EnvironmentBase, RedirectView):
    """
    Load an environment and save it on the session
    """

    def get_redirect_url(self, *args, **kwargs):
        self.clean_up_workflow()
        env_name = self.kwargs.get('env_name')

        if env_name in self.e:
            print(f'Loading Environment {env_name}')
            messages.add_message(self.request, messages.SUCCESS, 'Environment Loaded and ready to rock')
            self.request.session['current_env'] = env_name

            saved_workflow = self.get_workflow()
            if 'secrets' not in self.e[env_name]:
                print('No secrets here to reset')
                return '/list_envs'

            for s in self.e[env_name]['secrets'].keys():
                if s in saved_workflow:
                    print('removing saved value %s' % s)
                    saved_workflow.pop(s)

        else:
            print('Desired env was not found')
            messages.add_message(self.request, messages.ERROR, 'Could not load environment!')

        if 'last_page' in self.request.session:
            return self.request.session['last_page']
        else:
            return '/list_envs'


class DeleteEnvironmentView(EnvironmentBase, RedirectView):
    """
    Delete an environment off disk and ensure it is no longer loaded in the session
    """

    def get_redirect_url(self, *args, **kwargs):

        env_name = self.kwargs.get('env_name')

        if env_name in self.e:
            print(f'Deleting Environment {env_name}')
            messages.add_message(self.request, messages.SUCCESS, 'Environment Deleted')
            self.e.pop(env_name)
            if not cnc_utils.save_user_secrets(str(self.request.user.id), self.e, self.request.session['passphrase']):
                messages.add_message(self.request, messages.ERROR, 'Could not save secrets')

            if self.request.session['current_env'] == env_name:
                self.request.session['current_env'] = ''

            self.request.session['environments'] = self.e
        else:
            print('Desired env was not found')
            messages.add_message(self.request, messages.ERROR, 'Could not find environment!')

        return '/list_envs'


class DeleteEnvironmentKeyView(EnvironmentBase, RedirectView):
    """
    Delete a single Key from the environment
    """

    def get_redirect_url(self, *args, **kwargs):

        env_name = self.kwargs.get('env_name')
        key_name = self.kwargs.get('key_name')

        if env_name in self.e and key_name in self.e[env_name]['secrets']:
            print(f'Deleting Secret {key_name} from {env_name}')
            messages.add_message(self.request, messages.SUCCESS, 'Secret Deleted')
            self.e[env_name]['secrets'].pop(key_name)
            if not cnc_utils.save_user_secrets(str(self.request.user.id), self.e, self.request.session['passphrase']):
                messages.add_message(self.request, messages.ERROR, 'Could not save secrets')

            self.request.session['environments'] = self.e

        else:
            print('Desired secret was not found')
            messages.add_message(self.request, messages.ERROR, 'Could not find secret!')

        return f'/edit_env/{env_name}'


#
#
#
# Debug Classes
#
#


class DebugMetadataView(CNCView):
    """
    Debug class
    """
    template_name = 'pan_cnc/debug_meta_cnc.html'
    header = 'Skillet Detail'

    def __init__(self):
        self.snippet_name = ''
        self.app_dir = ''
        super().__init__()

    def dispatch(self, request, *args, **kwargs):
        self.snippet_name = self.kwargs.get('snippet_name', '')
        self.app_dir = self.kwargs.get('app_dir', '')
        if self.snippet_name == '' or self.app_dir == '':
            messages.add_message(self.request, messages.ERROR, 'Could not find Snippet Name')
            return HttpResponseRedirect('')
        return super().dispatch(request, *args, **kwargs)

    def set_last_page_visit(self) -> None:
        pass

    def get_context_data(self, **kwargs):
        # snippet_data = snippet_utils.get_snippet_metadata(self.snippet_name, self.app_dir)
        snippet = self.load_skillet_by_name(self.snippet_name)
        context = super().get_context_data()
        context['header'] = 'Debug Metadata'
        context['title'] = 'Metadata for %s' % self.snippet_name

        if snippet is None:
            messages.add_message(self.request, messages.ERROR, f'Could not load skillet with name {self.snippet_name}')
            return context

        snippet_data = snippet_utils.read_skillet_metadata(snippet)
        print(f"loaded snippet from {snippet['snippet_path']}")
        context['skillet'] = snippet_data
        context['meta'] = snippet
        return context


class ClearCacheView(CNCBaseAuth, RedirectView):
    """
    Clears the long term cache
    """

    def get_redirect_url(self, *args, **kwargs):
        print('Clearing Cache')
        self.clean_up_workflow()
        # clear everything except our cached imported git repositories
        repos = cnc_utils.get_long_term_cached_value(self.app_dir, 'imported_repositories')
        cnc_utils.clear_long_term_cache(self.app_dir)
        cnc_utils.clear_long_term_cache('cnc')
        cnc_utils.set_long_term_cached_value(self.app_dir, 'imported_repositories', repos, 604800,
                                             'imported_git_repos')

        # fix for panhandler#118
        db_utils.refresh_skillets_from_all_repos()
        messages.add_message(self.request, messages.INFO, 'Long term cache cleared')
        return '/'


class DebugContextView(CNCView):
    """
    Debug Context class, allows user to see all the variables currently set inside the workflow
    """
    template_name = 'pan_cnc/debug_context.html'
    header = 'Panhandler Context'
    help_text = 'This view shows all the values captured into the context. These values will be used to ' \
                'pre-populate fields when rendering Skillet input forms. The output from one skillet can ' \
                'be used as the input to another Skillet allowing more complex workflows.'

    def __init__(self):
        self.snippet_name = ''
        self.app_dir = ''
        super().__init__()

    def set_last_page_visit(self) -> None:
        pass

    def get_context_data(self, **kwargs):
        self.clean_up_workflow()
        workflow = self.get_workflow()
        w = dict(sorted(workflow.items()))
        context = super().get_context_data()
        context['header'] = self.header
        context['title'] = 'Workflow Context'

        try:
            context['workflow'] = json.dumps(w, indent=2)

        except ValueError as ve:
            context['workflow'] = f'Error getting context {ve}'

        return context


class ViewLogsView(CNCView):
    template_name = 'pan_cnc/debug_logs.html'
    help_text = 'This is the raw debug logs from this application. This can be useful to find various errors and ' \
                'trouble shoot issues. Please provide this output when opening an issue or requesting help.'

    def __init__(self):
        self.snippet_name = ''
        self.app_dir = ''
        super().__init__()

    def set_last_page_visit(self) -> None:
        pass

    def get_context_data(self, **kwargs):
        self.clean_up_workflow()
        context = super().get_context_data()
        context['header'] = "Debug Logs"

        dh = docker_utils.DockerHelper()
        context['logs'] = dh.get_container_logs()

        return context


class ClearContextView(CNCBaseAuth, RedirectView):
    """
     Clear Context class, allows user to remove all items in the context
    """

    def get_redirect_url(self, *args, **kwargs):

        self.app_dir = db_utils.get_default_app_name()

        if self.app_dir in self.request.session:
            self.request.session[self.app_dir] = dict()
            messages.add_message(self.request, messages.INFO, 'Context cleared')

        if 'last_page' in self.request.session:
            return self.request.session['last_page']
        else:
            return '/welcome'


class ReinitPythonVenv(CNCView):
    """
    Upgrades the virtualenv associated with a python skillet
    """

    template_name = 'pan_cnc/results_async.html'

    def set_last_page_visit(self) -> None:
        pass

    def get_context_data(self, **kwargs):

        app_dir = self.kwargs.get('app_dir', '')
        if app_dir != '':
            self.app_dir = app_dir

        skillet_name = self.kwargs.get('skillet', '')
        skillet = self.load_skillet_by_name(skillet_name)
        context = super().get_context_data()
        context['base_html'] = self.base_html
        if skillet is not None:
            context['title'] = f"Upgrading Environment for: {skillet['label']}"
            context['auto_continue'] = True
            self.clean_up_workflow()
            r = task_utils.python3_init(skillet)
            self.request.session['task_id'] = r.id
        return context


class DefaultSSHKeyView(CNCView):
    template_name = "pan_cnc/ssh_pub_key.html"

    def set_last_page_visit(self) -> None:
        pass

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)

        pub_key = git_utils.get_default_ssh_pub_key()
        context['public_key'] = pub_key
        return context


class AppWelcomeView(CNCView):
    """
    Simple Welcome View Class to initialize the database for custom CNC Apps.

    This is used by appetizer and should be the default for any CNC Skeleton based apps as well.

    """

    template_name = "pan_cnc/welcome.html"

    def get_context_data(self, **kwargs):

        this_app = os.environ.get('CNC_APP', None)

        context = super().get_context_data(**kwargs)
        if this_app:
            db_utils.initialize_default_repositories(this_app)
            self.request.session['app_dir'] = this_app

        return context
