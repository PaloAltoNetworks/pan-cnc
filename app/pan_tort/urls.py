from django.urls import path

from pan_tort.views import *

app_name = 'tort'
urlpatterns = [
    path('', ExecTortView.as_view()),
]