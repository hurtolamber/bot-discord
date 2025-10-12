
# Start the Valorant 5v5 Discord bot
Set-StrictMode -Version Latest
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
. .\.venv\Scripts\Activate.ps1
python bot.py
