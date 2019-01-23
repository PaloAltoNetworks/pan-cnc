import os
import re
import time

import docker
from docker.errors import ContainerError, DockerException
from docker.models.containers import Container

from pan_cnc.lib.actions.AbstractAction import AbstractAction


# from urllib3.connection import HTTPException


class DockerAction(AbstractAction):
    """
        Copies a template to a volume mounted location, then runs a docker container with that volume mounted
        volumes can be persistent or ephemeral
    """

    def __init__(self):
        self._template_name = ''
        # self._docker_url = 'tcp://127.0.0.1:2376'
        self._docker_url = 'unix://var/run/docker.sock'
        self._docker_cmd = 'run'
        self._docker_image = 'alpine'
        self._storage_dir = 'unique_dir_name_for_workflow'
        self._persistent_dir = '/tmp/cnc/'
        self._working_dir = '/cnc'
        self._environment = list().append('CNC=True')
        self._container = ''

    @property
    def template_name(self) -> str:
        """
        Returns the configured template_name property
        :return: str
        """
        return self._template_name

    @template_name.setter
    def template_name(self, value) -> None:
        """
        Name of the template to write into the working directory in the container
        :param value: filename
        :return: None
        """
        self._template_name = value

    @property
    def docker_url(self) -> str:
        return self._docker_url

    @docker_url.setter
    def docker_url(self, value) -> None:
        """
        URL of the docker API Default is tcp://127.0.0.1:2376'
        :param value: str to the URL
        :return:
        """
        self._docker_url = value

    @property
    def docker_cmd(self) -> str:
        return self._docker_cmd

    @docker_cmd.setter
    def docker_cmd(self, value) -> None:
        """
        Command to run inside the docker container
        :param value: full path to command string to execute
        :return: None
        """
        self._docker_cmd = value

    @property
    def docker_image(self):
        return self._docker_image

    @docker_image.setter
    def docker_image(self, value):
        self._docker_image = value

    @property
    def storage_dir(self):
        return self._storage_dir

    @storage_dir.setter
    def storage_dir(self, value):
        self._storage_dir = value

    @property
    def persistent_dir(self):
        return self._persistent_dir

    @persistent_dir.setter
    def persistent_dir(self, value):
        self._persistent_dir = value

    @property
    def working_dir(self):
        return self._working_dir

    @working_dir.setter
    def working_dir(self, value):
        self._working_dir = value

    @property
    def environment(self) -> list:
        return self._environment

    @environment.setter
    def environment(self, value: list):
        """
        List of environment variables to pass. Example is ['CNC=TRUE']. Each list element is simply a KEY=VALUE string
        where key and value are separated by a '='
        :param value: List of string elements
        :return: None
        """
        self._environment = value

    @property
    def container(self) -> Container:
        return self._container

    @container.setter
    def container(self, value) -> None:
        self._container = value

    def create_file_in_persistent_dir(self, template_name, template):
        """
        Creates a file in the persistent dir using the supplied template as it's contents
        :param template_name: full path to the file to create inside the docker container persistent directory
        :param template: contents of the template/file to create
        :return: boolean
        """
        if not os.path.exists(self.persistent_dir):
            print('Creating docker volume dir')
            os.makedirs(self.persistent_dir)

        print('Using storage_dir of: %s' % self.storage_dir)

        # ensure only relative path here, replace all leading '/' with nothing
        if self.storage_dir.startswith('/'):
            self.storage_dir = re.sub('^/+', '', self.storage_dir)

        if len(self.storage_dir) == 0:
            self.storage_dir = 'docker_container_action'

        instance_path = os.path.join(self.persistent_dir, self.storage_dir)
        print('Using instance_dir of: %s' % instance_path)

        if not os.path.exists(instance_path):
            os.makedirs(instance_path)

        try:
            # if a template was specified then write it out into the working directory
            cleaned_template = template.replace('\r\n', '\n')
            path = os.path.join(instance_path, template_name)
            with open(path, 'w+') as f:
                f.write(cleaned_template)

        except OSError as oe:
            print('Could not write file into docker container persistent dir')
            return

    def execute_template(self, template=''):
        """
        """

        if type(self.environment) is str:
            if self.environment == "":
                env = ["CNC=True"]
            else:
                env = self.environment.split(',')
        elif type(self.environment) is list:
            if not self.environment:
                env = ["CNC=True"]
            else:
                env = self.environment
        else:
            env = ["CNC=True"]

        if self.template_name != '':
            self.create_file_in_persistent_dir(self.template_name, template)

        try:
            client = docker.DockerClient(base_url=self.docker_url)
            # client = docker.DockerClient()
            instance_path = os.path.join(self.persistent_dir, self.storage_dir)
            vols = {instance_path: {'bind': self.working_dir, 'mode': 'rw'}}
            print(vols)
            self.container = client.containers.run(self.docker_image, self.docker_cmd, volumes=vols,
                                                   working_dir=self.working_dir,
                                                   auto_remove=False, environment=env, detach=True)
            timer = 1
            while timer < 60:
                time.sleep(1)
                self.container.reload()
                print('Checking for output')
                print(self.container.status)
                if self.container.status == 'exited':
                    logs = self.container.logs().decode("utf-8")
                    self.container.remove()
                    return logs
                timer += 1

            return self.container.logs()

        except docker.errors.APIError as ae:
            print(ae)
            return ae

        except ContainerError as ce:
            print(ce)
            return ce

        except DockerException as conn_err:
            print(conn_err)
            return "Could not connect to docker API"

        except RuntimeError as rte:
            print('Could not run container command')
            return str(rte)

    def get_output(self):
        """
        Returns the complete output of the container
        :return:
        """
        if self.container != '':
            return self.container.logs()

        return 'No Container found'
