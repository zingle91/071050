# scripts/Invoke-MessengerApi.ps1
# UTF-8-safe helpers for Messenger API calls from Windows PowerShell 5.x.
#
# Why not bare Invoke-RestMethod?
# - PS 5.x -Body [byte[]] re-encodes with the ANSI code page (corrupts Korean POST).
# - PS 5.x response decoding often uses the wrong charset (corrupts Korean GET).
# This helper always writes/reads raw UTF-8 via HttpWebRequest + StreamReader(UTF8).
#
# Usage:
#   . .\scripts\Invoke-MessengerApi.ps1
#   $tok = Connect-Messenger -EmployeeId 'F00001' -Password '1q2w3e1!'
#   $msg = Send-MessengerMessage -RoomId 15 -Content '한글 테스트' -Token $tok
#   $got = Get-MessengerMessages -RoomId 15 -Token $tok

Set-StrictMode -Version Latest

function Set-MessengerUtf8 {
    <#
    .SYNOPSIS
      Set console / pipeline encoding to UTF-8 (code page 65001).
    #>
    [CmdletBinding()]
    param()
    try { chcp 65001 | Out-Null } catch { }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    try {
        [Console]::InputEncoding  = $utf8
        [Console]::OutputEncoding = $utf8
    } catch { }
    $script:OutputEncoding = $utf8
    $global:OutputEncoding = $utf8
}

function ConvertTo-Utf8JsonBytes {
    <#
    .SYNOPSIS
      Serialize an object (or raw JSON string) to UTF-8 bytes without BOM.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [object]$InputObject,
        [int]$Depth = 10
    )
    if ($InputObject -is [string]) {
        $json = $InputObject
    } else {
        $json = ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress
    }
    # unary comma keeps [byte[]] intact (PowerShell unwraps arrays on return)
    return , [System.Text.Encoding]::UTF8.GetBytes($json)
}

function Invoke-MessengerApi {
    <#
    .SYNOPSIS
      Call Messenger REST endpoints with UTF-8 request/response (Korean-safe on PS 5.x).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Get', 'Post', 'Put', 'Patch', 'Delete')]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Path,

        [object]$Body = $null,
        [string]$Token = $null,
        [string]$BaseUrl = 'http://127.0.0.1:8000',
        [hashtable]$Headers = $null,
        [string]$IdempotencyKey = $null
    )

    Set-MessengerUtf8

    if ($Path -match '^https?://') {
        $uri = $Path
    } else {
        $uri = ($BaseUrl.TrimEnd('/') + '/' + $Path.TrimStart('/'))
    }

    $hdr = @{}
    if ($null -ne $Headers) {
        foreach ($k in $Headers.Keys) { $hdr[$k] = $Headers[$k] }
    }
    if ($Token) {
        $hdr['Authorization'] = ('Bearer ' + $Token)
    }
    if ($IdempotencyKey) {
        $hdr['Idempotency-Key'] = $IdempotencyKey
    }

    $req = [System.Net.HttpWebRequest]::Create($uri)
    $req.Method = $Method.ToUpperInvariant()
    $req.Accept = 'application/json'
    $req.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
    # Prefer UTF-8 JSON from server
    $req.Headers['Accept-Charset'] = 'utf-8'
    foreach ($k in $hdr.Keys) {
        $req.Headers[$k] = [string]$hdr[$k]
    }

    if ($null -ne $Body) {
        $bytes = ConvertTo-Utf8JsonBytes -InputObject $Body
        $req.ContentType = 'application/json; charset=utf-8'
        $req.ContentLength = $bytes.Length
        $rs = $req.GetRequestStream()
        try {
            $rs.Write($bytes, 0, $bytes.Length)
        } finally {
            $rs.Close()
        }
    } else {
        $req.ContentLength = 0
    }

    try {
        $resp = $req.GetResponse()
    } catch [System.Net.WebException] {
        if ($null -eq $_.Exception.Response) { throw }
        $resp = $_.Exception.Response
    }

    try {
        $status = [int]$resp.StatusCode
        $stream = $resp.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        try {
            $text = $reader.ReadToEnd()
        } finally {
            $reader.Close()
        }
    } finally {
        $resp.Close()
    }

    if ($status -ge 400) {
        throw (New-Object System.Net.WebException("HTTP $status for $Method $uri :: $text"))
    }
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    return ($text | ConvertFrom-Json)
}

function Connect-Messenger {
    <#
    .SYNOPSIS
      POST /api/auth/login/json and return access_token (optionally save to file).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$EmployeeId,
        [Parameter(Mandatory = $true)][string]$Password,
        [string]$BaseUrl = 'http://127.0.0.1:8000',
        [string]$TokenPath = $null
    )
    $resp = Invoke-MessengerApi -Method Post -Path '/api/auth/login/json' -BaseUrl $BaseUrl -Body @{
        employee_id = $EmployeeId
        password    = $Password
    }
    $token = [string]$resp.access_token
    if ($TokenPath) {
        Set-Content -Path $TokenPath -Value $token -Encoding ascii
    }
    return $token
}

function Send-MessengerMessage {
    <#
    .SYNOPSIS
      POST /api/rooms/{id}/messages with UTF-8 content (Korean-safe).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$RoomId,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Token,
        [string]$BaseUrl = 'http://127.0.0.1:8000',
        [string]$ClientMessageId = $null
    )
    $body = @{ content = $Content }
    if ($ClientMessageId) {
        $body['client_message_id'] = $ClientMessageId
    }
    return Invoke-MessengerApi -Method Post -Path ("/api/rooms/$RoomId/messages") -Token $Token -BaseUrl $BaseUrl -Body $body -IdempotencyKey $ClientMessageId
}

function Get-MessengerMessages {
    <#
    .SYNOPSIS
      GET /api/rooms/{id}/messages (UTF-8 response decode).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$RoomId,
        [Parameter(Mandatory = $true)][string]$Token,
        [string]$BaseUrl = 'http://127.0.0.1:8000'
    )
    return Invoke-MessengerApi -Method Get -Path ("/api/rooms/$RoomId/messages") -Token $Token -BaseUrl $BaseUrl
}

function Send-MessengerNote {
    <#
    .SYNOPSIS
      POST /api/notes with UTF-8 subject/content (Korean-safe).
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int[]]$RecipientIds,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Token,
        [string]$Subject = '',
        [string]$BaseUrl = 'http://127.0.0.1:8000'
    )
    $body = @{
        recipient_ids = @($RecipientIds)
        subject       = $Subject
        content       = $Content
    }
    return Invoke-MessengerApi -Method Post -Path '/api/notes' -Token $Token -BaseUrl $BaseUrl -Body $body
}

# Initialize UTF-8 when this script is dot-sourced
Set-MessengerUtf8