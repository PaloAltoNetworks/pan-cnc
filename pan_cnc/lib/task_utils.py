import json
import os
from pathlib import Path

from celery.result import AsyncResult
from celery.result import EagerResult
from django.conf import settings

from pan_cnc.celery import app as cnc_celery_app
from pan_cnc.lib.exceptions import CCFParserError
from pan_cnc.tasks import python3_execute_bare_script
from pan_cnc.tasks import python3_execute_script
from pan_cnc.tasks import python3_init_with_deps
from pan_cnc.tasks import terraform_apply
from pan_cnc.tasks import terraform_destroy
from pan_cnc.tasks import terraform_init
from pan_cnc.tasks import terraform_output
from pan_cnc.tasks import terraform_plan
from pan_cnc.tasks import terraform_refresh
from pan_cnc.tasks import terraform_validate


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


def perform_init(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_init.delay(resource_dir, tf_vars)


def perform_validate(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_validate.delay(resource_dir, tf_vars)


def perform_plan(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_plan.delay(resource_dir, tf_vars)


def perform_apply(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_apply.delay(resource_dir, tf_vars)


def perform_output(resource_def, snippet_context) -> EagerResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_output.apply(args=[resource_dir, tf_vars])


def perform_refresh(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_refresh.delay(resource_dir, tf_vars)


def perform_destroy(resource_def, snippet_context) -> AsyncResult:
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_destroy.delay(resource_dir, tf_vars)


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
    print(f"Performing python3 init")
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)
    tools_dir = os.path.join(settings.CNC_PATH, 'tools')
    return python3_init_with_deps.delay(resource_dir, tools_dir)


def python3_execute(resource_def, args) -> AsyncResult:
    (script_path, script_name) = _normalize_python_script_path(resource_def)
    input_type = get_python_input_options(resource_def)
    return python3_execute_script.delay(script_path, script_name, input_type, args)


def python3_init_complete(resource_def) -> bool:
    print(f"Performing python3 check")
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)
    init_done_file = os.path.join(resource_dir, '.python3_init_done')
    if os.path.exists(init_done_file):
        print('python3 init complete')
        return True
    else:
        return False


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


def verify_clean_state(resource_def) -> bool:
    # Verify the tfstate file does NOT exist or contain resources if it does exist
    resource_dir = resource_def['snippet_path']
    rd = Path(resource_dir)
    state_file = rd.joinpath('terraform.tfstate')
    print(f'checking {state_file}')
    if state_file.exists() and state_file.is_file():
        print('It exists, so lets check it out')
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
