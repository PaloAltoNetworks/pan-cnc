
from django.core.cache import cache
from .pan_utils import load_panrc

if not cache.get('panrc'):
    panrc = load_panrc()
    print('setting up the panrc')
    cache.set('panrc', panrc)
else:
    print('panrc is already cached')

