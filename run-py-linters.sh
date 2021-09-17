#!/bin/bash

python3 -m venv venv
# shellcheck disable=SC1091
. ./activate
pip3 install ".[dev]"


# used to set the overall script's exit code at the end
PASSED=true

SECTION=mypy
echo
echo ---- ${SECTION}
venv/bin/mypy --config-file mypy.ini chia tests;
if [ $? == 0 ]; then
    echo ---- ${SECTION} passed
else
    echo ---- ${SECTION} FAILED
    PASSED=false
fi

SECTION=flake8
echo
echo ---- ${SECTION}
venv/bin/flake8 --config .github/linters/.flake8 chia tests
if [ $? == 0 ]; then
    echo ---- ${SECTION} passed
else
    echo ---- ${SECTION} FAILED
    PASSED=false
fi

SECTION=black
echo
echo ---- ${SECTION}
venv/bin/black --config .github/linters/.python-black --check --diff chia tests
if [ $? == 0 ]; then
    echo ---- ${SECTION} passed
else
    echo ---- ${SECTION} FAILED
    PASSED=false
fi

SECTION=pylint
echo
echo ---- ${SECTION}
venv/bin/pylint --rcfile .github/linters/.python-lint chia tests
if [ $? == 0 ]; then
    echo ---- ${SECTION} passed
else
    echo ---- ${SECTION} FAILED
    PASSED=false
fi

echo
if [ ${PASSED} == "true" ]; then
    echo ----  All checks passed
else
    echo ----  Some checks FAILED
fi

# set the overal scripts exit code
${PASSED}
