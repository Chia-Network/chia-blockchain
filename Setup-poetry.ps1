param(
    [Parameter(Mandatory, HelpMessage="Python version")]
    [string]
    $pythonVersion
)

$ErrorActionPreference = "Stop"

py -$pythonVersion -m venv .penv
.penv/Scripts/python -m pip install --upgrade pip setuptools wheel
# TODO: maybe make our own zipapp/shiv/pex of poetry and download that?
.penv/Scripts/python -m pip install poetry "poetry-dynamic-versioning[plugin]"
