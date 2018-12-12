from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from django.shortcuts import render, HttpResponseRedirect
from typing import Any

from pan_cnc.lib import snippet_utils
from pan_cnc.lib import pan_utils


class CNCBaseAuth(LoginRequiredMixin):
    login_url = '/login'


class CNCView(CNCBaseAuth, TemplateView):
    template_name = "pan_cnc/index.html"


class CNCBaseFormView(FormView):
    # base form class, you should not need to override this
    form_class = forms.Form
    # form to render, override if you need a specific html fragment to render the form
    template_name = 'pan_cnc/dynamic_form.html'
    # where to forward after we've successfully acted on the submitted form data
    success_url = '/'
    # name of the snippet to load and use as the basis for the dynamic form
    snippet = ''
    # Head to show on the rendered dynamic form
    header = 'Pan-OS Utils'
    # FIXME - where does this go again?
    title = 'Title'
    # the action of the form if it needs to differ
    action = '/'
    # the app dir should match the app name and is used to load app specific snippets
    app_dir = 'pan_cnc'
    # after the jinja context is fully populated, save it here for future use in the view
    parsed_context = dict()
    # form_fields to render, you may not want to render all the variables given in the service variables list
    # only fields that appear in the list (or all fields if list is empty) will be rendered in the dynamic form
    fields_to_render = list()
    # form fields to NOT render
    fields_to_filter = list()
    # loaded snippet
    service = dict()
    # base html - allow sub apps to override this with special html base if desired
    base_html = 'pan_cnc/base.html'

    def get_snippet(self) -> str:
        print('returning snippet name: %s' % self.snippet)
        return self.snippet

    def get_context_data(self, **kwargs) -> dict:
        print('GETTING CONTEXT DATA')
        print(kwargs)
        context = super().get_context_data(**kwargs)
        form = self.generate_dynamic_form()
        context['form'] = form
        context['header'] = self.header
        context['title'] = self.title

        context['base_html'] = self.base_html

        return context

    def get(self, request, *args, **kwargs) -> Any:
        """Handle GET requests: instantiate a blank version of the form."""
        # load the snippet into the class attribute here so it's available to all other methods throughout the
        # call chain in the child classes
        self.service = snippet_utils.load_snippet_with_name(self.get_snippet(), self.app_dir)
        return self.render_to_response(self.get_context_data())

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

    def get_workflow(self) -> dict:
        if self.app_dir in self.request.session:
            return self.request.session[self.app_dir]
        else:
            return dict()

    def get_value_from_workflow(self, var_name, default) -> Any:
        session_cache = self.get_workflow()
        return session_cache.get(var_name, default)

    def generate_dynamic_form(self) -> forms.Form:

        dynamic_form = forms.Form()
        if 'variables' not in self.service:
            print('No self.service found on this class')
            return dynamic_form

        # Get all of the variables defined in the self.service
        for variable in self.service['variables']:
            if len(self.fields_to_render) != 0:
                print(self.fields_to_render)
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
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)
                dynamic_form.fields[field_name] = forms.ChoiceField(choices=tuple(choices_list))
            elif type_hint == "text_area":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.Textarea)
            elif type_hint == "email":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.EmailInput)
            elif type_hint == "number":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.NumberInput)
            elif type_hint == "ip":
                dynamic_form.fields[field_name] = forms.GenericIPAddressField()
            elif type_hint == "password":
                dynamic_form.fields[field_name] = forms.CharField(widget=forms.PasswordInput)
            elif type_hint == "radio" and "rad_list":
                rad_list = variable['rad_list']
                choices_list = list()
                for item in rad_list:
                    choice = (item['value'], item['key'])
                    choices_list.append(choice)
                dynamic_form.fields[field_name] = forms.ChoiceField(widget=forms.RadioSelect, choices=choices_list)
            else:
                dynamic_form.fields[field_name] = forms.CharField(label=description, initial=default)

        return dynamic_form


class ChooseSnippetView(CNCBaseAuth, CNCBaseFormView):
    """
    /mssp/configure

    Allows the user to choose which snippet to load, configure, and provision based on a dropdown list of snippets
    with a certain label

    The fields to configure are defined in the snippet given in the 'snippet' attribute

    The list of snippets to choose from are defined by the 'customize_field', 'customize_label_name' and
    'customize_label_value' labels on the snippet YAML.

    For example: To present a list of snippets to configure user-id on panorama
            1. create the initial configuration snippet with whatever values we need there
            2. add the required labels: customize_field, customize_label_name, customize_label_value
            3. Add at least one configuration snippet with the appropriate label
            4. Create a URL entry in urls.py
                        path('configure', ChooseSnippetView.as_view(snippet='user_id_config)),
            5. Optional - add a menu entry in the templates/mssp/base.html file

    """
    snippet = 'cnc-conf'
    header = 'Provision Service'
    title = 'Configure Service Sales information'
    app_dir = 'pan_cnc'

    def get_context_data(self, **kwargs):
        """
        Override get_context_data so we can modify the SimpleDemoForm as necessary.
        We want to dynamically add all the snippets in the snippets dir as choice fields on the form
        :param kwargs:
        :return:
        """

        context = super().get_context_data(**kwargs)

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

        form = context['form']

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

        context['form'] = form
        return context

    def form_valid(self, form):
        """
        Called when the simple demo form is submitted
        :param form: SimpleDemoForm
        :return: rendered html response
        """
        return HttpResponseRedirect('provision')


class ProvisionSnippetView(CNCBaseAuth, CNCBaseFormView):
    """
    Provision Service View - This view uses the Base Auth and Form View
    The posted view is actually a dynamically generated form so the forms.Form will actually be blank
    use form_valid as it will always be true in this case.
    """
    snippet = ''
    header = 'Provision Service'
    title = 'Configure Service Sales information'
    app_dir = 'pan_cnc'

    def get_snippet(self):
        print('Getting snippet here in get_snippet')
        if 'snippet_name' in self.request.POST:
            return self.request.POST['snippet_name']

        elif self.app_dir in self.request.session:
            session_cache = self.request.session[self.app_dir]
            if 'snippet_name' in session_cache:
                print('returning snippet name: %s' % session_cache['snippet_name'])
                return session_cache['snippet_name']
        else:
            print('what happened here?')
            return self.snippet

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
            return render(self.request, 'mssp/results.html', context)

        login = pan_utils.panorama_login()
        if login is None:
            context = dict()
            context['error'] = 'Could not login to Panorama'
            return render(self.request, 'mssp/error.html', context=context)

        # let's grab the current workflow values (values saved from ALL forms in this app
        jinja_context = self.get_workflow()
        # check if we need to ensure a baseline exists before hand
        if 'extends' in self.service and self.service['extends'] is not None:
            # prego (it's in there)
            baseline = self.service['extends']
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
