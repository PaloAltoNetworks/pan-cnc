# Copyright (c) 2018, Palo Alto Networks
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

# Author: Nathan Embery nembery@paloaltonetworks.com

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


