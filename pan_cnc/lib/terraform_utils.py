import json
from pathlib import Path
from celery.result import EagerResult
from celery.result import AsyncResult

from pan_cnc.tasks import terraform_init, terraform_validate, terraform_plan, terraform_apply, terraform_refresh, \
    terraform_destroy, terraform_output


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
