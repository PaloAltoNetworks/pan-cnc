# Getting Started with Pan-CNC


## Background

Pan-CNC can create apps quicky by configuring itself via a .pan-cnc.yaml file. Normal mode of operation is:

1. create a tool / set of snippets / etc
2. upload tool to git repository
3. create a .pan-cnc.yaml file im the root of the project
4. create a distributable application by combining the pan-cnc repo with your freshly created repo
    project structure is:
        root:
            cnc: this pan-cnc git repo
            src:
                your-app: git repository of your tool
                other-app-1: another app that might be useful to be included
                other-app-2: yet another app
5. this distributable app can be its own git repository and pull in pan-cnc and your app via git submodules, or
 you can use docker build files to pull in the deps and build a container containing all the requirements necessary


## Example pan-cnc.yaml

name: nates_test_app

views:
  - name: ''
    class: CNCView
    menu: Nates Test App
    menu_option: LETS GO
    attributes:
      template_name: pan_cnc/welcome.html
    context:
      title: Nates TEST APP
      description: Some nice long descrition here!
      documentation_link: http://natestestapp.readthedocs.io

  - name: 'configure'
    class: ChooseSnippetView
    menu: Nates Test App
    menu_option: GPCS
    attributes:
      snippet: cnc-conf-gpcs
      header: Step 1
      title: Choose GPCS Snippet

  - name: 'provision'
    class: ProvisionSnippetView     

       
                
## Running Pan-CNC

1. Build the database
```bash 
./cnc/manage.py migrate
```

2. Create a new user
```bash
./cnc/manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_superuser('vistoq', 'admin@example.com', 'vistoq')"
```