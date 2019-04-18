from django.contrib.auth.signals import user_logged_in
from django.core.signals import request_finished
from django.dispatch import receiver
from django.conf import settings
from django.core.handlers.wsgi import WSGIHandler
from django.core.cache import cache
from . import cnc_utils


@receiver(user_logged_in)
def handle_login(user, request, **kwargs) -> None:
    first_app = list(settings.INSTALLED_APPS_CONFIG)[0]
    print(f'Setting current_app_dir to {first_app}')
    request.session['current_app_dir'] = first_app


@receiver(request_finished)
def save_long_term_cache(sender, **kwargs) -> None:
    apps_to_save = cache.get('ltc_dirty', list())
    for app_name in apps_to_save:
        cache_key = f"{app_name}_cache"
        ltc = cache.get(cache_key, dict())
        print(f'Saving {app_name} to long term cache')
        cnc_utils.save_long_term_cache(app_name, ltc)

    cache.set('ltc_dirty', list())
