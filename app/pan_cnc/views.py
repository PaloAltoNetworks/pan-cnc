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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = snippet_utils.load_snippet_with_name(self.snippet)
        form = self.generate_dynamic_form(service)
        context['form'] = form
        context['header'] = self.header
        return context

    @staticmethod
    def generate_dynamic_form(service):
        dynamic_form = forms.Form()
        for variable in service['variables']:
            field_name = variable['name']
            type_hint = variable['type_hint']
            description = variable['description']
            default = variable['default']
            # FIXME - set form field type based on type_hint
            dynamic_form.fields[field_name] = forms.CharField(label=description, initial=default)

        return dynamic_form


