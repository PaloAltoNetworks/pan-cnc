import json
import os
from datetime import datetime
from pathlib import Path

from celery.result import AsyncResult
from django.conf import settings

from pan_cnc.celery import app as cnc_celery_app
from pan_cnc.lib.exceptions import CCFParserError
from pan_cnc.tasks import execute_docker_skillet
from pan_cnc.tasks import python3_execute_bare_script
from pan_cnc.tasks import python3_execute_script
from pan_cnc.tasks import python3_init_with_deps


def __build_cmd_seq_vars(resource_def, snippet_context):
    if 'variables' not in resource_def:
        print('No resource def found or mis-configured')
        return None

    sanity_checked_vars = dict()
    for v in list(resource_def['variables']):
        var_name = v['name']
        var_type = v['type_hint']
        if var_name in snippet_context:
            if var_type == 'list' and type(snippet_context[var_name]) is list:
                try:
                    sanity_checked_vars[var_name] = json.dumps(snippet_context[var_name])
                except ValueError:
                    print('Could not convert list to terraform list string')
                    sanity_checked_vars[var_name] = snippet_context[var_name]
            else:
                sanity_checked_vars[var_name] = snippet_context[var_name]
        else:
            print('Not found in snippet_context')

    # print(sanity_checked_vars)
    return sanity_checked_vars


def perform_terraform_cmd(resource_def: dict, cmd: str, snippet_context: dict) -> AsyncResult:
    """
    Performs various terraform related tasks such as 'init', 'plan', 'validate' etc.
    This function will determine the correct image to use and configure the resource_def
    as appropriate before sending to skilletlib for execution

    :param resource_def: Skillet metadata
    :param cmd: terraform command to execute
    :param snippet_context: context to send to skilletlib
    :return: AsyncResult from Celery
    """
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)

    env = dict()
    for k, v in tf_vars.items():
        env[f'TF_VAR_{k}'] = v

    # fix for #100 - always set home to /home/cnc_user for terraform type docker containers
    env['HOME'] = '/home/cnc_user'

    # FIXME - skilletlib should have terraform type just extend docker where possible
    resource_def['type'] = 'docker'

    # terraform skillets do not use snippets attribute, so overwrite here
    resource_def['snippets'] = list()

    snippet = dict()
    snippet['name'] = 'terraform_cmd'
    snippet['image'] = __get_terraform_image(resource_def)
    snippet['cmd'] = cmd
    snippet['async'] = True

    resource_def['snippets'].append(snippet)

    print('Performing skillet execute')
    return execute_docker_skillet.delay(resource_def, env)


def __get_terraform_image(resource_def: dict) -> str:
    """
    Check the skillet metadata (resource_def) for a label with key
    'terraform_image', and if found use that docker image to execute
    our terraform commands

    :param resource_def: Skillet metadata as loaded from the .meta-cnc file
    :return: str containing the value of the 'terraform_image' if found, otherwise
        a default value
    """

    for label, value in resource_def.get('labels', dict()).items():
        if label == 'terraform_image':
            return value

    # FIXME - update with new default image as it gets built
    return 'registry.gitlab.com/panw-gse/as/terraform_tools:0.11'


