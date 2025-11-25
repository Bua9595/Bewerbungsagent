@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "C:\Users\F. Bujupi\Desktop\Lager\Projekte\Bewerbungsagent"
echo ==== START %DATE% %TIME% ====>> "C:\Users\F. Bujupi\Desktop\Lager\Projekte\Bewerbungsagent\logs\mail-list.log"
"C:\Users\F. Bujupi\Desktop\Lager\Projekte\Bewerbungsagent\.venv\Scripts\python.exe" tasks.py mail-list >> "C:\Users\F. Bujupi\Desktop\Lager\Projekte\Bewerbungsagent\logs\mail-list.log" 2>&1
echo ==== END %DATE% %TIME% (exit %ERRORLEVEL%) ====>> "C:\Users\F. Bujupi\Desktop\Lager\Projekte\Bewerbungsagent\logs\mail-list.log"
exit /b %ERRORLEVEL%
