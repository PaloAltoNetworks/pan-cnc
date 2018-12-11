from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from typing import Any

from pan_cnc.lib import snippet_utils


class CNCBaseAuth(LoginRequiredMixin):
    login_url = '/login'
    form = forms.Form(initial={'username': 'vistoq', 'password': 'Vistoq123'})


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


