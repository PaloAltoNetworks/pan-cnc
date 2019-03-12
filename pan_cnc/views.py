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
from collections import OrderedDict
from typing import Any

from celery.result import AsyncResult
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render, HttpResponseRedirect, HttpResponse
from django.views.generic import RedirectView
from django.views.generic import TemplateView
from django.views.generic import View
from django.views.generic.edit import FormView

from pan_cnc.lib import cnc_utils
from pan_cnc.lib import output_utils
from pan_cnc.lib import pan_utils
from pan_cnc.lib import rest_utils
from pan_cnc.lib import snippet_utils
from pan_cnc.lib import task_utils
from pan_cnc.lib.exceptions import SnippetRequiredException, CCFParserError


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
                print('Seeding last_page session atrribute')
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

        if hasattr(self, 'service'):
            for variable in self.service['variables']:
                var_name = variable['name']
                if var_name in self.request.POST:
                    print('Adding variable %s to session' % var_name)
                    current_workflow[var_name] = self.request.POST.get(var_name)

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

    def save_dict_to_workflow(self, dict_to_save: dict) -> None:
        """
        Saves all values from a dict into the session_cache / workflow
        :param dict_to_save: a dict of key / value pairs to save
        :return: None
        """

        workflow = self.get_workflow()
        for k in dict_to_save:
            workflow[k] = dict_to_save[k]

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

        workflow = self.get_workflow()
        snippet_vars = dict()
        if skillet is None:
            if hasattr(self, 'service'):
                skillet = self.service
            else:
                return snippet_vars

        for variable in skillet['variables']:
            if 'name' not in variable:
                continue
            var_name = variable['name']
            if var_name in workflow:
                snippet_vars[var_name] = workflow[var_name]

        return snippet_vars

    def get_snippet_context(self) -> dict:
        """
        Convenience method to return the current workflow and env secrets in a single context
        useful for rendering snippets that require values from both
        :return: dict containing env secrets and workflow values
        """
        # context = self.get_workflow()
        # context.update(self.get_environment_secrets())
        context = self.get_environment_secrets()
        context.update(self.get_workflow())
        return context

    def get_value_from_workflow(self, var_name, default='') -> Any:
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
            print('returning variable from environment')
            return secrets[var_name]
        elif var_name in session_cache:
            print('returning var from session')
            return session_cache[var_name]
        else:
            return default

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
        elif self.app_dir != '':
            app_dir = self.app_dir

        if app_dir != '':
            app_config = cnc_utils.get_app_config(self.app_dir)
            if 'label' in app_config:
                return app_config['label']
            elif 'name' in app_config:
                return app_config['name']
            else:
                return default

        return default

    def get_header(self):
        next_step = self.request.session.get('next_step', None)
        if next_step is None:
            return self.header
        else:
            return f"Step {next_step}: {self.header}"


