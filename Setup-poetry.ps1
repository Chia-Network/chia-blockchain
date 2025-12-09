param(
    [Parameter(Mandatory, HelpMessage="Python version")]
    [string]
    $pythonVersion
)

$ErrorActionPreference = "Stop"

if (-not (Get-Item -ErrorAction SilentlyContinue ".penv/Scripts/").Exists)
{
    py -$pythonVersion -m venv .penv
    .penv/Scripts/python -m pip install --upgrade pip
}
# TODO: maybe make our own zipapp/shiv/pex of poetry and download that?
.penv/Scripts/python -m pip install --upgrade --requirement requirements-poetry.txt
