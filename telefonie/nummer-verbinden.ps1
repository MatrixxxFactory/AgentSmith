# Verbindet eine Telefonnummer eines SIP-Anbieters (sipgate, Telnyx, Twilio, …) mit LiveKit.
#
# Vorher beim Anbieter: Nummer buchen und eingehende Anrufe an die SIP-URI deines
# LiveKit-Projekts schicken (LiveKit Cloud → Settings → Project → "SIP URI").
#
# Aufruf (im Projektordner):
#   powershell -ExecutionPolicy Bypass -File telefonie\nummer-verbinden.ps1 -Nummer +4930123456
# Mit Zugangsdaten, falls der Anbieter sich per Benutzer/Passwort anmeldet:
#   ... -Nummer +4930123456 -Benutzer meinbenutzer -Passwort geheim
#
# Danach die Nummer in "telefonnummern:" des passenden Profils eintragen.
# Die Weiterleitungsregel (telefonie\dispatch-regel.json) gilt für alle Trunks und ist
# bereits angelegt; prüfen mit: lk sip dispatch list

param(
    [Parameter(Mandatory = $true)][string]$Nummer,
    [string]$Name = "Agent Smith $Nummer",
    [string]$Benutzer = "",
    [string]$Passwort = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($Nummer -notmatch '^\+[1-9]\d{6,14}$') {
    Write-Host "Die Nummer muss im internationalen Format sein, z. B. +4930123456" -ForegroundColor Red
    exit 1
}

$argumente = @('sip', 'inbound', 'create', '--name', $Name, '--numbers', $Nummer)
if ($Benutzer) { $argumente += @('--auth-user', $Benutzer, '--auth-pass', $Passwort) }

& lk @argumente
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Verbunden. Aktuelle Trunks und Regeln:" -ForegroundColor Green
& lk sip inbound list
& lk sip dispatch list
