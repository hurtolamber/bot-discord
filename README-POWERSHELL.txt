
POWERSHELL QUICK START (Windows)

1) Open PowerShell:
   - Press Win, type "PowerShell", open it.

2) Navigate to the folder where you saved these files, e.g. Downloads:
   cd "C:\Users\%USERNAME%\Downloads\discord_5v5_bot"

3) Allow script activation once (required for venv activation script):
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

4) Run setup (creates venv, installs, opens .env for your token):
   .\setup.ps1

5) Start the bot:
   .\start.ps1
   (or double-click start.bat if PS1 is blocked).
