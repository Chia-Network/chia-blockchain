To complete the install:

First open a PowerShell run as Administrator and run:
    Set-ExecutionPolicy Unrestricted

Close the Administrator PowerShell and open a normal PowerShell session.

Change directory to "~\AppData\Local\Programs\Chia Network\Chia Blockchain\".
    cd "~\AppData\Local\Programs\Chia Network\Chia Blockchain\"

Run the install.ps1 script located in that folder.
    .\install.ps1

Generally you then run:
    chia init
    chia generate keys

You can start a node or a farmer as follows:
    Start-Job -Name chia-node -ScriptBlock { chia start node }
or
    Start-Job -Name chia-farmer -ScriptBlock { chia start farmer }

To watch the logs try:
    Get-Content ~\.\.chia\beta-1.0b4.dev62\log\debug.log -Wait

To create one k=26 proof of space plots:
    chia-create-plots -k 26 -n 1

For more usage information try:
The chia-blockchain README.md - https://github.com/Chia-Network/chia-blockchain/blob/master/README.md
The chia-blockchain repo wiki - https://github.com/Chia-Network/chia-blockchain/wiki
