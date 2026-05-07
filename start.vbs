Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pythonPaths = Array( _
    "D:\conda\python.exe", _
    "C:\Users\" & CreateObject("WScript.Network").UserName & "\anaconda3\python.exe", _
    "C:\Users\" & CreateObject("WScript.Network").UserName & "\miniconda3\python.exe", _
    "python.exe" _
)

pythonExe = ""
For Each path In pythonPaths
    If fso.FileExists(path) Then
        pythonExe = path
        Exit For
    End If
Next

If pythonExe = "" Then
    MsgBox "Python not found! Please run in Anaconda Prompt.", vbCritical, "Error"
    WScript.Quit 1
End If

cmd = """" & pythonExe & """ start.py"
WshShell.Run cmd, 1, True
