import logging
import os

import docker
from docker.errors import APIError
from requests.exceptions import ConnectionError

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

    def check_docker_server(self) -> bool:
        """
        Verifies communication with the docker server

        :return: boolean true on success
        """

        try:
            self.client.ping()

        except APIError as ae:
            logger.error(ae)
            return False

        except ConnectionError as ce:
            logger.error(
                'This is a connection error'
            )
            logger.error(ce)
            return False

        except Exception as e:
            logger.error(' Basic exception here')
            logger.error(e)
            return False

        return True

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

    def get_cnc_volumes(self) -> (dict, None):
        """
        Returns volume mounts from the HOST application container that contains the HOME
        directory of the cnc_user and also the .pan_cnc folder if found. In some cases, these may be
        the same mount (only mount $HOME) in other cases, they may be two different mounts

        :return: dict containing volume mounts to pass to
        """

        home_dir = os.environ.get('HOME', '/home/cnc_user')
        persistent_dir = '.pan_cnc'

        persistent_volumes = dict()

        if not self.is_docker():
            # let's mount the this uses's .pan_cnc folder instead of just nothing
            user_pancnc_dir = os.path.abspath(os.path.join(home_dir, persistent_dir))
            persistent_volumes[user_pancnc_dir] = {
                'bind': user_pancnc_dir, 'mode': 'rw'
            }
            print(persistent_volumes)
            return persistent_volumes

        if not self.check_docker_server():
            return None

        this_container = self.get_container_id()
        volumes = self.get_volumes_for_container(this_container)

        for v in volumes:
            print(f'Checking {v}')
            parts = v.split(':')
            source_vol: str = parts[0]
            dest_dir: str = parts[1]

            # match destinations like 'pan_cnc_volume:/home/cnc_user/.pan_cnc'
            # or 'panhandler_volume:/home/cnc_user'

            if dest_dir == home_dir or dest_dir.endswith(persistent_dir):
                persistent_volumes[source_vol] = {
                    'bind': dest_dir, 'mode': 'rw'
                }

        return persistent_volumes

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

    def get_container_logs(self) -> str:
        """
        Returns the last 75 lines of log output for this container (if found)

        :return: logs as str
        """

        this_container_id = self.get_container_id()
        if this_container_id == '':
            return 'No logs found, could not get container id'

        return self.client.logs(tail=75, container=this_container_id).decode('utf-8')
