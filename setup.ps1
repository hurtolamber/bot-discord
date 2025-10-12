
# Setup script for the Valorant 5v5 Discord bot
# Run in PowerShell by right‑clicking > Run with PowerShell (after unblocking scripts if needed).
Set-StrictMode -Version Latest
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# Create venv
python -m venv .venv

# Activate (requires RemoteSigned policy once)
. .\.venv\Scripts\Activate.ps1

# Install deps
pip install --upgrade pip
pip install -r requirements.txt

# Create .env if missing
if (-not (Test-Path ".env")) {
    Copy-Item ".env.template" ".env"
    Write-Host "Opening .env — paste your DISCORD_BOT_TOKEN then save and close Notepad."
    notepad ".env"
}

Write-Host "`nSetup done.`nTo start the bot next time:" -ForegroundColor Green
Write-Host ".\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "python bot.py" -ForegroundColor Yellow
