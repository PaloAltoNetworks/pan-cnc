# Building a new App using the CNC library

#### Generic folder structure

```bash
cnc-skeleton/
└── src
    └── cnc-app-name
        ├── .pan-cnc.yaml
        ├── snippets
        │   └── README.md
        └── views.py
```


All folders in the 'src' directory are treated as cnc 'apps'. The CNC library will try to automatically load them 
as Django apps on startup. The two most important files are the `.pan-cnc.yaml` and the `views.py` files. 
All your code will live in `src/$APP_NAME/views.py`


#### Install CNC as a submodule to your repo

```bash

git submodule add -b develop git@github.com:PaloAltoNetworks/pan-cnc.git cnc

```

You should now have two top level directories: `src` and `cnc`. 

## Running Pan-CNC
#### 1. Install python requirements

```bash

pip install -r cnc/requirements.txt

```
#### 2. Build the database
```bash

./cnc/manage.py migrate

```

#### 3. Create a new user

NOTE: In the below command, change ***email address*** and ***passwd*** to your respective entries .Common practice 
is to have the password be the name of the app, unless specifically spelled out in your documentation.

```bash

./cnc/manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_superuser('paloalto', 'admin@example.com', 'passwd')"

```

#### Local Development

You can launch this new app with the following commands:

```bash
cd cnc
celery -A pan_cnc worker --loglevel=info  &
./manage.py runserver 8080

```

This will start a background task worker and then start the application on port `8080`. You can login using the 
`username` and `password` specified above. 
