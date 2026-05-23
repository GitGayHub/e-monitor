# Switch GitHub account + push project to new repo
# Run from D:\eSearch as normal user:
#   powershell -ExecutionPolicy Bypass -File .\setup_new_account.ps1

$REPO_NAME = "ebay-monitor"
function S($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }

S "1/8  Check tools"
foreach ($cmd in @("git","gh")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "Not found: $cmd. Install Git and GitHub CLI first." -ForegroundColor Red; exit 1
    }
}
Write-Host "  git and gh found."

S "2/8  gh auth logout all accounts"
$ghOut = gh auth status 2>&1 | Out-String
$accounts = [regex]::Matches($ghOut, "account (\S+)") | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
if ($accounts) {
    foreach ($u in $accounts) {
        Write-Host "  logout $u"
        "y" | gh auth logout -h github.com -u $u 2>&1 | Out-Null
    }
} else { Write-Host "  No accounts, skipping." }

S "3/8  Clear Windows Credential Manager (git/github)"
$credList = cmdkey /list | Out-String
$targets = [regex]::Matches($credList, "(?:Ziel|Target):\s*(\S+)") |
    ForEach-Object { $_.Groups[1].Value } |
    Where-Object { $_ -match "git:|github" }
if ($targets) {
    foreach ($t in $targets) { Write-Host "  delete $t"; cmdkey /delete:$t | Out-Null }
} else { Write-Host "  Nothing to clear." }

S "4/8  Clean remote URL"
$r = git remote get-url origin 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  was : $r"
    $clean = "$r" -replace "https://[^/@]+@github\.com/","https://github.com/"
    if ($clean -ne "$r") { git remote set-url origin $clean }
    Write-Host "  now : $(git remote get-url origin)"
} else { Write-Host "  No remote set." }

S "5/8  gh auth login (browser will open - log into new account)"
gh auth login -h github.com -p https -w
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gh auth login failed" -ForegroundColor Red; exit 1 }

S "6/8  Read new account profile"
$user  = (gh api user --jq ".login" 2>&1).Trim()
$name  = (gh api user --jq "(.name // .login)" 2>&1).Trim()
$email = (gh api user --jq "(.email // empty)" 2>&1).Trim()
if (-not $email -or $email -eq "null") { $email = "$user@users.noreply.github.com" }
Write-Host "  user : $user";  Write-Host "  name : $name";  Write-Host "  email: $email"

S "7/8  git config --global"
git config --global user.name  $name
git config --global user.email $email
git config --global credential.helper manager
Write-Host "  user.name : $(git config --global user.name)"
Write-Host "  user.email: $(git config --global user.email)"

S "8/8  Create / push repo $user/$REPO_NAME"
$repoFull = "$user/$REPO_NAME"
gh repo view $repoFull 1>$null 2>$null
$repoExists = ($LASTEXITCODE -eq 0)

if (-not $repoExists) {
    Write-Host "  Creating private repo $repoFull ..."
    git add -A
    $diff = git diff --cached --name-only
    if ($diff) { git commit -m "Initial push to new account ($user)" }
    git remote remove origin 2>&1 | Out-Null
    gh repo create $repoFull --private --source=. --remote=origin --push
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gh repo create failed" -ForegroundColor Red; exit 1 }
} else {
    Write-Host "  Repo exists, switching origin and pushing ..."
    git remote get-url origin 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        git remote set-url origin "https://github.com/$repoFull.git"
    } else {
        git remote add origin "https://github.com/$repoFull.git"
    }
    git add -A
    $diff = git diff --cached --name-only
    if ($diff) { git commit -m "Push to new account ($user)" }
    git push -u origin HEAD:main
}

S "9/9  Actions secrets"
function Get-Val($env, $prompt) {
    $v = [Environment]::GetEnvironmentVariable($env, "User")
    if (-not $v) { $v = [Environment]::GetEnvironmentVariable($env, "Process") }
    if (-not $v) { $v = Read-Host "  $prompt"; if ($v) { [Environment]::SetEnvironmentVariable($env, $v, "User") } }
    return $v
}
$tok  = Get-Val "TELEGRAM_BOT_TOKEN" "Paste TELEGRAM_BOT_TOKEN"
$chat = Get-Val "TELEGRAM_CHAT_ID"   "Paste TELEGRAM_CHAT_ID"
$ebayClientId = Get-Val "EBAY_CLIENT_ID" "Paste EBAY_CLIENT_ID (optional)"
$ebayClientSecret = Get-Val "EBAY_CLIENT_SECRET" "Paste EBAY_CLIENT_SECRET (optional)"
if ($tok)  { $tok  | gh secret set TELEGRAM_BOT_TOKEN --repo $repoFull; Write-Host "  TELEGRAM_BOT_TOKEN set" }
if ($chat) { $chat | gh secret set TELEGRAM_CHAT_ID   --repo $repoFull; Write-Host "  TELEGRAM_CHAT_ID set" }
if ($ebayClientId) { $ebayClientId | gh secret set EBAY_CLIENT_ID --repo $repoFull; Write-Host "  EBAY_CLIENT_ID set" }
if ($ebayClientSecret) { $ebayClientSecret | gh secret set EBAY_CLIENT_SECRET --repo $repoFull; Write-Host "  EBAY_CLIENT_SECRET set" }

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "Repo   : https://github.com/$repoFull"
Write-Host "Actions: https://github.com/$repoFull/actions"
Write-Host "Trigger first run: gh workflow run ebay-monitor.yml --repo $repoFull"
