import json
import os
from pathlib import Path

from celery.result import AsyncResult
from celery.result import EagerResult

from pan_cnc.celery import app as cnc_celery_app

from pan_cnc.lib.exceptions import CCFParserError
from pan_cnc.tasks import terraform_init, terraform_validate, terraform_plan, terraform_apply, terraform_refresh, \
    terraform_destroy, terraform_output, python3_init_env, python3_init_with_deps, python3_execute_script, \
    python3_init_existing, python3_execute_bare_script


def __build_cmd_seq_vars(resource_def, snippet_context):
    if 'variables' not in resource_def:
        print('No resource def found or mis-configured')
        return None

    tf_vars = dict()
    for v in list(resource_def['variables']):
        var_name = v['name']
        if var_name in snippet_context:
            tf_vars[var_name] = snippet_context[var_name]
        else:
            print('Not found in snippet_context')

    print(tf_vars)
    return tf_vars


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
    return python3_execute_bare_script.delay(script_path, script_name, args)


def python3_init(resource_def) -> AsyncResult:
    print(f"Performing python3 init")
    (resource_dir, script_name) = _normalize_python_script_path(resource_def)

    print(f"Resource dir is {resource_dir}")
    req_file = os.path.join(resource_dir, 'requirements.txt')
    print(f"req_file is {req_file}")

    init_done_file = os.path.join(resource_dir, '.python3_init_done')

    with open(init_done_file, 'w+') as init_done:
        init_done.write('y')

    venv_path = os.path.join(resource_dir, '.venv')
    if os.path.exists(req_file) and os.path.exists(venv_path):
        return python3_init_existing.delay(resource_dir)

    elif os.path.exists(req_file):
        print('requirements.txt exists')
        return python3_init_with_deps.delay(resource_dir)
    else:
        print('no requirements.txt exists')
        return python3_init_env.delay(resource_dir)


def python3_execute(resource_def, args) -> AsyncResult:
    (script_path, script_name) = _normalize_python_script_path(resource_def)
    return python3_execute_script.delay(script_path, script_name, args)


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