class CNCView(CNCBaseAuth, TemplateView):
    """
    Base View that only renders a template. Use or override this class if you want to include a custom
    HTML page in your app
    """
    template_name = "pan_cnc/index.html"
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    app_dir = 'pan_cnc'
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
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'PAN-OS Utils'
    # title to show on dynamic form
    title = 'Title'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = 'provision'
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
            return self.request.POST['snippet_name']

        elif self.app_dir in self.request.session:
            session_cache = self.request.session[self.app_dir]
            if 'snippet_name' in session_cache:
                print('found snippet defined in the session')
                print('returning snippet name: %s' % session_cache['snippet_name'])
                return session_cache['snippet_name']

        # default case is to use the snippet defined directly on the class
        print(f'Returning snippet: {self.snippet}')
        return self.snippet

    def get_context_data(self, **kwargs) -> dict:
        """
        Loads relevant configuration into the context for the page render
        :param kwargs:
        :return:
        """
        context = super().get_context_data(**kwargs)
        # Generate the dynamic form based on the snippet name found and returned from get_snippet
        form = self.generate_dynamic_form()
        context['form'] = form
        context['header'] = self.header
        context['title'] = self.title
        context['base_html'] = self.base_html
        context['app_dir'] = self.app_dir
        context['snippet_name'] = self.get_snippet()

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
            snippet = self.get_snippet()
            if snippet != '':
                self.service = snippet_utils.load_snippet_with_name(snippet, self.app_dir)
            return self.render_to_response(self.get_context_data())
        except SnippetRequiredException:
            print('Snippet was not defined here!')
            messages.add_message(self.request, messages.ERROR, 'Process Error - Snippet not found')
            return HttpResponseRedirect('/')
        except CCFParserError as cpe:
            print('Could not load CCF Metadata!')
            messages.add_message(self.request, messages.ERROR, 'Process Error - Could not load CCF')
            return HttpResponseRedirect('/')

    def post(self, request, *args, **kwargs) -> Any:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid. If valid, save variables to the session
        and call form_valid
        """
        form = self.get_form()
        if form.is_valid():
            # load the snippet into the class attribute here so it's available to all other methods throughout the
            # call chain in the child classes
            self.service = snippet_utils.load_snippet_with_name(self.get_snippet(), self.app_dir)
            # go ahead and save all our current POSTed variables to the session for use later
            self.save_workflow_to_session()

            return self.form_valid(form)
        else:
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

    def generate_dynamic_form(self) -> forms.Form:
        """
        The heart of this class. This will generate a Form object based on the value of the self.snippet
        All variables defined in a snippet metadata.xml file will be converted into a form field depending on it's
        type_hint. The initial value of the variable will be the value of the 'default' key defined in the metadata file
        or the value of a secret from the currently loaded environment if it contains the same name.

        :return: Form object
        """

        dynamic_form = forms.Form()

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

        if 'type' not in self.service:
            print('No type defined in metadata')
            return dynamic_form

        # Get all of the variables defined in the self.service
        for variable in self.service['variables']:
            if type(variable) is not OrderedDict:
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

            # if the user has entered this before, let's grab it from the session
            default = self.get_value_from_workflow(field_name, variable_default)
            # Figure out which type of widget should be rendered
            # Valid widgets are dropdown, text_area, password and defaults to a char field
            if type_hint == 'dropdown' and 'dd_list' in variable:
                dd_list = variable['dd_list']
                choices_list = list()
                for item in dd_list:
                    if 'key' in item and 'value' in item:
                        print(item)
                        choice = (item['value'], item['key'])
                        choices_list.append(choice)
                dynamic_form.fields[field_name] = forms.ChoiceField(choices=tuple(choices_list), label=description,
                                                                    initial=default)
            elif type_hint == "text_area":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.Textarea, label=description,
                                                                  initial=default)
            elif type_hint == "email":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.EmailInput, label=description,
                                                                  initial=default)
            elif type_hint == "number":
                dynamic_form.fields[field_name] = forms.GenericIPAddressField(label=description,
                                                                              initial=default)
            elif type_hint == "password":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                                                  initial=default)
            elif type_hint == "radio" and "rad_list":
                rad_list = variable['rad_list']
                choices_list = list()
                for item in rad_list:
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)
                dynamic_form.fields[field_name] = forms.ChoiceField(widget=forms.RadioSelect, choices=choices_list,
                                                                    label=description, initial=default)
            elif type_hint == "checkbox" and "cbx_list":
                cbx_list = variable['cbx_list']
                choices_list = list()
                for item in cbx_list:
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)
                dynamic_form.fields[field_name] = forms.ChoiceField(widget=forms.CheckboxSelectMultiple,
                                                                    choices=choices_list,
                                                                    label=description, initial=default)
            else:
                dynamic_form.fields[field_name] = forms.CharField(label=description, initial=default)

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

    def generate_dynamic_form(self):
        """
        Generates a form with only 1 option - snippet_name
        :return: Form Object
        """

        form = forms.Form()
        if self.label_name == '' or self.label_value == '':
            print('No Labels to use to filter!')
            return form

        services = snippet_utils.load_snippets_by_label(self.label_name, self.label_value, self.app_dir)

        # we need to construct a new ChoiceField with the following basic format
        # snippet_name = forms.ChoiceField(choices=(('gold', 'Gold'), ('silver', 'Silver'), ('bronze', 'Bronze')))
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
        new_choices_field = forms.ChoiceField(choices=choices_set, label='Template Name')
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

    def generate_dynamic_form(self):
        form = super().generate_dynamic_form()
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
        # snippet_name = forms.ChoiceField(choices=(('gold', 'Gold'), ('silver', 'Silver'), ('bronze', 'Bronze')))
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
        new_choices_field = forms.ChoiceField(choices=choices_set, label='Template Name')
        # set it on the original form, overwriting the hardcoded GSB version

        form.fields[custom_field] = new_choices_field

        return form


class ProvisionSnippetView(CNCBaseFormView):
    """
    Provision Snippet View - This view uses the Base Auth and Form View
    The posted view is actually a dynamically generated form so the forms.Form will actually be blank
    use form_valid as it will always be true in this case.
    """
    snippet = ''
    header = 'Provision Configuration'
    title = 'Customize Variables'

    def get_context_data(self, **kwargs):
        if self.service is not None:

            if 'type' not in self.service:
                return super().get_context_data()

            if self.service['type'] == 'template':
                self.header = 'Render Template'
                self.title = f"Customize Template: {self.service['label']}"
            elif self.service['type'] == 'panos':
                self.header = 'PAN-OS Configuration'
                self.title = f"Customize PAN-OS Skillet: {self.service['label']}"
            elif self.service['type'] == 'panorama':
                self.header = 'Panorama Configuration'
                self.title = f"Customize Panorama Skillet: {self.service['label']}"
            elif self.service['type'] == 'workflow':
                self.header = 'Workflow'
                self.title = self.service['label']
            else:
                # May need to add additional types here
                t = self.service['type']
                self.header = 'Provision'
                self.title = self.service['label']
                print(f'Found unknown type {t} for form customization in ProvisionSnippetView:get_context_data')

        return super().get_context_data()

    def get_snippet(self):
        print('Checking app_dir')
        print(self.app_dir)

        session_cache = self.request.session.get(self.app_dir, {})

        if 'snippet_name' in self.request.POST:
            print('found snippet in post')
            snippet_name = self.request.POST['snippet_name']
            session_cache['snippet_name'] = snippet_name
            return snippet_name

        elif self.app_dir in self.request.session:
            if 'snippet_name' in session_cache:
                print('returning snippet name: %s from session cache' % session_cache['snippet_name'])
                return session_cache['snippet_name']
        else:
            print('snippet is not set in ProvisionSnippetView:get_snippet')
            raise SnippetRequiredException

    def form_valid(self, form):
        service_name = self.get_value_from_workflow('snippet_name', '')

        if service_name == '':
            # FIXME - add an ERROR page and message here
            print('No Service ID found!')
            return super().form_valid(form)

        if self.service['type'] == 'template':
            template = snippet_utils.render_snippet_template(self.service, self.app_dir, self.get_workflow())
            snippet = self.service['snippets'][0]

            # check for and handle outputs
            if 'outputs' in snippet:
                # template type only has 1 snippet defined, which is the template to render
                outputs = output_utils.parse_outputs(self.service, snippet, template)
                self.save_dict_to_workflow(outputs)

            context = dict()
            context['base_html'] = self.base_html
            # context['header'] = f"Results for {self.service['label']}"
            self.header = f"Results for {self.service['label']}"
            context['title'] = "Rendered Output"
            context['results'] = template
            context['view'] = self
            return render(self.request, 'pan_cnc/results.html', context)
        elif self.service['type'] == 'rest':
            # Found a skillet type of 'rest'
            return HttpResponseRedirect('/editRestTarget')
        elif self.service['type'] == 'python3':
            print('Launching python3 init')
            context = super().get_context_data()
            context['base_html'] = self.base_html
            context['title'] = f"Preparing environment for: {self.service['label']}"
            r = task_utils.python3_init(self.service)
            self.request.session['task_id'] = r.id
            self.request.session['task_next'] = 'python3_execute'
            self.request.session['task_app_dir'] = self.app_dir
            self.request.session['task_base_html'] = self.base_html
            return render(self.request, 'pan_cnc/results_async.html', context)

        elif self.service['type'] == 'workflow':
            # Found a skillet type of 'workflow'
            return HttpResponseRedirect('/workflow/0')
        elif self.service['type'] == 'terraform':
            self.save_value_to_workflow('next_url', self.next_url)
            return HttpResponseRedirect('/terraform')
        else:
            print('This template type requires a target')
            return HttpResponseRedirect('/editTarget')


class EditTargetView(CNCBaseAuth, FormView):
    """
    Edit or update the current target
    """
    # base form class, you should not need to override this
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'PAN-OS Utils'
    # title to show on dynamic form
    title = 'Title'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = '/'
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = 'The Target is the endpoint or device where the configured template will be applied. ' \
                'This us usually a PAN-OS or other network device depending on the type of template to ' \
                'be provisioned'

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests
            Ensure we have a snippet_name in the workflow somewhere, otherwise, we need to redirect out of here
            Fixes issue where a user goes to the editTarget URL directly
        """
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name != '':
            return self.render_to_response(self.get_context_data())
        else:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')
        form = forms.Form()
        snippet_name = self.get_value_from_workflow('snippet_name', '')

        target_ip_label = 'Target IP'
        target_username_label = 'Target Username'
        target_password_label = 'Target Password'

        header = 'Edit Target'
        title = 'Configure Target information'

        if snippet_name != '':
            meta = snippet_utils.load_snippet_with_name(snippet_name, self.app_dir)
            if 'label' in meta:
                header = f"Set Target for {meta['label']}"

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

        workflow = self.get_workflow()
        # print(workflow)

        target_ip = self.get_value_from_workflow('TARGET_IP', '')
        target_username = self.get_value_from_workflow('TARGET_USERNAME', '')
        target_password = self.get_value_from_workflow('TARGET_PASSWORD', '')

        target_ip_field = forms.CharField(label=target_ip_label, initial=target_ip)
        target_username_field = forms.CharField(label=target_username_label, initial=target_username)
        target_password_field = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                                label=target_password_label,
                                                initial=target_password)

        form.fields['TARGET_IP'] = target_ip_field
        form.fields['TARGET_USERNAME'] = target_username_field
        form.fields['TARGET_PASSWORD'] = target_password_field

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
        if snippet_name != '':
            meta = snippet_utils.load_snippet_with_name(snippet_name, self.app_dir)
        else:
            print('Could not find a valid meta-cnc def')
            raise SnippetRequiredException

        workflow = self.get_workflow()
        print(workflow)

        tip = self.get_value_from_workflow('TARGET_IP', None)
        print(f'found current target_ip in workflow of {tip}')
        # Grab the values from the form, this is always hard-coded in this class
        target_ip = self.request.POST.get('TARGET_IP', None)
        target_username = self.request.POST.get('TARGET_USERNAME', None)
        target_password = self.request.POST.get('TARGET_PASSWORD', None)

        print(f'saving target_ip {target_ip} to workflow')

        self.save_value_to_workflow('TARGET_IP', target_ip)
        self.save_value_to_workflow('TARGET_USERNAME', target_username)

        workflow = self.get_workflow()
        print(workflow)

        self.request.session[self.app_dir] = workflow

        # self.save_value_to_workflow('TARGET_PASSWORD', target_password)
        print(f'logging in to pan device with {target_ip}')
        login = pan_utils.panos_login(
            pan_device_ip=target_ip,
            pan_device_username=target_username,
            pan_device_password=target_password
        )

        if login is None:
            context = dict()
            context['base_html'] = self.base_html
            context['results'] = 'Could not login to PAN-OS'
            return render(self.request, 'pan_cnc/results.html', context=context)

        # Always grab all the default values, then update them based on user input in the workflow
        jinja_context = dict()
        if 'variables' in meta and type(meta['variables']) is list:
            for snippet_var in meta['variables']:
                jinja_context[snippet_var['name']] = snippet_var['default']

        # let's grab the current workflow values (values saved from ALL forms in this app
        jinja_context.update(self.get_workflow())
        dependencies = snippet_utils.resolve_dependencies(meta, self.app_dir, [])
        for baseline in dependencies:
            # prego (it's in there)
            baseline_service = snippet_utils.load_snippet_with_name(baseline, self.app_dir)
            # FIX for https://github.com/nembery/vistoq2/issues/5
            if 'variables' in baseline_service and type(baseline_service['variables']) is list:
                for v in baseline_service['variables']:
                    # FIXME - Should include a way show this in UI so we have POSTED values available
                    if 'default' in v:
                        # Do not overwrite values if they've arrived from the user via the Form
                        if v['name'] not in jinja_context:
                            print('Setting default from baseline on context for %s' % v['name'])
                            jinja_context[v['name']] = v['default']

            if baseline_service is not None:
                # check the panorama config to see if it's there or not
                if not pan_utils.validate_snippet_present(baseline_service, jinja_context):
                    # no prego (it's not in there)
                    print('Pushing configuration dependency: %s' % baseline_service['name'])
                    # make it prego
                    if not pan_utils.push_service(baseline_service, jinja_context):
                        messages.add_message(self.request, messages.ERROR, 'Could not push baseline Configuration')
                        return HttpResponseRedirect(f"{self.app_dir}/")

        # BUG-FIX to always just push the toplevel meta
        if not pan_utils.push_service(meta, jinja_context):
            messages.add_message(self.request, messages.ERROR, 'Could not push Configuration')
            return HttpResponseRedirect(f"{self.app_dir}/")

        messages.add_message(self.request, messages.SUCCESS, 'Configuration Push Queued successfully')
        return HttpResponseRedirect(f"{self.app_dir}/")


