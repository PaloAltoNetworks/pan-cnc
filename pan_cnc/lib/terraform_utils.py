from pan_cnc.lib.actions.DockerAction import DockerAction
from pan_cnc.tasks import terraform_init, terraform_validate, terraform_plan, terraform_apply, terraform_destroy


def __build_cmd_seq_vars(resource_def, snippet_context):
    if 'variables' not in resource_def:
        print('No resource def found or misconfigured')
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


def perform_init(resource_def, snippet_context):
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_init.delay(resource_dir, tf_vars)


def perform_validate(resource_def, snippet_context):
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_validate.delay(resource_dir, tf_vars)


def perform_plan(resource_def, snippet_context):
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_plan.delay(resource_dir, tf_vars)


def perform_apply(resource_def, snippet_context):
    resource_dir = resource_def['snippet_path']
    tf_vars = __build_cmd_seq_vars(resource_def, snippet_context)
    return terraform_apply.delay(resource_dir, tf_vars)