def perform_init(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform init')
    cmd = 'init -no-color'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_validate(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform validate')
    cmd = 'validate -no-color'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_plan(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform plan')
    cmd = 'plan -no-color -out=".cnc_plan"'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_apply(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform apply')
    cmd = 'apply -no-color -auto-approve ./.cnc_plan'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_output(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform output')
    cmd = 'output -no-color -json'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_refresh(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform refresh')
    cmd = 'refresh -no-color'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def perform_destroy(resource_def, snippet_context) -> AsyncResult:
    print('Executing task terraform destroy')
    cmd = 'destroy -no-color -auto-approve'
    return perform_terraform_cmd(resource_def, cmd, snippet_context)


def python3_check_no_requirements(resource_def) -> bool:
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)
    req_file = os.path.join(resource_dir, 'requirements.txt')

    if os.path.exists(req_file):
        print('requirements.txt exists')
        return False
    else:
        return True


def python3_execute_bare(resource_def, args) -> AsyncResult:
    (script_path, script_name) = _normalize_python_script_path(resource_def)
    input_type = get_python_input_options(resource_def)
    return python3_execute_bare_script.delay(script_path, script_name, input_type, args)


def python3_init(resource_def) -> AsyncResult:
    print("Performing python3 init")
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)
    tools_dir = os.path.join(settings.CNC_PATH, 'tools')
    return python3_init_with_deps.delay(resource_dir, tools_dir)


def python3_execute(resource_def, args) -> AsyncResult:
    (script_path, script_name) = _normalize_python_script_path(resource_def)
    input_type = get_python_input_options(resource_def)
    return python3_execute_script.delay(script_path, script_name, input_type, args)


def python3_init_complete(resource_def) -> bool:
    print("Performing python3 check")
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)
    init_done_file = os.path.join(resource_dir, '.python3_init_done')
    if os.path.exists(init_done_file):
        print('python3 init complete')
        return True
    else:
        return False


def skillet_execute(skillet_def: dict, args: dict) -> AsyncResult:
    print('Performing skillet execute')
    return execute_docker_skillet.delay(skillet_def, args)


def python3_reset_init(script_roots: str) -> None:
    """
    Remove the touch file that indicates the virtualenv is already set up. This forces an update
    to the virtualenv. This gets called whenever a repository is updated by the user

    :param script_roots: the directory in which to search for the touch files
    :return: None
    """
    path = Path(script_roots)
    touch_files = path.rglob('.python3_init_done')
    for tf in touch_files:
        print(f'Resetting python init touch file in dir: {tf}')
        tf.unlink()


def _normalize_python_script_path(resource_def: dict) -> tuple:
    if 'snippet_path' not in resource_def:
        raise CCFParserError('Malformed .meta-cnc file for python3 execution')

    resource_dir = resource_def['snippet_path']
    if 'snippets' in resource_def and len(resource_def['snippets']) > 0:
        # python type only uses first snippet from list
        snippet = resource_def['snippets'][0]
        if 'file' in snippet and 'name' in snippet:
            script = snippet['file']

            if '/' not in script:
                script = f"./{script}"

            # ensure no funny business
            skillet_base_path = Path(resource_dir)
            print(skillet_base_path)
            script_path = skillet_base_path.joinpath(script).resolve()
            print(script_path)
            # # if skillet_base_path not in script_path.parents:
            #     raise CCFParserError('Malformed .meta-cnc file for python3 execution - Refusing to jump out of dir')

            return str(script_path.parent), script_path.name
        else:
            raise CCFParserError('Malformed .meta-cnc file for python3 execution - Malformed snippet')
    else:
        raise CCFParserError('Malformed .meta-cnc file for python3 execution - Malformed snippet')


def get_python_input_options(resource_def: dict) -> str:
    """
    Determine how input variables from the view should be passed to this script. An optional snippet parameter
    called 'input_type' is checked to determine whether 'cli' or 'env' should be used. 'cli' indicates input
    variables will be passed along as long form arguments to the python script on the cli (for example:
    --first_arg=arg1_val --second_arg=arg2_val). 'env' indicates env variables will be set (for example:
    export first_arg=arg1_var; export second_arg=arg2_val)

    :param resource_def: the compiled .meta-cnc file
    :return: str of either 'cli' or 'env'
    """
    if 'snippet_path' not in resource_def:
        raise CCFParserError('Malformed .meta-cnc file for python3 execution')

    try:
        if 'snippets' in resource_def and len(resource_def['snippets']) > 0:
            # python type only uses first snippet from list
            snippet = resource_def['snippets'][0]
            if 'input_type' in snippet:
                if str(snippet['input_type']).lower() == 'cli':
                    return 'cli'
                elif str(snippet['input_type']).lower() == 'env':
                    return 'env'
                else:
                    return 'cli'

            return 'cli'
    except TypeError:
        raise CCFParserError('Malformed .meta-cnc file for python3 execution - Malformed snippet')


def __get_state_file_from_path(resource_def: dict) -> (Path, None):
    """
    Find and return the terraform state file for the given skillet resource_def

    :param resource_def: Skill definition file
    :return: pathlib.Path object of the found state file or None
    """
    resource_dir = resource_def['snippet_path']
    rd = Path(resource_dir)
    state_file = rd.joinpath('terraform.tfstate')
    print(f'checking {state_file}')

    if state_file.exists() and state_file.is_file():
        return state_file
    else:
        return None


def terraform_state_exists(resource_def: dict) -> bool:
    """
    Used by View class to determine if we need to present options to the user about overwriting or backing up
    a state file. This will locate the state file and determine if it contains resources

    :param resource_def: Skillet definition file
    :return:
    """
    state_file = __get_state_file_from_path(resource_def)

    if not state_file:
        return False

    if verify_empty_tf_state(state_file):
        # reverse the logic from the verify_empty_tf_state call
        # if the state exists and it is empty, then return False
        return False

    # exists but is not empty
    return True


def verify_empty_tf_state(state_file: (Path, None)) -> bool:
    """

    Verifies that if a terraform.tfstate file exists for the given skillet that it is empty
    or that no state file exists.

    :param state_file: Terraform state path object
    :return: bool True if state does not exist or no resources found in state
    """

    if state_file is None:
        return True

    # we have had a state at some point in the past
    with state_file.open(mode='r') as state_object:
        state_data = json.loads(state_object.read())
        print(state_data)
        modules = state_data.get('modules', [])
        for module in modules:
            if 'resources' in module:
                print('We have resources')
                if len(module['resources']) > 0:
                    return False
                else:
                    return True
    return True


def override_tfstate(resource_def: dict) -> str:
    """
    Will create a new terraform state file and back up the existing one if necessary
    Will only create a new terraform state file if there are found to be existing resources in the file
    This is dangerous!

    :param resource_def: Skillet Definition dictionary
    :return: Name of the terraform.tfstate file
    """

    # check if there are resources defined in the state file
    state_file = __get_state_file_from_path(resource_def)
    new_name = state_file.absolute()
    if not verify_empty_tf_state(state_file):
        current_name = state_file.absolute()
        current_modtime_stamp = state_file.stat().st_mtime
        current_modtime = datetime.fromtimestamp(current_modtime_stamp).strftime("%b-%d-%y-%H_%M_%S")
        new_name = f'{current_name}-{current_modtime}'
        state_file.rename(new_name)

    return new_name


def purge_all_tasks() -> None:
    num_tasks = cnc_celery_app.control.purge()
    print(f'Purged {num_tasks} tasks from queue')
    return None


def clean_task_output(output: str) -> str:
    """
    Remove CNC metadata from task output. In some cases we need to return data from the task to the cnc application.
    The only available route to do this is by injecting metadata into the text output from the task. This is done by
    simply prefixing out metadata with 'CNC:'. This function will remove any metadata from the task output in order
    to present it to the user

    :param output: str of output with metadata possibly present
    :return: str of output with no metadata present
    """
    cleaned_output = ""
    for line in output.splitlines():
        if not line.startswith('CNC:'):
            cleaned_output += f'{line}\n'

    return cleaned_output
