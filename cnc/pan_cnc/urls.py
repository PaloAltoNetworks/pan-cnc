"""pan_cnc URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.views.generic import TemplateView
from django.urls import path, include

from django.contrib.auth import views as auth_views
from django.conf import settings
import os

urlpatterns = [
    path('', TemplateView.as_view(template_name='base/welcome.html'), name='base'),
    path('login', auth_views.LoginView.as_view(template_name='base/login.html'), name='login'),
    path('logout', auth_views.LogoutView.as_view(next_page='login')),
]

for app in settings.INSTALLED_APPS:
    app_dir = os.path.join(settings.SRC_PATH, app)
    print('Checking app_dir %s' % app_dir)
    if os.path.exists(os.path.join(app_dir, 'urls.py')):
        print('ADDING URL')
        urlpatterns += [path('%s/' % app, include('%s.urls' % app))]

print(urlpatterns)