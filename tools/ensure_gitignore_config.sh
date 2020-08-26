#!/bin/sh

GIT_CONFIG_PATH=/home/cnc_user/.config/git
GIT_CONFIG_FILE="${GIT_CONFIG_PATH}/ignore"

if [ ! -d "${GIT_CONFIG_PATH}" ];
then
    echo "Creating git global configuration"
    mkdir -p "${GIT_CONFIG_PATH}"
    chown cnc_user:cnc_group "${GIT_CONFIG_PATH}"
fi

if [ ! -f "${GIT_CONFIG_FILE}" ];
then
    cp /app/cnc/tools/.gitignore-cnc_user "${GIT_CONFIG_FILE}"
    chown cnc_user:cnc_group "${GIT_CONFIG_FILE}"
else
  if ! diff /app/cnc/tools/.gitignore-cnc_user "${GIT_CONFIG_FILE}" >>/dev/null 2>&1;
    then
      echo "Updating global git ignore configuration"
      cp /app/cnc/tools/.gitignore-cnc_user "${GIT_CONFIG_FILE}"
  fi
fi

exit 0;


