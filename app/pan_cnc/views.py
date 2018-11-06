from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.views.generic.edit import FormView

from pan_cnc.lib import snippet_utils


class CNCBaseAuth(LoginRequiredMixin):
    login_url = '/login'


class CNCView(CNCBaseAuth, TemplateView):
    template_name = "base/index.html"


class CNCBaseFormView(FormView):
    form_class = forms.Form
    template_name = 'base/dynamic_form.html'
    success_url = '/'
    snippet = ''
    header = 'Pan-OS Utils'
    title = 'Title'
    action = '/'
    app_dir = 'pan_cnc'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = snippet_utils.load_snippet_with_name(self.snippet, self.app_dir)
        form = self.generate_dynamic_form(service)
        context['form'] = form
        context['header'] = self.header
        return context

    @staticmethod
    def generate_dynamic_form(service):
        dynamic_form = forms.Form()
        # Get all of the variables defined in the service
        for variable in service['variables']:
            field_name = variable['name']
            type_hint = variable['type_hint']
            description = variable['description']
            default = variable['default']
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
            else:
                dynamic_form.fields[field_name] = forms.CharField(label=description, initial=default)

        return dynamic_form


