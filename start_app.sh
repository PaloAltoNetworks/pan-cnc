#!/usr/bin/env sh

export HOME=/home/cnc_user

cd /app/cnc
su -c "celery -A pan_cnc worker --loglevel=info " -s /bin/sh cnc_user &
if [[ ! -f /app/cnc/db.sqlite3 ]];
  then
    su -c "python /app/cnc/manage.py migrate" -s /bin/sh cnc_user && \
    su -c "python /app/cnc/manage.py collectstatic --noinput" -s /bin/sh cnc_user && \
    su -c "python /app/cnc/manage.py shell -c \"from django.contrib.auth.models import User; User.objects.create_superuser('${CNC_USERNAME}', 'admin@example.com', '${CNC_PASSWORD}')\"" -s /bin/sh cnc_user \
    || exit 1
fi
echo "====="
echo "====="
echo "====="
echo "=================== Welcome to panhandler ============================"
echo "====="
echo "====="
echo "====="
gunicorn --user cnc_user --group cnc_group --env HOME=/home/cnc_user --bind 0.0.0.0:80 pan_cnc.wsgi
