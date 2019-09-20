#!/bin/sh

VIRTUAL_PATH=$1

if [ ! -d "$VIRTUAL_PATH" ];
then
    echo "Directory does not exist"
    exit 1
fi

cd "${VIRTUAL_PATH}" || (echo "Could not change directory" && exit 1)

if [ -f .python3_init_done ] && [ -d .venv ];
then
    # Issue #94 - always update the requirements
    echo "Environment already set up - Checking for updates"
    ./.venv/bin/pip3 install --upgrade -r requirements.txt || (echo "Could not update virtualenv!"; exit 1)
    exit 0
fi

# Issue #95 - use system-site-packages by default
python3 -m virtualenv  --system-site-packages ./.venv || (echo "Could not create virtualenv!"; exit 1)

if [ ! -f requirements.txt ];
then
    touch .python3_init_done
    exit 0
fi

echo "Installing requirements"
./.venv/bin/pip3 install -r requirements.txt || (echo "Could not install requirements!"; exit 1)

touch .python3_init_done

echo "Environment Created Successfully"

exit 0
