Remove-Item "./venv" -Recurse -Force -ErrorAction Ignore

Start-Process "$env:HOMEDRIVE$env:HOMEPATH\AppData\Local\Programs\Python\Python37\python.exe" -ArgumentList "-m venv venv" -Wait
if ($LastExitCode) { exit $LastExitCode }

. .\venv\Scripts\activate.ps1
pip3 install --upgrade pip
pip install -i https://download.chia.net/simple/ miniupnpc==2.1 setproctitle==1.1.10 cbor2==5.1.0
pip install -e .