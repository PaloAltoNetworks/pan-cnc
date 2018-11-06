from django.conf import settings
from django.shortcuts import render
from django.core.cache import cache
from pan_cnc.views import CNCBaseAuth, CNCBaseFormView


class DownloadDynamicContentView(CNCBaseAuth, CNCBaseFormView):
    snippet = 'download_dynamic_content'
    header = 'Download Dynamic Content'
    title = 'Where is this title?'
    action = 'what is this action?'
    app_dir = 'dynamic_content'

    def form_valid(self, form):
        panrc = cache.get('panrc')
        print(panrc)
        context = dict()
        return render(self.request, 'base/welcome.html', context=context)
