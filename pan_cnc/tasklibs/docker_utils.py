import logging
import os

import docker
from docker.errors import ContainerError


logger = logging.getLogger(__name__)


class DockerHelperException(BaseException):
    pass


class DockerHelper:
    """
    Simple class to help with working with docker containers
    """

    def __init__(self):

        # assume docker.sock is available
        self.client = docker.APIClient()

    def get_volumes_for_container(self, container_id: str) -> list:
        """
        Get the attached volumes as a list of ':' separated strings
        :param container_id: container id string
        :return: list such as ['pan_cnc_volume:/home/cnc_user/.pan_cnc']
        """

        try:
            container_dict: dict = self.client.inspect_container(container_id)
            return container_dict['HostConfig']['Binds']

        except KeyError as ke:
            logger.error(ke)
            raise DockerHelperException('Could not find attached volumes on container')

        except docker.errors.NotFound as dne:
            logger.error(dne)
            raise DockerHelperException('Container Not Found')

        except docker.errors.APIError as ae:
            logger.error(ae)
            raise DockerHelperException('Could not contact Docker daemon')

    def get_cnc_volume(self) -> (str, None):
        """
        Returns the bind / mount that contains the '.pan_cnc' directory (if any)
        :return: string of the bind configuration or None if not found
        """

        if not self.is_docker():
            return None

        this_container = self.get_container_id()
        volumes = self.get_volumes_for_container(this_container)

        home_dir = os.environ.get('HOME', '/home/cnc_user')
        persistent_dir = os.path.join(home_dir, '.pan_cnc')

        for v in volumes:
            if persistent_dir in v:
                logger.info('Found CNC persistent mount')
                return v

    @staticmethod
    def is_docker() -> bool:
        """
        Detect if we are in a docker container
        :return: True if it is found that we are running in a container
        """
        path = '/proc/self/cgroup'
        return (
                os.path.exists('/.dockerenv') or
                os.path.isfile(path) and any('docker' in line for line in open(path))
        )

    @staticmethod
    def get_container_id() -> str:
        """
        Find our current container id, the id of the container in which this process is running
        :return: container_id as string (for example: 6e2edce66211371bd7b2baefaf9eb4c505ef7ae001b3c8e389c2efe3df1bc6ca)
        """
        path = '/proc/self/cgroup'

        container_id = ''

        try:
            if not os.path.isfile(path):
                logger.info('does not appear that we are in a container')
                return container_id

            with open(path, 'r') as cgroup:
                for line in cgroup:
                    if ':/docker/' in line:
                        container_id = line.split('/')[-1].strip()

        except OSError as ose:
            logger.error('Could not find container id')
            logger.error(ose)

        finally:
            logger.debug(f'Found container_id :{container_id}:')
            return container_id
