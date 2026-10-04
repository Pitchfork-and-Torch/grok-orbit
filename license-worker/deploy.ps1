# Deploy Grok Orbit license worker. Never print secret values.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

function Read-SecretFile([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-Content -LiteralPath $Path -Raw).Trim()
}

function Put-Secret([string]$Name, [string]$Value) {
  if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
  $tmp = Join-Path $env:TEMP ("orbit-sec-" + [guid]::NewGuid().ToString("N") + ".txt")
  $utf8 = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($tmp, $Value, $utf8)
  try {
    cmd /c "type `"$tmp`" | npx --yes wrangler secret put $Name --name grok-orbit-license"
    if ($LASTEXITCODE -ne 0) { throw "wrangler secret put $Name failed" }
  } finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
  return $true
}

if (-not (Test-Path "node_modules\wrangler")) {
  npm install --no-fund --no-audit
}

Write-Host "[orbit] creating KV if needed"
$kvOut = npx --yes wrangler kv namespace list 2>&1 | Out-String
if ($kvOut -notmatch "grok-orbit-licenses") {
  npx --yes wrangler kv namespace create "KV" --preview false
}

# If wrangler wrote an id, keep it in wrangler.jsonc only after we parse it.
$listJson = npx --yes wrangler kv namespace list
$ns = $listJson | ConvertFrom-Json | Where-Object { $_.title -match "grok-orbit-licenses|grok-orbit-license-KV" } | Select-Object -First 1
if (-not $ns) {
  $ns = $listJson | ConvertFrom-Json | Where-Object { $_.title -match "KV" -and $_.title -match "grok-orbit" } | Select-Object -First 1
}
if ($ns -and $ns.id) {
  $confPath = Join-Path $here "wrangler.jsonc"
  $conf = Get-Content -LiteralPath $confPath -Raw
  if ($conf -notmatch $ns.id) {
    $block = @"
  ,
  "kv_namespaces": [
    { "binding": "KV", "id": "$($ns.id)" }
  ]
}
"@
    $conf = $conf.TrimEnd()
    if ($conf.EndsWith("}")) {
      $conf = $conf.Substring(0, $conf.Length - 1).TrimEnd() + $block
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($confPath, $conf, $utf8)
    Write-Host "[orbit] wrote KV id to wrangler.jsonc"
  }
}

$stripe = Read-SecretFile "$env:USERPROFILE\.grok\secrets\stripe_api_key.txt"
if (-not $stripe) { $stripe = Read-SecretFile "$env:USERPROFILE\.grok\secrets\grokforge-stripe-secret-key.txt" }
$email = Read-SecretFile "$env:USERPROFILE\.grok\agent-email.env"
if ($email -match "AGENT_EMAIL_TOKEN\s*=\s*(\S+)") { $email = $Matches[1] }
if (-not $email) {
  $ej = Get-Content "$env:USERPROFILE\.grok\agent-email.json" -Raw -ErrorAction SilentlyContinue
  if ($ej) {
    $obj = $ej | ConvertFrom-Json
    if ($obj.secretsFile) { $email = Read-SecretFile ([string]$obj.secretsFile) }
  }
}

Write-Host "[orbit] putting secrets (values not printed)"
[void](Put-Secret "STRIPE_SECRET_KEY" $stripe)
[void](Put-Secret "EMAIL_TOKEN" $email)
$pepper = [guid]::NewGuid().ToString("N")
[void](Put-Secret "LICENSE_PEPPER" $pepper)

Write-Host "[orbit] deploy"
npx --yes wrangler deploy
if ($LASTEXITCODE -ne 0) { throw "wrangler deploy failed" }
Write-Host "[orbit] health"
curl.exe -sS "https://grok-orbit-license.pitchfork-and-torch.workers.dev/health"
Write-Host ""
