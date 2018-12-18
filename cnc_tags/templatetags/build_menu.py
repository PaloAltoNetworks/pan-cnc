from django import template
from django.conf import settings
from django.core.cache import cache

register = template.Library()


@register.simple_tag
def build_menu():

    menu = cache.get('pan_cnc_menu', None)
    if menu is not None:
        return menu

    menu = dict()
    installed_apps = settings.INSTALLED_APPS_CONFIG
    if type(installed_apps) is not dict:
        return {}

    for app in installed_apps.keys():
        app_config = installed_apps[app]
        if 'views' in app_config:
            for view in app_config['views']:
                if 'name' not in view:
                    continue
                view_name = view['name']
                if 'menu' in view and 'menu_option' in view:
                    menu_label = view['menu']

                    menu_item = dict()
                    menu_item['label'] = view['menu_option']
                    menu_item['value'] = f'/{app}/{view_name}'

                    if menu_label in menu:
                        menu_label_list = menu[menu_label]
                    else:
                        menu_label_list = list()

                    menu_label_list.append(menu_item)
                    menu[menu_label] = menu_label_list

    cache.set('pan_cnc_menu', menu)
    return menu
