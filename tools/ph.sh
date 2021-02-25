#!/usr/bin/env sh
# Simple wrapper script

# First run this script to ensure docker permissions are docker if necessary
/app/cnc/tools/create_docker_group.sh

# setup global git configuration
/app/cnc/tools/ensure_gitignore_config.sh

echo "Fixing up permissions"
chown -R cnc_user:cnc_group /home/cnc_user/.pan_cnc/
chgrp -R cnc_group /home/cnc_user/.pan_cnc/

APP_DIR=$(echo "$CNC_APP" | tr '[:upper:]' '[:lower:]')

python3 /app/cnc/tools/remove_dangling_dirs.py "/home/cnc_user/.pan_cnc/${APP_DIR}/repositories"

# next run our app as the cnc_user
su cnc_user /app/cnc/tools/start_app.sh
