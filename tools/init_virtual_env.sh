#!/bin/bash

VIRTUAL_PATH=$1

if [[ ! -d $VIRTUAL_PATH ]];
then
    echo "Directory does not exist"
    exit 1
fi

cd "${VIRTUAL_PATH}"

if [[ $? -ne 0 ]];
then
    echo "Could not change directory"
    exit 1
fi

python3 -m virtualenv ./.venv

if [[ $? -ne 0 ]];
then
    echo "Could not create virtualenv"
    exit 1
fi


if [[ ! -f requirements.txt ]];
then
    touch .python3_init_done
    exit 0
fi

source ./.venv/bin/activate
if [[ $? -ne 0 ]];
then
    echo "Could not activate virtualenv"
    exit 1
fi

pip3 install -r requirements.txt

if [[ $? -ne 0 ]];
then
    echo "Could not install requirements"
    exit 1
fi

touch .python3_init_done

echo "Environment Created Successfully"

exit 0
