# Gera um .tgz sem .git / venv / __pycache__ para enviar à VPS (menos ficheiros que scp -r na pasta inteira).
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$Out = Join-Path (Split-Path $RepoRoot) "deriv-ai-bot-deploy.tgz"
tar.exe -czvf $Out `
  --exclude=".git" `
  --exclude="venv" `
  --exclude=".venv" `
  --exclude="__pycache__" `
  --exclude="*.pyc" `
  --exclude="node_modules" `
  --exclude="web/node_modules" `
  --exclude="web/dist" `
  --exclude="data" `
  --exclude=".env" `
  .
Write-Host "Criado: $Out"
Write-Host "Enviar: scp `"$Out`" root@SEU_IP:/root/"
