#!/usr/bin/env sh

export HOME=/home/cnc_user

CNC_APP_LOWER=$(echo "$CNC_APP" | tr '[:upper:]' '[:lower:]')

cd /app/cnc || exit 1
celery -A pan_cnc worker --loglevel=info  &
if [ ! -f /app/cnc/db.sqlite3 ];
  then
    python /app/cnc/manage.py migrate && \
    python /app/cnc/manage.py shell -c \
    "from django.contrib.auth.models import User; User.objects.create_superuser('${CNC_USERNAME}','admin@example.com', '${CNC_PASSWORD}')" \
    || exit 1
fi

# if this CNC app supplies it's own DB, let's go ahead and make sure it's all set
if [ -d /app/src/"$CNC_APP_LOWER"/migrations ];
  then
    echo "Creating ${CNC_APP} database"
    python /app/cnc/manage.py migrate --database="$CNC_APP_LOWER" \
    || exit 1
fi

echo "====="
echo "====="
echo "====="
echo "=================== Welcome to ${CNC_APP} ============================"
echo "====="
echo "====="
echo "====="
python3 /app/cnc/manage.py runserver 0.0.0.0:8080
