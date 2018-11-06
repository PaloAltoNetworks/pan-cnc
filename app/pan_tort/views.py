from pan_cnc.views import *

from pan_cnc.views import CNCBaseAuth, CNCBaseFormView


class ExecTortView(CNCBaseAuth, CNCBaseFormView):
    snippet = 'tort-request'
    header = 'Analyze Hashes'
    title = 'Where is this title?'
    action = 'what is this action?'
    app_dir = 'pan_tort'

    def form_valid(self, form):
        print('O Fucking K then')