class EditRestTargetView(CNCBaseAuth, FormView):
    """
    Edit or update the current rest endpoint
    """
    # base form class, you should not need to override this
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'Rest Configuration'
    # title to show on dynamic form
    title = 'Enter Rest Endpoint'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = '/'
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = 'The Target is the endpoint or device where the configured template will be applied. ' \
                'This us usually a PAN-OS or other network device depending on the type of template to ' \
                'be provisioned'

    def get(self, request, *args, **kwargs) -> Any:
        """
            Handle GET requests
            Ensure we have a snippet_name in the workflow somewhere, otherwise, we need to redirect out of here
            Fixes issue where a user goes to the editTarget URL directly
        """
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name != '':
            return self.render_to_response(self.get_context_data())
        else:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)

        snippet_name = self.get_value_from_workflow('snippet_name', '')
        if snippet_name != '':
            meta = snippet_utils.load_snippet_with_name(snippet_name, self.app_dir)
        else:
            print('Could not find a valid meta-cnc def')
            raise SnippetRequiredException

        form = forms.Form()

        target_ip_label = 'Endpoint Host'

        workflow = self.get_workflow()
        print(workflow)

        target_ip = self.get_value_from_workflow('TARGET_IP', '')

        target_ip_field = forms.CharField(label=target_ip_label, initial=target_ip)

        form.fields['TARGET_IP'] = target_ip_field

        context['form'] = form
        context['base_html'] = self.base_html
        context['header'] = meta['label']
        context['title'] = self.title
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
        if snippet_name != '':
            meta = snippet_utils.load_snippet_with_name(snippet_name, self.app_dir)
        else:
            print('Could not find a valid meta-cnc def')
            raise SnippetRequiredException

        target_ip = self.request.POST.get('TARGET_IP', None)
        if target_ip is None:
            messages.add_message(self.request, messages.ERROR, 'Endpoint cannot be blank')
            return self.form_invalid(self.form)

        if not str(target_ip).startswith('http'):
            print('Adding https to endpoint')
            target_ip = f'https://{target_ip}'

        self.save_value_to_workflow('TARGET_IP', target_ip)

        results = rest_utils.execute_all(meta, self.app_dir, self.get_workflow())

        context = dict()
        context['base_html'] = self.base_html
        context['results'] = results
        context['view'] = self

        # results is a dict containing 'snippets' 'status' 'message'
        if 'snippets' not in results or 'status' not in results or 'message' not in results:
            print('Results from rest_utils is malformed')
        else:
            # Save all results into the workflow
            for result in results['snippets']:
                result_snippet = results['snippets'][result]
                if 'outputs' in result_snippet:
                    for output in result_snippet['outputs']:
                        print(f"Saving value for key {output} to session")
                        v = result_snippet['outputs'][output]
                        print(v)
                        self.save_value_to_workflow(output, v)

                    self.save_workflow_to_session()
                else:
                    print('no outputs for this one')

        return render(self.request, 'pan_cnc/results.html', context)


