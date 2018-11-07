from abc import ABC


class AbstractAction(ABC):
    import abc

    @abc.abstractmethod
    def execute_template(self, template):
        """
        :param template: thh configuration template to be executed from the input_form
        :return:
        """
        return

    def get_config_options(self):
        return []

    # def get_default_config(self):
    #     default_config = dict()
    #     for item in self.get_config_options():
    #         default_config[item['name']] = item['default']
    #
    #     return ActionConfig(default_config)

    def set_global_options(self, data):
        """
        :param data: class data from the settings.py file if configured
        :return:
        """

        for member in data:
            if hasattr(self, member):
                setattr(self, member, str(data[member]))

        return

    def set_instance_options(self, data):
        """
        :param data: instance data from the admin configured template file
        :return: None
        """
        for member in data:
            if hasattr(self, member):
                setattr(self, member, data[member]["value"])

        return

    @staticmethod
    def continue_workflow(self, can_continue, exit_message):
        """
        :param can_continue: boolean - should workflow continue? Similar to stderr in Unix pipes
        :param exit_message: String - Similar to stdout
        :return:
        """
        return {"continue": can_continue, "message": exit_message}


