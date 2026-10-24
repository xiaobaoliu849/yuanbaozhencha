' Double-click to stop the background server started by start_app.vbs.
Option Explicit
Dim TITLE: TITLE = ChrW(&H67E5) & ChrW(&H5F97) & ChrW(&H5230) & ChrW(&HFF0C) & ChrW(&H4FE1) & ChrW(&H5F97) & ChrW(&H8FC7)
Dim sh, port
Set sh = CreateObject("WScript.Shell")
port = "8000"
If WScript.Arguments.Count > 0 Then port = WScript.Arguments(0)
sh.Run "powershell -NoProfile -WindowStyle Hidden -Command ""Get-NetTCPConnection -LocalPort " & port & _
  " -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }""", 0, True
MsgBox "Stopped.", 64, TITLE
