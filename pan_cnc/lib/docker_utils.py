import random

import docker
from docker.errors import ContainerError
from docker.errors import DockerException
from docker.models.containers import Container

from .exceptions import DockerExecutionException


# from urllib3.connection import HTTPException


class DockerClient:
    """
    Simple class to execute a single command in an ephemeral docker image. An imported repository is mounted as a volume
    and the working directory is set to the directory where the current skillet is located. The repository is mounted
    as /repo and the working dir is set to /repo by default
    """

    def __init__(self, repository_dir: str):
        self._docker_url = 'unix://var/run/docker.sock'
        self._docker_cmd = 'run'
        self._docker_image = 'alpine'
        self._repository_dir = repository_dir
        self._name = None
        self._bind_dir = '/repo'
        self._working_dir = '/repo'
        self._environment = list().append('CNC=True')
        self._volumes = dict()
        self._container = ''

    @property
    def docker_url(self) -> str:
        return self._docker_url

    @docker_url.setter
    def docker_url(self, value: str) -> None:
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
    def docker_cmd(self, value: str) -> None:
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
    def docker_image(self, value: str):
        self._docker_image = value

    @property
    def repository_dir(self):
        return self._repository_dir

    @repository_dir.setter
    def repository_dir(self, value: str):
        self._repository_dir = value

    @repository_dir.deleter
    def repository_dir(self):
        self._repository_dir = None

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def bind_dir(self):
        return self._bind_dir

    @bind_dir.setter
    def bind_dir(self, value: str):
        self._bind_dir = value

    @property
    def working_dir(self):
        return self._working_dir

    @working_dir.setter
    def working_dir(self, value: str):
        self._working_dir = value

    @property
    def environment(self) -> list:
        return self._environment

    @environment.setter
    def environment(self, value: (list, str)) -> None:
        """
        List of environment variables to pass. Example is ['CNC=TRUE']. Each list element is simply a KEY=VALUE string
        where key and value are separated by a '='
        :param value: List of string elements
        :return: None
        """
        if type(value) is str and ',' in value:
            self._environment = value.split(',')
        elif type(value) is str:
            self._environment = list().append(value)
        elif type(value) is list:
            self._environment = value

    @property
    def volumes(self) -> dict:
        return self._volumes

    @volumes.setter
    def volumes(self, value: str) -> None:
        self._volumes = value

    @property
    def container(self) -> Container:
        return self._container

    @container.setter
    def container(self, value: Container) -> None:
        self._container = value

    def execute_cmd(self, cmd=None) -> None:
        """
        Executes the given command in the container
        """

        try:
            client = docker.DockerClient(base_url=self.docker_url)
            if cmd is None:
                cmd = self.docker_cmd

            # if the user has not specified a name, let's create something random with the 'cnc_' prefix. This will
            # allow us to clean these up later if needed
            if self.name is None:
                self.name = 'cnc_' + str(int(random.random() * 1000000000))

            # ensure we have at least the current repository as a mounted volume if the user has not specified
            # a volume configuration already
            if self.repository_dir not in self.volumes:
                self.volumes = {self.repository_dir: {'bind': self.bind_dir, 'mode': 'rw'}}

            if self.container == '':
                self.container = client.containers.run(self.docker_image, cmd, volumes=self.volumes,
                                                       working_dir=self.working_dir,
                                                       name=self.name,
                                                       auto_remove=False, environment=self.environment, detach=True)
            else:
                self.container.exec_run(cmd, environment=self.environment, workdir=self.working_dir, detach=True)

            return self.container.id

        except docker.errors.APIError as ae:
            raise DockerExecutionException(ae)

        except ContainerError as ce:
            raise DockerExecutionException(ce)

        except DockerException as conn_err:
            raise DockerExecutionException(conn_err)

        except RuntimeError as rte:
            raise DockerExecutionException(rte)

    def get_output(self, container_id: str) -> str:
        """
        Returns the output for the given container_id
        :return: log output
        """
        try:
            if type(self.container) is not Container:
                self.container = self.__get_container(container_id)

            return self.container.logs()

        except (DockerExecutionException, docker.errors.APIError) as e:
            return f'Could not get logs for container {container_id}: {e}'

    def __get_container(self, container_id: str) -> (Container, None):
        try:
            client = docker.DockerClient(base_url=self.docker_url)
            return client.containers.get(container_id)
        except docker.errors.NotFound:
            raise DockerExecutionException('Container Not Found')
        except docker.errors.APIError:
            raise DockerExecutionException('Could not contact Docker daemon')

    def clean_up(self, container_id) -> bool:
        try:
            if type(self.container) is not Container:
                self.container = self.__get_container(container_id)

            self.container.remove()
            self.container = ''
            return True

        except (DockerExecutionException, docker.errors.APIError) as e:
            print(e)
            return False
