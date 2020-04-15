.\clean.ps1

.\make-wallet-msi.ps1
if ($LastExitCode) { exit $LastExitCode }

.\make-bundle.ps1
if ($LastExitCode) { exit $LastExitCode }