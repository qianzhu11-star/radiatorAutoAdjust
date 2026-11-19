Option Explicit
Dim shell, fs, folder, pythonw, args, configFile, reader
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
configFile = folder & "\.pythonw-path"
If Not fs.FileExists(configFile) Then
  MsgBox "Run setup.ps1 first to select Python and install dependencies.", 16, "BS2 Pro"
  WScript.Quit 1
End If
Set reader = fs.OpenTextFile(configFile, 1, False, -1)
pythonw = Trim(reader.ReadLine)
reader.Close
If Not fs.FileExists(pythonw) Then
  MsgBox "Python not found. Run setup.ps1 with your installed Python.", 16, "BS2 Pro"
  WScript.Quit 1
End If
args = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & folder & "\main.py" & Chr(34)
shell.CurrentDirectory = folder
shell.Run args, 1, False
