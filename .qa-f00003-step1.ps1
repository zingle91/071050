# QA bootstrap for F00003 — uses UTF-8 Messenger API helper (Korean-safe).
# Dot-sources scripts/Invoke-MessengerApi.ps1 so login/GETs share the same encoding path.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Root) { $Root = (Get-Location).Path }
. (Join-Path $Root 'scripts\Invoke-MessengerApi.ps1')

$TokenFile = Join-Path $Root '.qa-f00003-token.txt'
$RoomIdFile = Join-Path $Root '.qa-scenario-room-id.txt'
$BaseUrl = 'http://127.0.0.1:8000'

$token = $null
if (Test-Path $TokenFile) {
    $token = (Get-Content $TokenFile -Raw -Encoding ascii).Trim()
}

$needLogin = $true
if ($token) {
    try {
        $me = Invoke-MessengerApi -Method Get -Path '/api/auth/me' -Token $token -BaseUrl $BaseUrl
        Write-Output ('ME_OK: ' + ($me | ConvertTo-Json -Compress -Depth 5))
        $needLogin = $false
    } catch {
        Write-Output ('TOKEN_INVALID: ' + $_.Exception.Message)
    }
}

if ($needLogin) {
    $token = Connect-Messenger -EmployeeId 'F00003' -Password '1q2w3e1!' -BaseUrl $BaseUrl -TokenPath $TokenFile
    Write-Output ('LOGIN_OK token_len=' + $token.Length)
    $me = Invoke-MessengerApi -Method Get -Path '/api/auth/me' -Token $token -BaseUrl $BaseUrl
    Write-Output ('ME_OK: ' + ($me | ConvertTo-Json -Compress -Depth 5))
}

$rooms = Invoke-MessengerApi -Method Get -Path '/api/rooms' -Token $token -BaseUrl $BaseUrl
Write-Output ('ROOMS: ' + ($rooms | ConvertTo-Json -Compress -Depth 8))
if (Test-Path $RoomIdFile) {
    Write-Output ('SAVED_ROOM_ID: ' + (Get-Content $RoomIdFile -Raw -Encoding ascii).Trim())
}