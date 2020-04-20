Remove-Item "./venv" -Recurse -Force -ErrorAction Ignore

Start-Process "$env:HOMEDRIVE$env:HOMEPATH\AppData\Local\Programs\Python\Python37\python.exe" -ArgumentList "-m venv venv" -Wait

. .\venv\Scripts\activate.ps1

pip3 install --user --upgrade pip

.\wheels.ps1
