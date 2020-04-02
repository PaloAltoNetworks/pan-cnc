#!/usr/bin/env sh
# Simple wrapper script

# First run this script to ensure docker permissions are docker if necessary
/app/cnc/tools/create_docker_group.sh

# next run our app as the cnc_user
su cnc_user /app/cnc/tools/start_app.sh