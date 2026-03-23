"""Generate the NSIS installer script for Windows."""
from pathlib import Path

ROOT = Path(__file__).parent.parent
script = ROOT / "build" / "aeglos_installer.nsi"

nsi = """
!define APPNAME "AEGLOS Analytics Pro"
!define VERSION "1.0.0"
!define PUBLISHER "AEGLOS Analytics"
!define APPDIR "$INSTDIR\\AEGLOS Analytics Pro"
!define UNINSTALL_KEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\$(^Name)"

Name "${APPNAME} ${VERSION}"
OutFile "..\\dist\\AEGLOS-Analytics-Pro-${VERSION}-Windows-x64.exe"
InstallDir "$PROGRAMFILES64\\AEGLOS Analytics Pro"
RequestExecutionLevel admin
SetCompressor lzma

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "..\\dist_app\\AEGLOS Analytics Pro\\*"

  ; Start menu shortcut
  CreateDirectory "$SMPROGRAMS\\AEGLOS Analytics Pro"
  CreateShortCut "$SMPROGRAMS\\AEGLOS Analytics Pro\\AEGLOS Analytics Pro.lnk" \\
    "$INSTDIR\\AEGLOS Analytics Pro.exe"
  CreateShortCut "$DESKTOP\\AEGLOS Analytics Pro.lnk" \\
    "$INSTDIR\\AEGLOS Analytics Pro.exe"

  ; Uninstaller
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\\Uninstall.exe"
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\\AEGLOS Analytics Pro\\AEGLOS Analytics Pro.lnk"
  RMDir "$SMPROGRAMS\\AEGLOS Analytics Pro"
  Delete "$DESKTOP\\AEGLOS Analytics Pro.lnk"
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
SectionEnd
"""

script.write_text(nsi)
print(f"Written: {script}")
