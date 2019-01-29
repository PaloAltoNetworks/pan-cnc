# Copyright (c) 2018, Palo Alto Networks
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Author: Nathan Embery nembery@paloaltonetworks.com

"""
Palo Alto Networks pan-cnc

pan-cnc is a library to build simple GUIs and workflows primarily to interact with various APIs

Please see http://github.com/PaloAltoNetworks/pan-cnc for more information

This software is provided without support, warranty, or guarantee.
Use at your own risk.
"""

import importlib

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path
from pan_cnc import views as pan_cnc_views
from pan_cnc.lib import cnc_utils

# ensure every view gets this in the context, even django default views
app_settings = settings.INSTALLED_APPS_CONFIG

urlpatterns = [
    path('login', auth_views.LoginView.as_view(template_name='pan_cnc/login.html'), name='login'),
    path('logout', auth_views.LogoutView.as_view(next_page='login')),
    path('list_envs', pan_cnc_views.ListEnvironmentsView.as_view()),
    path('logs', pan_cnc_views.TaskLogsView.as_view()),
    path('load_env/<env_name>', pan_cnc_views.LoadEnvironmentView.as_view()),
    path('edit_env/<env_name>', pan_cnc_views.EditEnvironmentsView.as_view()),
    path('create_env', pan_cnc_views.CreateEnvironmentsView.as_view()),
    path('clone_env/<clone>', pan_cnc_views.CreateEnvironmentsView.as_view()),
    path('delete_env/<env_name>', pan_cnc_views.DeleteEnvironmentView.as_view()),
    path('delete_secret/<env_name>/<key_name>', pan_cnc_views.DeleteEnvironmentKeyView.as_view()),
    path('unlock_envs', pan_cnc_views.UnlockEnvironmentsView.as_view()),
    path('debug/<app_dir>/<snippet_name>', pan_cnc_views.DebugMetadataView.as_view()),
    path('next_task', pan_cnc_views.NextTaskView.as_view()),
    path('editTarget', pan_cnc_views.EditTargetView.as_view()),
    path('terraform', pan_cnc_views.EditTerraformView.as_view())
]

print('Configuring URLs for installed apps')

indx = 0

for app_name in settings.INSTALLED_APPS_CONFIG:
    app = settings.INSTALLED_APPS_CONFIG[app_name]
    print('Performing CNC App initialization')
    cnc_utils.init_app(app)

    if 'views' not in app:
        print('Skipping app: %s with no views configured' % app_name)
        continue

    for v in app['views']:
        if 'class' not in v or 'name' not in v:
            print('Skipping view with no class configured!')
            continue

        view_class_string = v['class']
        view_name = v['name']
        # common to have the intro page be a blank url portion, reflect that here
        if view_name is None:
            view_name = ''

        # ensure we import the views module here for all apps
        try:
            app_view_module = importlib.import_module('%s.views' % app_name)
        except ModuleNotFoundError:
            print('No view module found for this app!')
            app_view_module = object()

        django_generic_module = importlib.import_module('django.views.generic')
        pancnc_view_module = importlib.import_module('pan_cnc.views')

        # Check in 3 places for the configured view class
        # django generic classes
        # views.py in the custom app
        # views.py in the pan_cnc base library
        # otherwise, bail out as we can't check everywhere
        if hasattr(app_view_module, v['class']):
            class_object = getattr(app_view_module, v["class"])
        elif hasattr(django_generic_module, v['class']):
            class_object = getattr(django_generic_module, v["class"])
        elif hasattr(pancnc_view_module, v['class']):
            class_object = getattr(pancnc_view_module, v["class"])
        else:
            print(f'Could not find the configured view class: {view_class_string} for app: {app_name}')
            continue

        # ensure we always set the app_settings on the context for dynamic menu building
        # FIXME - would this be better done via a template tag library?
        context = {'app_settings': app_settings}
        if 'context' in v and type(v['context']) is dict:
            context.update(v['context'])

        if 'attributes' in v and type(v['attributes'] is dict):
            attributes = dict()
            for attr in v['attributes']:
                if type(attr) is not str:
                    print(f'Invlid attribute found in .pan-cnc.yaml for view: {v["name"]}')
                    continue

                if hasattr(class_object, attr):
                    attributes[attr] = v['attributes'][attr]
        else:
            attributes = dict()

        # ensure the app_dir attribute is always set if it exists on the view object!
        if hasattr(class_object, 'app_dir'):
            if 'app_dir' not in attributes:
                attributes['app_dir'] = app_name

        print(f'Adding src app {app_name} and view: {view_name} to urlpatterns')
        if 'parameter' in v:
            param = v['parameter']
            new_path = path(f'{app_name}/{view_name}/<{param}>', class_object.as_view(**attributes), context)
        elif 'parameters' in v:
            if type(v['parameters']) is not list:
                print(type(v['parameters']))
                print('parameters attribute is not a list!')
                continue

            path_string = f'{app_name}/{view_name}'
            for p in v['parameters']:
                path_string += f'/<{p}>'

            new_path = path(path_string, class_object.as_view(**attributes), context)
        else:
            new_path = path(f'{app_name}/{view_name}', class_object.as_view(**attributes), context)

        # If this is the first app defined and the view_name is '', then add the home page entry here
        if view_name == '' and indx == 0:
            home_path = path('', class_object.as_view(**attributes), context)
            urlpatterns += [home_path]

        urlpatterns += [new_path]
        indx += 1

