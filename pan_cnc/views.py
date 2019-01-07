from typing import Any
import copy

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, HttpResponseRedirect
from django.views.generic import RedirectView
from django.views.generic import TemplateView
from django.views.generic import View
from django.views.generic.edit import FormView

from pan_cnc.lib import cnc_utils
from pan_cnc.lib import pan_utils
from pan_cnc.lib import snippet_utils
from pan_cnc.lib.exceptions import SnippetRequiredException


class CNCBaseAuth(LoginRequiredMixin):
    login_url = '/login'


class CNCView(CNCBaseAuth, TemplateView):
    template_name = "pan_cnc/index.html"
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'
    app_dir = 'pan_cnc'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['base_html'] = self.base_html
        context['app_dir'] = self.app_dir
        return context


class CNCBaseFormView(FormView):
    """
    Base class for most CNC view functions. Will find a 'snippet' from either the POST or the session cache
    and load it into a 'service' attribute.
    GET will create a dynamic form based on the loaded snippet
    POST will save all user input into the session and redirect to next_url

    Variables defined in __init__ are instance specific variables while variables defined immedately preceeding
    this docstring are class specific variables and will be shared with child classes

    """
    # base form class, you should not need to override this
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # Head to show on the rendered dynamic form - Main header
    header = 'Pan-OS Utils'
    # title to show on dynamic form
    title = 'Title'
    # where to go after this? once the form has been submitted, redirect to where?
    # this should match a 'view name' from the pan_cnc.yaml file
    next_url = 'provision'
    # the action of the form if it needs to differ (it shouldn't)
    action = '/'
    # the app dir should match the app name and is used to load app specific snippets
    app_dir = 'pan_cnc'
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'

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
        print('Getting snippet here in CNCBaseFormView:get_snippet')
        if 'snippet_name' in self.request.POST:
            print('found it in the POST')
            return self.request.POST['snippet_name']

        elif self.app_dir in self.request.session:
            print('Checking session for snippet')
            session_cache = self.request.session[self.app_dir]
            if 'snippet_name' in session_cache:
                print('returning snippet name: %s' % session_cache['snippet_name'])
                return session_cache['snippet_name']

        print(f'Returning snippet: {self.snippet}')
        return self.snippet

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        form = self.generate_dynamic_form()
        context['form'] = form
        context['header'] = self.header
        context['title'] = self.title
        context['base_html'] = self.base_html
        context['app_dir'] = self.app_dir
        context['snippet_name'] = self.get_snippet()

        return context

    def get(self, request, *args, **kwargs) -> Any:
        """Handle GET requests: instantiate a blank version of the form."""
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

    def post(self, request, *args, **kwargs) -> Any:
        """
        Handle POST requests: instantiate a form instance with the passed
        POST variables and then check if it's valid. If valid, save variables to the session
        and load the desired snippet
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

        if 'variables' not in self.service:
            print('Service not loaded on this class!')
            return ''
        template = snippet_utils.render_snippet_template(self.service, self.app_dir, self.get_workflow())
        return template

    def save_workflow_to_session(self) -> None:
        """
        Save the current user input to the session
        :return: None
        """

        if self.app_dir in self.request.session:
            current_workflow = self.request.session[self.app_dir]
        else:
            current_workflow = dict()

        for variable in self.service['variables']:
            var_name = variable['name']
            if var_name in self.request.POST:
                print('Adding variable %s to session' % var_name)
                current_workflow[var_name] = self.request.POST.get(var_name)

        self.request.session[self.app_dir] = current_workflow

    def save_value_to_workflow(self, var_name, var_value) -> None:

        workflow = self.get_workflow()
        workflow[var_name] = var_value

    def get_workflow(self) -> dict:
        if self.app_dir in self.request.session:
            return self.request.session[self.app_dir]
        else:
            return dict()

    def get_snippet_context(self) -> dict:
        """
        Convienence function to return the current workflow and env secrets in a single context
        useful for rendering snippets that require values from both
        :return: dict containing env secrets and workflow values
        """
        context = self.get_workflow()
        context.update(self.get_environment_secrets())
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

    def get_environment_secrets(self):
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

    def generate_dynamic_form(self) -> forms.Form:

        dynamic_form = forms.Form()

        if self.service is None:
            print('There is not service here :-/')
            return dynamic_form

        if 'variables' not in self.service:
            print('No self.service found on this class')
            return dynamic_form

        # Get all of the variables defined in the self.service
        for variable in self.service['variables']:
            if len(self.fields_to_filter) != 0:
                if variable['name'] in self.fields_to_filter:
                    print('Skipping render of variable %s' % variable['name'])
                    continue

            elif len(self.fields_to_render) != 0:
                if variable['name'] not in self.fields_to_render:
                    print('Skipping render of variable %s' % variable['name'])
                    continue

            field_name = variable['name']
            type_hint = variable['type_hint']
            description = variable['description']
            # if the user has entered this before, let's grab it from the session
            default = self.get_value_from_workflow(variable['name'], variable['default'])
            # Figure out which type of widget should be rendered
            # Valid widgets are dropdown, text_area, password and defaults to a char field
            if type_hint == 'dropdown' and 'dd_list' in variable:
                dd_list = variable['dd_list']
                choices_list = list()
                for item in dd_list:
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
                dynamic_form.fields[field_name] = forms.ChoiceField(widget=forms.CheckboxSelectMultiple, choices=choices_list,
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


class ChooseSnippetByLabelView(CNCBaseAuth, CNCBaseFormView):
    label_name = ''
    label_value = ''

    def get_snippet(self) -> str:
        return ''

    def generate_dynamic_form(self):

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
        new_choices_field = forms.ChoiceField(choices=choices_set)
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


class ChooseSnippetView(CNCBaseAuth, CNCBaseFormView):
    snippet = ''

    def get_snippet(self):
        return self.snippet

    def generate_dynamic_form(self):
        form = super().generate_dynamic_form()
        if self.service is None:
            return form

        if 'labels' in self.service and 'customize_field' in self.service['labels']:
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
        new_choices_field = forms.ChoiceField(choices=choices_set)
        # set it on the original form, overwriting the hardcoded GSB version

        form.fields[custom_field] = new_choices_field

        return form


class ProvisionSnippetView(CNCBaseAuth, CNCBaseFormView):
    """
    Provision Service View - This view uses the Base Auth and Form View
    The posted view is actually a dynamically generated form so the forms.Form will actually be blank
    use form_valid as it will always be true in this case.
    """
    snippet = ''
    header = 'Provision Service'
    title = 'Configure Service Sales information'

    def get_snippet(self):
        print('Getting snippet here in ProvisionSnippetView:get_snippet')
        if 'snippet_name' in self.request.POST:
            print('found snippet in post')
            return self.request.POST['snippet_name']

        elif self.app_dir in self.request.session:
            session_cache = self.request.session[self.app_dir]
            if 'snippet_name' in session_cache:
                print('returning snippet name: %s from session cache' % session_cache['snippet_name'])
                return session_cache['snippet_name']
        else:
            print('snippet is not set in ProvisionSnippetView:get_snippet')
            raise SnippetRequiredException

    def form_valid(self, form):
        """
        form_valid is always called on a blank / new form, so this is essentially going to get called on every POST
        self.request.POST should contain all the variables defined in the service identified by the hidden field
        'service_id'
        :param form: blank form data from request
        :return: render of a success template after service is provisioned
        """
        service_name = self.get_value_from_workflow('snippet_name', '')

        if service_name == '':
            # FIXME - add an ERROR page and message here
            print('No Service ID found!')
            return super().form_valid(form)

        if self.service['type'] == 'template':
            template = snippet_utils.render_snippet_template(self.service, self.app_dir, self.get_workflow())
            context = dict()
            context['results'] = template
            return render(self.request, 'pan_cnc/results.html', context)

        login = pan_utils.panorama_login()
        if login is None:
            context = dict()
            context['results'] = 'Could not login to Panorama'
            return render(self.request, 'pan_cnc/results.html', context=context)

        # Always grab all the default values, then update them based on user input in the workflow
        jinja_context = dict()
        if 'variables' in self.service and type(self.service['variables']) is list:
            for snippet_var in self.service['variables']:
                jinja_context[snippet_var['name']] = snippet_var['default']

        # let's grab the current workflow values (values saved from ALL forms in this app
        jinja_context.update(self.get_workflow())
        dependencies = snippet_utils.resolve_dependencies(self.service, self.app_dir, [])
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
                    pan_utils.push_service(baseline_service, jinja_context)

        # BUG-FIX to always just push the toplevel self.service
        pan_utils.push_service(self.service, jinja_context)
        # if not pan_utils.validate_snippet_present(service, jinja_context):
        #     print('Pushing new service: %s' % service['name'])
        #     pan_utils.push_service(service, jinja_context)
        # else:
        #     print('This service was already configured on the server')

        return super().form_valid(form)


class EnvironmentBase(CNCBaseAuth, View):
    def __init__(self):
        self.e = dict()
        super().__init__()

    def dispatch(self, request, *args, **kwargs):
        self.e = request.session.get('environments', '')
        if self.e == '':
            return HttpResponseRedirect('/unlock_envs')

        return super().dispatch(request, *args, **kwargs)


class UnlockEnvironmentsView(CNCBaseAuth, FormView):
    success_url = 'list_envs'
    template_name = 'pan_cnc/dynamic_form.html'
    # base form class, you should not need to override this
    form_class = forms.Form
    base_html = 'pan_cnc/base.html'
    header = 'Unlock Environments'
    title = 'Enter master passphrase to unlock the environments configuration'

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        form = forms.Form()
        unlock_field = forms.CharField(widget=forms.PasswordInput, label='Master PassPhrase')
        form.fields['password'] = unlock_field
        context['form'] = form
        context['base_html'] = self.base_html
        context['header'] = self.header
        context['title'] = self.title
        return context

    def post(self, request, *args, **kwargs) -> Any:
        form = self.get_form()

        if form.is_valid():
            print('checking passphrase')
            if 'password' in request.POST:
                print('Getting environment configs')
                user = request.user
                if not cnc_utils.check_user_secret(str(user.id)):
                    if cnc_utils.create_new_user_environment_set(str(user.id), request.POST['password']):
                        messages.add_message(request, messages.SUCCESS,
                                             'Created New Env with supplied master passphrase')
                envs = cnc_utils.load_user_secrets(str(user.id), request.POST['password'])
                if envs is None:
                    messages.add_message(request, messages.ERROR, 'Incorrect Password')
                    return self.form_invalid(form)

                session = request.session
                session['environments'] = envs
                session['passphrase'] = request.POST['password']
                env_names = envs.keys()
                if len(env_names) > 0:
                    session['current_env'] = list(env_names)[0]

            return self.form_valid(form)
        else:
            print('nope')
            return self.form_invalid(form)


class ListEnvironmentsView(EnvironmentBase, CNCView):
    template_name = 'pan_cnc/list_environments.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        envs = self.request.session.get('environments')
        context['envs'] = envs
        return context


class EditEnvironmentsView(EnvironmentBase, FormView):
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
        secret_data = forms.CharField(widget=forms.PasswordInput, label='Value')
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

    def get_redirect_url(self, *args, **kwargs):

        env_name = self.kwargs.get('env_name')
        key_name = self.kwargs.get('key_name')

        print(f'{env_name} {key_name}')
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


class DebugMetadataView(CNCView):
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
