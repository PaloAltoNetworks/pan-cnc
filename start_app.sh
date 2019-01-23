#!/usr/bin/env sh

cd /app/cnc
celery -A pan_cnc worker --loglevel=info &
python3 /app/cnc/manage.py runserver 0.0.0.0:80
