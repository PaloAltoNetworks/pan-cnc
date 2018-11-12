from django.urls import path

from pan_tort.views import *

app_name = 'bootstrapper'
urlpatterns = [
    path('', ExecTortView.as_view()),
]