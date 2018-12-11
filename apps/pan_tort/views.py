import json

import requests
from django.shortcuts import render

from pan_cnc.lib import cnc_utils
from pan_cnc.views import CNCBaseAuth, CNCBaseFormView


class ExecTortView(CNCBaseAuth, CNCBaseFormView):
    snippet = 'tort-request'
    header = 'Analyze Hashes'
    title = 'Enter Hash Data'
    app_dir = 'pan_tort'

    def form_valid(self, form):
        pan_tort_host = cnc_utils.get_config_value('PAN_TORT_HOST', '')
        pan_tort_port = cnc_utils.get_config_value('PAN_TORT_PORT', '')
        pan_tort_url = f'http://{pan_tort_host}:{pan_tort_port}/process_hashes'

        print(f'Using pan-tort url of {pan_tort_url}')

        payload = self.render_snippet_template()

        print(payload)

        payload_json = json.loads(payload)
        res = requests.post(pan_tort_url, json=payload_json)

        context = dict()
        context['results'] = res.text
        return render(self.request, 'pan_cnc/results.html', context=context)
