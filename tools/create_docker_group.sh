#!/bin/sh

DOCKER_SOCKET=/var/run/docker.sock
DOCKER_GID=$(stat -c %g ${DOCKER_SOCKET})

if [ "${DOCKER_GID}" -eq "0" ];
 then
  exit 0
fi

DOCKER_GROUP=$(grep "${DOCKER_GID}" /etc/group | cut -f1 -d':')

if [ "${DOCKER_GROUP}" != "" ];
 then
  echo "Adding user to existing group"
  groupadd cnc_user "${DOCKER_GROUP}"
else
  echo "Creating new group and adding user"
  groupadd -g "${DOCKER_GID}" cnc_docker
  groupadd cnc_user cnc_docker
fi