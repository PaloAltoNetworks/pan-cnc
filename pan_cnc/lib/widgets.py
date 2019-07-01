from django.forms.widgets import Input


class ListInput(Input):
    input_type = 'list'
    template_name = 'pan_cnc/widgets/list.html'

