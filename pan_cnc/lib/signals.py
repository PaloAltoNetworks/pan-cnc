from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.conf import settings


@receiver(user_logged_in)
def handle_login(user, request, **kwargs):
    first_app = list(settings.INSTALLED_APPS_CONFIG)[0]
    print(f'Setting current_app_dir to {first_app}')
    request.session['current_app_dir'] = first_app

