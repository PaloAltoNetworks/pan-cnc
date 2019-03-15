## Install CNC as a submodule to your repo
```bash
git submodule add -b develop git@github.com:PaloAltoNetworks/pan-cnc.git cnc
```

## Running Pan-CNC

#### 1. Build the database
```bash 
./cnc/manage.py migrate
```

#### 2. Create a new user
NOTE: In the below command, change ***email address*** and ***passwd*** to your respective entries .Common practice is to have the password be the name of the app, unless specifically spelled out in your documentation
```bash
./cnc/manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_superuser('paloalto', 'admin@example.com', 'passwd')"
```
