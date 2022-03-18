!include "nsDialogs.nsh"

; Add our customizations to the finish page
!macro customFinishPage
XPStyle on

Var DetectDlg
Var FinishDlg
Var ChiaSquirrelInstallLocation
Var ChiaSquirrelInstallVersion
Var ChiaSquirrelUninstaller
Var CheckboxUninstall
Var UninstallChiaSquirrelInstall
Var BackButton
Var NextButton

Page custom detectOldChiaVersion detectOldChiaVersionPageLeave
Page custom finish finishLeave

; Add a page offering to uninstall an older build installed into the chia-blockchain dir
Function detectOldChiaVersion
  ; Check the registry for old chia-blockchain installer keys
  ReadRegStr $ChiaSquirrelInstallLocation HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\chia-blockchain" "InstallLocation"
  ReadRegStr $ChiaSquirrelInstallVersion HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\chia-blockchain" "DisplayVersion"
  ReadRegStr $ChiaSquirrelUninstaller HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\chia-blockchain" "QuietUninstallString"

  StrCpy $UninstallChiaSquirrelInstall ${BST_UNCHECKED} ; Initialize to unchecked so that a silent install skips uninstalling

  ; If registry keys aren't found, skip (Abort) this page and move forward
  ${If} ChiaSquirrelInstallVersion == error
  ${OrIf} ChiaSquirrelInstallLocation == error
  ${OrIf} $ChiaSquirrelUninstaller == error
  ${OrIf} $ChiaSquirrelInstallVersion == ""
  ${OrIf} $ChiaSquirrelInstallLocation == ""
  ${OrIf} $ChiaSquirrelUninstaller == ""
  ${OrIf} ${Silent}
    Abort
  ${EndIf}

  ; Check the uninstall checkbox by default
  StrCpy $UninstallChiaSquirrelInstall ${BST_CHECKED}

  ; Magic create dialog incantation
  nsDialogs::Create 1018
  Pop $DetectDlg

  ${If} $DetectDlg == error
    Abort
  ${EndIf}

  !insertmacro MUI_HEADER_TEXT "Uninstall Old Version" "Would you like to uninstall the old version of Chia Blockchain?"

  ${NSD_CreateLabel} 0 35 100% 12u "Found Chia Blockchain $ChiaSquirrelInstallVersion installed in an old location:"
  ${NSD_CreateLabel} 12 57 100% 12u "$ChiaSquirrelInstallLocation"

  ${NSD_CreateCheckBox} 12 81 100% 12u "Uninstall Chia Blockchain $ChiaSquirrelInstallVersion"
  Pop $CheckboxUninstall
  ${NSD_SetState} $CheckboxUninstall $UninstallChiaSquirrelInstall
  ${NSD_OnClick} $CheckboxUninstall SetUninstall

  nsDialogs::Show

FunctionEnd

Function SetUninstall
  ; Set UninstallChiaSquirrelInstall accordingly
  ${NSD_GetState} $CheckboxUninstall $UninstallChiaSquirrelInstall
FunctionEnd

Function detectOldChiaVersionPageLeave
  ${If} $UninstallChiaSquirrelInstall == 1
    ; This could be improved... Experiments with adding an indeterminate progress bar (PBM_SETMARQUEE)
    ; were unsatisfactory.
    ExecWait $ChiaSquirrelUninstaller ; Blocks until complete (doesn't take long though)
  ${EndIf}
FunctionEnd

Function finish

  ; Magic create dialog incantation
  nsDialogs::Create 1018
  Pop $FinishDlg

  ${If} $FinishDlg == error
    Abort
  ${EndIf}

  GetDlgItem $NextButton $HWNDPARENT 1 ; 1 = Next button
  GetDlgItem $BackButton $HWNDPARENT 3 ; 3 = Back button

  ${NSD_CreateLabel} 0 35 100% 12u "Chia has been installed successfully!"
  EnableWindow $BackButton 0 ; Disable the Back button
  SendMessage $NextButton ${WM_SETTEXT} 0 "STR:Let's Farm!" ; Button title is "Close" by default. Update it here.

  nsDialogs::Show

FunctionEnd

; Copied from electron-builder NSIS templates
Function StartApp
  ${if} ${isUpdated}
    StrCpy $1 "--updated"
  ${else}
    StrCpy $1 ""
  ${endif}
  ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" "$1"
FunctionEnd

Function finishLeave
  ; Launch the app at exit
  Call StartApp
FunctionEnd

; Section
; SectionEnd
!macroend
