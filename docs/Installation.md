git submodule add -b develop git@github.com:PaloAltoNetworks/pan-cnc.git cnc

## Running Pan-CNC

1. Build the database
```bash 
./cnc/manage.py migrate
```

2. Create a new user
```bash
./cnc/manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_superuser('vistoq', 'admin@example.com', 'vistoq')"
```