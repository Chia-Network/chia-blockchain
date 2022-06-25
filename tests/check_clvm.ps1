$script_directory = Split-Path $MyInvocation.MyCommand.Path -Parent

"$script_directory/../venv/Scripts/python" "$script_directory/check_clvm.py"
exit $LASTEXITCODE
