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

To watch the logs try this (your version - beta-1.0b4 here - may be different):
    Get-Content ~\.\.chia\beta-1.0b4\log\debug.log -Wait

To create one k=26 proof of space plots:
    chia-create-plots -k 26 -n 1

To use the Chia Wallet UI you will need to run:
     Start-Job -Name chia-wallet-server -ScriptBlock { chia start wallet-server }

And then click on the "Chia Wallet" icon on the Desktop or in the Start Menu.

To stop a service started with Start-Job, run 'Get-Job' and then 'Stop Job ID'
where ID is the listed job number.

After install, you can enter the venv in the "Chia Blockchain" directory with:
    .\venv\Scrips\Activate.ps1

For more usage information try:
Quick Start Guide - https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide
Repository wiki - https://github.com/Chia-Network/chia-blockchain/wiki

For assistance join us on Keybase in the #testnet chat channel
    https://keybase.io/team/chia_network.public