class EditTerraformView(CNCBaseAuth, FormView):
    # base form class, you should not need to override this
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'Terraform Template'
    # title to show on dynamic form
    title = 'Choose the action to perform'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = '/'
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    # link to external documentation
    documentation_link = ''
    # help text - inline documentation text
    help_text = 'Choose which action you would like to perform on the selected Terraform template.'

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
            return self.render_to_response(self.get_context_data())
        else:
            messages.add_message(self.request, messages.ERROR, 'Process Error - Meta not found')
            return HttpResponseRedirect('/')

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')
        form = forms.Form()

        choices_list = list()
        choices_list.append(('validate', 'Validate, Init, and Apply'))
        choices_list.append(('refresh', 'Refresh Current Status'))
        choices_list.append(('destroy', 'Destroy'))

        choices_set = tuple(choices_list)
        terraform_action_list = forms.ChoiceField(choices=choices_set, label='Template Name')
        form.fields['terraform_action'] = terraform_action_list
        context['form'] = form
        context['base_html'] = self.base_html
        context['env_name'] = env_name
        context['header'] = self.header
        context['title'] = self.title
        return context

    def form_valid(self, form):

        snippet_name = self.get_value_from_workflow('snippet_name', '')
        terraform_action = self.request.POST.get('terraform_action', 'validate')

        if snippet_name != '':
            meta = snippet_utils.load_snippet_with_name(snippet_name, self.app_dir)
        else:
            raise SnippetRequiredException

        context = super().get_context_data()
        context['header'] = 'Terraform Template'

        if terraform_action == 'validate':
            print('Launching terraform init')
            context['title'] = 'Executing Task: Terraform Init'
            r = task_utils.perform_init(meta, self.get_snippet_context())
            self.request.session['task_next'] = 'terraform_validate'
        elif terraform_action == 'refresh':
            print('Launching terraform refresh')
            context['title'] = 'Executing Task: Terraform Refresh'
            r = task_utils.perform_refresh(meta, self.get_snippet_context())
            self.request.session['task_next'] = 'terraform_output'
        elif terraform_action == 'destroy':
            print('Launching terraform destroy')
            context['title'] = 'Executing Task: Terraform Destroy'
            r = task_utils.perform_destroy(meta, self.get_snippet_context())
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


