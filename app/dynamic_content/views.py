from pan_cnc.views import CNCBaseAuth, CNCBaseFormView


class DownloadDynamicContentView(CNCBaseAuth, CNCBaseFormView):
    snippet = 'download_dynamic_content'
    header = 'Download Dynamic Content'
    title = 'Where is this title?'
    action = 'what is this action?'
    app_dir = 'dynamic_content'

    def form_valid(self, form):
        print('O Fucking K then')
