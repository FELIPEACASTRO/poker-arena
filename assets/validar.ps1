# Complete local quality gate. Every step runs even if a previous one fails.
$ErrorActionPreference = 'Continue'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$distributionRoot = [IO.Path]::GetFullPath((Split-Path $projectRoot -Parent))
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$cmdExecutable = Join-Path ([Environment]::SystemDirectory) 'cmd.exe'
$failures = @()

function Resolve-PlainApplication([string]$Name) {
    $command = Get-Command $Name -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $item = Get-Item -LiteralPath $command.Source -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Executavel recusado por nao ser arquivo regular: $Name"
    }
    return [IO.Path]::GetFullPath($item.FullName)
}

$npmExecutable = Resolve-PlainApplication 'npm.cmd'
$nodeExecutable = Resolve-PlainApplication 'node.exe'
$uvExecutable = Resolve-PlainApplication 'uv.exe'
$gitExecutable = Resolve-PlainApplication 'git.exe'
$safePathDirectories = @(
    (Split-Path $npmExecutable -Parent),
    (Split-Path $nodeExecutable -Parent),
    (Split-Path $uvExecutable -Parent),
    (Split-Path $gitExecutable -Parent),
    (Split-Path $python -Parent),
    ([Environment]::SystemDirectory),
    (Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0')
) | Sort-Object -Unique
$safePath = $safePathDirectories -join [IO.Path]::PathSeparator
$npmCommand = "`"$npmExecutable`""
$uvCommand = "`"$uvExecutable`""

function Stop-ProcessTree([Diagnostics.Process]$Target) {
    if ($Target.HasExited) {
        return
    }
    $taskkill = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
    & $taskkill /PID $Target.Id /T /F | Out-Null
    if (-not $Target.WaitForExit(10000)) {
        Stop-Process -Id $Target.Id -Force -ErrorAction Stop
        [void]$Target.WaitForExit(10000)
    }
    if (-not $Target.HasExited) {
        throw 'Processo do gate permaneceu ativo apos encerramento.'
    }
}

function Invoke-Step(
    [string]$Name,
    [string]$Directory,
    [string]$Command,
    [int]$TimeoutSeconds = 600
) {
    Write-Host "`n>>> $Name" -ForegroundColor Cyan
    $code = 1
    $pushed = $false
    $timedOut = $false
    $process = $null
    try {
        Push-Location -LiteralPath $Directory -ErrorAction Stop
        $pushed = $true
        $stepFile = Join-Path $tempBase ("step-{0}.cmd" -f ([Guid]::NewGuid().ToString('N')))
        $stepBody = "@echo off`r`n$Command`r`nexit /b %errorlevel%`r`n"
        [IO.File]::WriteAllText($stepFile, $stepBody, [Text.UTF8Encoding]::new($false))
        $arguments = "/d /s /c `"`"$stepFile`"`""
        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = $cmdExecutable
        $startInfo.Arguments = $arguments
        $startInfo.WorkingDirectory = $Directory
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw 'Falha ao iniciar processo do gate.'
        }
        if ($process.WaitForExit($TimeoutSeconds * 1000)) {
            $code = $process.ExitCode
        } else {
            $timedOut = $true
            Stop-ProcessTree $process
            $code = 124
        }
    } catch {
        Write-Host "Falha ao iniciar o gate no diretorio esperado." -ForegroundColor Red
    } finally {
        if ($null -ne $process -and -not $process.HasExited) {
            try {
                Stop-ProcessTree $process
            } catch {
                $code = 1
            }
        }
        if ($pushed) {
            Pop-Location
        }
    }
    if ($code -ne 0) {
        $detail = if ($timedOut) { "timeout ${TimeoutSeconds}s" } else { "exit $code" }
        $script:failures += "$Name ($detail)"
        Write-Host "[FALHOU] $Name" -ForegroundColor Red
    } else {
        Write-Host "[OK] $Name" -ForegroundColor Green
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Ambiente backend ausente: execute 'cd backend; uv sync'."
}

$runToken = "{0}-{1}" -f $PID, ([Guid]::NewGuid().ToString('N'))
$tempBase = [IO.Path]::GetFullPath((Join-Path $projectRoot ".qa-run-$runToken"))
if ([IO.Path]::GetDirectoryName($tempBase) -ne $projectRoot) {
    throw 'Diretorio temporario de QA resolveu fora da raiz do projeto.'
}
$pytestBase = Join-Path $tempBase 'pytest'
$auditRequirements = Join-Path $tempBase 'audit-requirements.txt'
$pipAuditCache = Join-Path $tempBase 'pip-audit-cache'

# O gate deve medir o checkout, não integrações/modelos/segredos herdados do shell.
$inheritedOverrides = @(
    'POKER_API_TOKEN',
    'POKER_API_TOKEN_FILE',
    'POKER_PUBLIC_DEPLOYMENT',
    'POKER_ALLOWED_ORIGINS',
    'POKER_ROOT_PATH',
    'POKER_ENABLE_REMOTE_VLM',
    'POKER_REMOTE_VLM_CONSENT_TTL_SECONDS',
    'POKER_VLM_URL',
    'POKER_VLM_ALLOWED_HOSTS',
    'POKER_VLM_API_TOKEN',
    'POKER_VLM_TIMEOUT',
    'POKER_VLM_MODEL',
    'POKER_VLM_REDACT_REGIONS',
    'POKER_ALLOWED_HOSTS',
    'POKER_MAX_IMAGE_BYTES',
    'POKER_MAX_IMAGE_PIXELS',
    'POKER_EXPERT_MODEL',
    'POKER_EXPERT_MANIFEST',
    'POKER_EXPERT_CANDIDATE_MANIFEST',
    'POKER_MODEL_MANIFEST',
    'POKER_VISION_MODEL',
    'POKER_VISION_MANIFEST',
    'POKER_CARD_READER',
    'POKER_CARD_READER_MANIFEST',
    'VITE_API',
    'POKER_LOG_DIR',
    'POKER_TEST_LOG_DIR',
    'POKER_WARMUP',
    'HYPOTHESIS_STORAGE_DIRECTORY',
    'UV_CACHE_DIR',
    'NPM_CONFIG_CACHE',
    'COVERAGE_FILE',
    'COVERAGE_PROCESS_START',
    'COVERAGE_RCFILE',
    'MYPY_CACHE_DIR',
    'RUFF_CACHE_DIR',
    'PYTEST_ADDOPTS',
    'PYTEST_PLUGINS',
    'VITE_CACHE_DIR',
    'VITE_OUT_DIR',
    'PLAYWRIGHT_OUTPUT_DIR',
    'POKER_E2E_DIST_DIR',
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'NO_PROXY',
    'NETRC',
    'GIT_ASKPASS',
    'SSH_ASKPASS',
    'PIP_INDEX_URL',
    'PIP_EXTRA_INDEX_URL',
    'PIP_TRUSTED_HOST',
    'PIP_CONFIG_FILE',
    'PIP_CERT',
    'PIP_CLIENT_CERT',
    'PIP_DISABLE_PIP_VERSION_CHECK',
    'UV_INDEX_URL',
    'UV_EXTRA_INDEX_URL',
    'NPM_CONFIG_REGISTRY',
    'NPM_CONFIG_PROXY',
    'NPM_CONFIG_HTTPS_PROXY',
    'NPM_CONFIG_USERCONFIG',
    'NPM_CONFIG_CAFILE',
    'NPM_CONFIG_CA',
    'NPM_CONFIG_CERT',
    'NPM_CONFIG_KEY',
    'NPM_CONFIG__AUTH',
    'NPM_CONFIG__AUTH_TOKEN',
    'NPM_CONFIG_STRICT_SSL',
    'REQUESTS_CA_BUNDLE',
    'CURL_CA_BUNDLE',
    'SSL_CERT_FILE',
    'SSL_CERT_DIR',
    'NODE_EXTRA_CA_CERTS',
    'GIT_CONFIG_GLOBAL',
    'GIT_CONFIG_NOSYSTEM',
    'PYTHONPATH',
    'PYTHONHOME',
    'PYTHONSTARTUP',
    'PYTHONUSERBASE',
    'PYTHONBREAKPOINT',
    'PYTHONINSPECT',
    'PYTHONWARNINGS',
    'PYTHONNOUSERSITE',
    'PYTHONSAFEPATH',
    'NODE_OPTIONS',
    'NODE_PATH',
    'NPM_CONFIG_SCRIPT_SHELL',
    'NPM_CONFIG_NODE_GYP',
    'COREPACK_HOME',
    'COMSPEC',
    'PATH'
)
$secretNamePattern = '(?i)(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|KEY|PRIVATE_KEY|CREDENTIALS?|DSN|CONNECTION_STRING)($|_)|^(HF_|HUGGINGFACE_|HUGGING_FACE_|KAGGLE_|MODAL_|GITHUB_|GH_|OPENAI_|ANTHROPIC_|AWS_|AZURE_|GOOGLE_|GCP_|CLOUDFLARE_|OPENROUTER_|REPLICATE_|WANDB_|COMET_)|^(DATABASE_URL|REDIS_URL)$'
$sensitiveNames = @(
    Get-ChildItem Env: |
        Where-Object { $_.Name -match $secretNamePattern } |
        ForEach-Object { $_.Name }
)
$environmentCarrierPattern = '(?i)^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|NETRC|GIT_ASKPASS|SSH_ASKPASS|GIT_CONFIG_.+|GIT_CREDENTIAL_.+|PIP_.+(?:URL|HOST|CERT|CONFIG_FILE)|UV_.+(?:URL|HOST|CERT)|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|SSL_CERT_FILE|SSL_CERT_DIR|NODE_EXTRA_CA_CERTS|NODE_OPTIONS|NODE_PATH|COREPACK_HOME|NPM_CONFIG_.+|PYTHONPATH|PYTHONHOME|PYTHONSTARTUP|PYTHONUSERBASE|PYTHONBREAKPOINT|PYTHONINSPECT|PYTHONWARNINGS|COMSPEC|PATH)$'
$environmentCarrierNames = @(
    Get-ChildItem Env: |
        Where-Object { $_.Name -match $environmentCarrierPattern } |
        ForEach-Object { $_.Name }
)
$managedEnvironment = @(
    $inheritedOverrides + $sensitiveNames + $environmentCarrierNames |
        Sort-Object -Unique
)
$environmentSnapshot = @{}
foreach ($name in $managedEnvironment) {
    $environmentSnapshot[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    New-Item -ItemType Directory -Path $tempBase -Force -ErrorAction Stop | Out-Null
    foreach ($name in $managedEnvironment) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }

    $env:PATH = $safePath
    $env:ComSpec = $cmdExecutable
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONSAFEPATH = '1'
    $env:POKER_LOG_DIR = Join-Path $tempBase 'logs'
    $env:POKER_TEST_LOG_DIR = Join-Path $tempBase 'logs'
    $env:POKER_WARMUP = '0'
    $env:HYPOTHESIS_STORAGE_DIRECTORY = Join-Path $tempBase 'hypothesis'
    $env:UV_CACHE_DIR = Join-Path $tempBase 'uv-cache'
    $env:NPM_CONFIG_CACHE = Join-Path $tempBase 'npm-cache'
    $env:COVERAGE_FILE = Join-Path $tempBase 'coverage\.coverage'
    $env:MYPY_CACHE_DIR = Join-Path $tempBase 'mypy-cache'
    $env:RUFF_CACHE_DIR = Join-Path $tempBase 'ruff-cache'
    $env:VITE_CACHE_DIR = Join-Path $tempBase 'vite-cache'
    $env:VITE_OUT_DIR = Join-Path $tempBase 'frontend-dist'
    $env:PIP_INDEX_URL = 'https://pypi.org/simple'
    $env:PIP_CONFIG_FILE = 'NUL'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:NPM_CONFIG_REGISTRY = 'https://registry.npmjs.org/'
    $env:NPM_CONFIG_USERCONFIG = Join-Path $tempBase 'npm-userconfig'
    $env:NPM_CONFIG_SCRIPT_SHELL = $cmdExecutable
    [IO.File]::WriteAllText($env:NPM_CONFIG_USERCONFIG, '', [Text.UTF8Encoding]::new($false))
    $env:GIT_CONFIG_GLOBAL = 'NUL'
    $env:GIT_CONFIG_NOSYSTEM = '1'
    New-Item -ItemType Directory -Path (Split-Path $env:COVERAGE_FILE -Parent) `
        -Force -ErrorAction Stop | Out-Null

Invoke-Step 'Backend pytest + branch coverage' $projectRoot `
    "`"$python`" -B -m pytest backend\tests -q --basetemp `"$pytestBase`" -o cache_dir=`"$tempBase\pytest-cache`" --cov=backend\poker_arena --cov-branch --cov-report=term-missing --cov-fail-under=85" `
    600
Invoke-Step 'Backend Ruff' (Join-Path $projectRoot 'backend') `
    "`"$python`" -B -m ruff check poker_arena tests scripts ..\api-docs\generate.py ..\frontend\e2e\run_e2e.py ..\assets\make_icon.py" `
    180
Invoke-Step 'Backend Ruff format policy' (Join-Path $projectRoot 'backend') `
    "`"$python`" -B -m ruff format --check poker_arena tests scripts --exclude scripts/catalog_search_receipt.py" `
    180
# catalog_search_receipt.py permanece lintado acima, mas não é reformatado: seu hash é
# evidência histórica encadeada em docs/research/evidence/catalog_collector_hardening_20260718.json.
# S311 e deliberadamente permitido apenas nos notebooks: seus PRNGs seedados geram
# amostras/augmentations cientificas, nunca tokens, nonces ou credenciais.
Invoke-Step 'Notebook security lint (including F821)' (Join-Path $projectRoot 'backend') `
    "`"$python`" -B -m ruff check ..\ml\notebooks --select S,F821 --ignore S311" `
    180
Invoke-Step 'Backend mypy' (Join-Path $projectRoot 'backend') `
    "`"$python`" -B -m mypy poker_arena" `
    300
Invoke-Step 'Distribution contract' $projectRoot `
    "`"$python`" -B backend\scripts\validate_distribution.py --project-root `"$projectRoot`" --distribution-root `"$distributionRoot`" --release" `
    120
Invoke-Step 'Distribution-root secret scan' $projectRoot `
    "`"$python`" -B backend\scripts\scan_secrets.py --root `"$distributionRoot`"" `
    120
Invoke-Step 'API docs contract drift check' $projectRoot `
    "`"$python`" -B api-docs\generate.py --check" `
    120
Invoke-Step 'Production profile static contract' $projectRoot `
    "`"$python`" -B deploy\production\validate_profile.py" `
    120
Invoke-Step 'Python locked dependency export' $projectRoot `
    "$uvCommand export --project backend --frozen --all-groups --no-emit-project --format requirements.txt --no-header --no-annotate --quiet --output-file `"$auditRequirements`"" `
    120
Invoke-Step 'Python dependency audit (pip-audit)' $projectRoot `
    "`"$python`" -B -m pip_audit --requirement `"$auditRequirements`" --disable-pip --cache-dir `"$pipAuditCache`" --progress-spinner off --timeout 30" `
    300
Invoke-Step 'Frontend tests' (Join-Path $projectRoot 'frontend') "$npmCommand test" 300
Invoke-Step 'Frontend browser E2E navigation' (Join-Path $projectRoot 'frontend') `
    "$npmCommand run test:e2e" `
    360
Invoke-Step 'Frontend TypeScript + production build' (Join-Path $projectRoot 'frontend') `
    "$npmCommand run build" `
    300
Invoke-Step 'Frontend ESLint' (Join-Path $projectRoot 'frontend') "$npmCommand run lint" 300
Invoke-Step 'Frontend dependency audit' (Join-Path $projectRoot 'frontend') `
    "$npmCommand audit --audit-level=high" `
    300

} finally {
    try {
        if (Test-Path -LiteralPath $tempBase) {
            $tempItem = Get-Item -LiteralPath $tempBase -Force -ErrorAction Stop
            $resolvedTemp = [IO.Path]::GetFullPath($tempItem.FullName)
            if ([IO.Path]::GetDirectoryName($resolvedTemp) -ne $projectRoot -or
                -not ([IO.Path]::GetFileName($resolvedTemp).StartsWith('.qa-run-'))) {
                throw 'Recusa de cleanup: alvo temporario nao corresponde ao run isolado.'
            }
            if (($tempItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Recusa de cleanup: raiz temporaria e um reparse point.'
            }
            $nestedReparse = Get-ChildItem -LiteralPath $resolvedTemp -Force -Recurse |
                Where-Object { ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 } |
                Select-Object -First 1
            if ($null -ne $nestedReparse) {
                throw 'Recusa de cleanup: reparse point encontrado dentro do run.'
            }
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction Stop
        }
    } catch {
        $failures += "Cleanup temporario de QA ($($_.Exception.Message))"
        Write-Host "[FALHOU] Cleanup temporario de QA" -ForegroundColor Red
    }
    foreach ($name in $managedEnvironment) {
        $originalValue = $environmentSnapshot[$name]
        if ($null -eq $originalValue) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $originalValue, 'Process')
        }
    }
}

Write-Host "`n======================================================"
if ($failures.Count -eq 0) {
    Write-Host 'TUDO VERDE - todos os gates passaram.' -ForegroundColor Green
    exit 0
}
Write-Host "$($failures.Count) gate(s) falharam:" -ForegroundColor Red
$failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
exit 1