class NextTaskView(CNCView):
    template_name = 'pan_cnc/results_async.html'

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

    def get_context_data(self, **kwargs):
        app_dir = self.get_app_dir()
        skillet = snippet_utils.load_snippet_with_name(self.get_snippet(), app_dir)
        context = dict()
        context['base_html'] = self.base_html

        if 'task_next' not in self.request.session or \
                self.request.session['task_next'] == '':
            context['results'] = 'Could not find next task to execute!'
            context['completed'] = True
            context['error'] = True
            return context

        task_next = self.request.session['task_next']

        if 'terraform' in task_next:
            context['header'] = 'Terraform execution progress'
        elif 'python' in task_next:
            context['header'] = 'Script execution progress'
        else:
            context['header'] = 'Task execution progress'

        #
        # terraform tasks
        #
        if task_next == 'terraform_validate':
            r = task_utils.perform_validate(skillet, self.get_snippet_context())
            new_next = 'terraform_plan'
            title = 'Executing Task: Validate'
        elif task_next == 'terraform_plan':
            r = task_utils.perform_plan(skillet, self.get_snippet_context())
            new_next = 'terraform_apply'
            title = 'Executing Task: Plan'

        elif task_next == 'terraform_apply':
            r = task_utils.perform_apply(skillet, self.get_snippet_context())
            new_next = 'terraform_output'
            title = 'Executing Task: Apply'
        elif task_next == 'terraform_output':
            r = task_utils.perform_output(skillet, {})
            # output is run synch so we have the results here
            # capture outputs before returning to the results_async page

            print(type(r))

            result = r.result
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
            r = task_utils.python3_execute(skillet, self.get_snippet_variables_from_workflow(skillet))
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
                    if task_next == '':
                        print('Last task, checking for output')
                        # The task is complete, now check if we need to do any output capturing from this task
                        # first, load the correct skillet from the session, check for 'snippets' stanza and
                        # and if any of them require output parsing
                        # if outputs remains blank (no output parsing for any snippet, then discard and return the 'out'
                        # directly
                        skillet_name = self.get_value_from_workflow('snippet_name', '')
                        if skillet_name != '':
                            print('loaded skillet from session')
                            meta = snippet_utils.load_snippet_with_name(skillet_name, self.app_dir)
                            if 'snippets' in meta:
                                for snippet in meta['snippets']:
                                    if 'output_type' in snippet and 'name' in snippet:
                                        print('getting output from last task')
                                        snippet_output = output_utils.parse_outputs(meta, snippet, out)
                                        outputs[snippet['name']] = snippet_output

                                        # save all captured output to the workflow / session
                                        for o in outputs:
                                            d = outputs[o]
                                            self.save_dict_to_workflow(d)

                        else:
                            print('Could not load a valid snippet for output capture!')

                    if out == '' and err == '' and rc == 0:
                        logs_output['output'] = 'Task Completed Successfully'
                    else:
                        if outputs:
                            logs_output['output'] = f'{out}\n{err}'
                            logs_output['captured_output'] = json.dumps(outputs)
                        else:
                            logs_output['output'] = f'{out}\n{err}'

                    logs_output['returncode'] = rc

                except TypeError as te:
                    print(te)
                    logs_output['output'] = task_result.result
                except ValueError as ve:
                    print(ve)
                    logs_output['output'] = task_result.result

                logs_output['status'] = 'exited'
            elif task_result.failed():
                logs_output['status'] = 'exited'
                logs_output['output'] = 'Task Failed, check logs for details'
            elif task_result.status == 'PROGRESS':
                logs_output['status'] = task_result.state
                logs_output['output'] = task_result.info

            else:
                logs_output['output'] = 'Task is still Running'
                logs_output['status'] = task_result.state

            if 'task_logs' not in request.session:
                request.session['task_logs'] = dict()

            request.session['task_logs'][task_id] = logs_output
        else:
            logs_output['status'] = 'no task found'

        try:
            logs_out_str = json.dumps(logs_output)
        except TypeError:
            print('Error serializing json output!')
            # smother all issues
            logs_output['output'] = 'Error converting object'
            logs_output['status'] = 'exited'
            logs_output['returncode'] = 255

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

        current_step_str = self.kwargs.get('step')
        current_step = 0
        print(f"Current step is {current_step_str}")
        try:
            current_step = int(current_step_str)
        except ValueError as ve:
            print('Could not parse current step index!')
            print(ve)

        next_step = current_step + 1

        print(f"next step is {next_step}")
        if current_step == 0:
            # get the actual workflow skillet what was selected
            skillet_name = self.get_value_from_workflow('snippet_name', '')
            # let's save this for later when we are on step #2 or later
            self.save_value_to_workflow('workflow_name', skillet_name)
        else:
            # no longer on step 0, so the saved snippet name will not point us back to the origin
            # workflow we need
            print(f"Getting our original workflow name out of the session")
            skillet_name = self.get_value_from_workflow('workflow_name', '')

        print(f"found skillet name {skillet_name}")
        self.meta = snippet_utils.load_snippet_with_name(skillet_name, self.app_dir)

        if 'snippets' not in self.meta or 'type' not in self.meta:
            messages.add_message(self.request, messages.ERROR, 'Malformed .meta-cnc')
            return '/'

        if self.meta['type'] != 'workflow':
            messages.add_message(self.request, messages.ERROR, 'Process Error - not a workflow skillet!')
            return '/'

        if len(self.meta['snippets']) <= current_step:
            print('All done here! Redirect Home')
            self.request.session['next_step'] = None
            self.request.session['last_step'] = None
            self.request.session.pop('next_step')
            self.request.session.pop('last_step')
            return '/'

        if 'name' not in self.meta['snippets'][current_step]:
            messages.add_message(self.request, messages.ERROR, 'Malformed .meta-cnc workflow step')
            return '/'

        current_skillet_name = self.meta['snippets'][current_step]['name']
        print(f"Current skillet name is {current_skillet_name}")

        self.save_value_to_workflow('snippet_name', current_skillet_name)
        # we don't have access to the workflow cache from the view, so save our next step directly to the
        # session - We might have to revisit this once we allow multi apps per instance
        if next_step == len(self.meta['snippets']):
            print('SETTING LAST STEP')
            self.request.session['last_step'] = next_step
            self.request.session['next_step'] = next_step
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

        self.save_workflow_to_session()

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
    form_class = forms.Form
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
        form = forms.Form()

        unlock_field = forms.CharField(widget=forms.PasswordInput, label='Master Passphrase')
        form.fields['password'] = unlock_field

        user = self.request.user
        if not cnc_utils.check_user_secret(str(user.id)):
            context['header'] = 'Create a new Passphrase protected Environment'
            context['title'] = 'Set new Master Passphrase'
            verify_field = forms.CharField(widget=forms.PasswordInput, label='Verify Master Passphrase')
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
    form_class = forms.Form
    base_html = 'pan_cnc/base.html'

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        env_name = self.kwargs.get('env_name')
        form = forms.Form()
        secret_label = forms.CharField(label='Key')
        secret_data = forms.CharField(label='Value')
        env_name_field = forms.CharField(widget=forms.HiddenInput, initial=env_name)
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
    form_class = forms.Form
    base_html = 'pan_cnc/base.html'

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        clone_name = self.kwargs.get('clone', None)
        form = forms.Form()
        environment_name = forms.CharField(label='Name')
        environment_description = forms.CharField(widget=forms.Textarea, label='Description')
        if clone_name:
            clone_name_field = forms.CharField(widget=forms.HiddenInput, initial=clone_name)
            form.fields['clone'] = clone_name_field
            context['title'] = f'Clone Environment from {clone_name}'
        else:
            context['title'] = f'Create New Environment'

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

        env_name = self.kwargs.get('env_name')

        if env_name in self.e:
            print(f'Loading Environment {env_name}')
            messages.add_message(self.request, messages.SUCCESS, 'Environment Loaded and ready to rock')
            self.request.session['current_env'] = env_name
        else:
            print('Desired env was not found')
            messages.add_message(self.request, messages.ERROR, 'Could not load environment!')

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

        # print(f'{env_name} {key_name}')
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
    template_name = 'pan_cnc/results.html'

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

    def get_context_data(self, **kwargs):
        snippet_data = snippet_utils.get_snippet_metadata(self.snippet_name, self.app_dir)
        context = super().get_context_data()
        context['results'] = snippet_data
        context['header'] = 'Debug Metadata'
        context['title'] = 'Metadata for %s' % self.snippet_name
        return context
