' Double-click to open the app: starts the server in the background (no black window)
' and opens the page in its own window. Run run_local.bat once first to install everything.
Option Explicit
Dim TITLE: TITLE = ChrW(&H67E5) & ChrW(&H5F97) & ChrW(&H5230) & ChrW(&HFF0C) & ChrW(&H4FE1) & ChrW(&H5F97) & ChrW(&H8FC7)
Dim sh, fso, dir, port, url, i
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
port = "8011"
If WScript.Arguments.Count > 0 Then port = WScript.Arguments(0)
url = "http://localhost:" & port

If Not fso.FileExists(dir & "\frontend\dist\index.html") Or Not fso.FileExists(dir & "\.env") Then
  MsgBox "First time? Please run run_local.bat once to install everything, then use this again.", 48, TITLE
  WScript.Quit
End If

If Not IsUp() Then
  sh.CurrentDirectory = dir
  ' plain "python" can be the Microsoft Store stub, so prefer the py launcher
  Dim py: py = "python"
  If sh.Run("cmd /c where py", 0, True) = 0 Then py = "py -3"
  sh.Run "cmd /c " & py & " -m uvicorn backend.main:app --port " & port & " > server_" & port & ".log 2>&1", 0, False
  For i = 1 To 60
    WScript.Sleep 500
    If IsUp() Then Exit For
  Next
  If Not IsUp() Then
    MsgBox "The server did not start. Open server_" & port & ".log in this folder and send it to Claude.", 16, TITLE
    WScript.Quit
  End If
End If

On Error Resume Next
sh.Run "msedge --app=" & url, 1, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run url, 1, False
End If

Function IsUp()
  Dim http
  IsUp = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP")
  http.setTimeouts 1000, 1000, 1000, 1000
  http.Open "GET", url & "/api/health", False
  http.Send
  If Err.Number = 0 Then IsUp = (http.Status = 200)
End Function
