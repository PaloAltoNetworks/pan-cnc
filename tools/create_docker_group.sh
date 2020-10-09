#!/bin/sh
#
# Simple tool to align docker.sock permissions with cnc_user user group
# the goal is to ensure cnc_user can access docker.sock
#
# 4-2-2020 nembery@paloaltonetworks.com
#
DOCKER_SOCKET=/var/run/docker.sock

# Check if the socket is mounted at all
if [ ! -S $DOCKER_SOCKET ]; then
  echo "Docker is unavailable"
  exit 0
fi

# fix for docker on mac version 19.03.13 see issue: https://gitlab.com/panw-gse/as/panhandler/-/issues/113
if ! stat -c %a $DOCKER_SOCKET | grep -q '.[67].'; then
  chmod g+w $DOCKER_SOCKET
fi

# Socket is mounted, get the group id using stat
DOCKER_GID=$(stat -c %g ${DOCKER_SOCKET})

# if we can't get the gid for some reason, then we need to bail out here
if [ -z "${DOCKER_GID}" ]; then
  echo "Could not determine Group ID for Docker socket"
  exit 0
fi

# group id 0 is already handled
if [ "${DOCKER_GID}" -eq "0" ]; then
  exit 0
fi

# attempt to find if a group already exists with this gid
DOCKER_GROUP=$(grep ":${DOCKER_GID}:" /etc/group | cut -f1 -d':')

# if there is an existing group, ensure our user is a part of it, otherwise add them
if [ "${DOCKER_GROUP}" != "" ]; then
  if ! groups cnc_user | grep -q "${DOCKER_GROUP}"; then
    echo "Adding user to existing group"
    addgroup cnc_user "${DOCKER_GROUP}"
  fi
else
  # create the group and add the user
  echo "Creating new group and adding user"
  addgroup --gid "${DOCKER_GID}" cnc_docker
  addgroup cnc_user cnc_docker
fi

# all done
exit 0
