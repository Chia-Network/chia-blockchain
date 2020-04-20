Remove-Item "./venv" -Recurse -Force -ErrorAction Ignore

Start-Process "$env:HOMEDRIVE$env:HOMEPATH\AppData\Local\Programs\Python\Python37\python.exe" -ArgumentList "-m venv venv" -Wait

. .\venv\Scripts\activate.ps1

python -m pip install --upgrade pip

pip install .\wheels\miniupnpc-2.1-cp37-cp37m-win_amd64.whl
pip install .\wheels\setproctitle-1.1.10-cp37-cp37m-win_amd64.whl
.\wheels.ps1
