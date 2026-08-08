[CmdletBinding()]
param(
    [switch]$OpenBrowser,
    [switch]$ShowUrlsOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$pidFile = Join-Path $projectRoot '.poker-arena.pids.json'
$runtimeDir = Join-Path $projectRoot '.poker-arena-runtime'
$python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$vite = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$taskkill = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
$safeComSpec = Join-Path ([Environment]::SystemDirectory) 'cmd.exe'
$backendPort = 8000
$frontendPort = 5173
$frontendApi = "http://127.0.0.1:$backendPort"
$pidSchema = 'poker-arena-pids-v1'

function Show-SolutionUrls {
    Write-Host ''
    Write-Host 'URLs operacionais do Poker Arena (somente neste computador):'
    Write-Host '  Arena principal......... http://127.0.0.1:5173/'
    Write-Host '  Captura supervisionada.. http://127.0.0.1:5173/?view=capture'
    Write-Host '  Copiloto de estudo....... http://127.0.0.1:5173/?view=copilot'
    Write-Host '  API / Swagger............ http://127.0.0.1:8000/docs'
    Write-Host '  API / ReDoc.............. http://127.0.0.1:8000/redoc'
    Write-Host '  Contrato OpenAPI......... http://127.0.0.1:8000/openapi.json'
    Write-Host '  Saude.................... http://127.0.0.1:8000/health'
    Write-Host '  Prontidao................ http://127.0.0.1:8000/ready'
    Write-Host '  WebSocket de mesa........ ws://127.0.0.1:8000/tables/{table_id}/ws'
    Write-Host '  Todos os endpoints REST estao catalogados no Swagger e no OpenAPI.'
    Write-Host ''
}

if ($ShowUrlsOnly) {
    Show-SolutionUrls
    if ($OpenBrowser) {
        Start-Process 'http://127.0.0.1:5173/?view=capture'
    }
    exit 0
}

if (-not ('PokerArena.NativeProcessTree' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace PokerArena {
    public static class NativeProcessTree {
        private const uint TH32CS_SNAPPROCESS = 0x00000002;
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct PROCESSENTRY32 {
            public uint dwSize;
            public uint cntUsage;
            public uint th32ProcessID;
            public IntPtr th32DefaultHeapID;
            public uint th32ModuleID;
            public uint cntThreads;
            public uint th32ParentProcessID;
            public int pcPriClassBase;
            public uint dwFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string szExeFile;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32FirstW(IntPtr snapshot, ref PROCESSENTRY32 entry);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool Process32NextW(IntPtr snapshot, ref PROCESSENTRY32 entry);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);

        public static Dictionary<int, int> Snapshot() {
            IntPtr snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot == new IntPtr(-1)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            try {
                var result = new Dictionary<int, int>();
                var entry = new PROCESSENTRY32();
                entry.dwSize = (uint)Marshal.SizeOf(entry);
                if (!Process32FirstW(snapshot, ref entry)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                do {
                    result[(int)entry.th32ProcessID] = (int)entry.th32ParentProcessID;
                    entry.dwSize = (uint)Marshal.SizeOf(entry);
                } while (Process32NextW(snapshot, ref entry));
                return result;
            } finally {
                CloseHandle(snapshot);
            }
        }
    }
}
'@
}
$baseEnvironmentNames = @(
    'ALLUSERSPROFILE',
    'APPDATA',
    'HOMEDRIVE',
    'HOMEPATH',
    'LANG',
    'LC_ALL',
    'LOCALAPPDATA',
    'NUMBER_OF_PROCESSORS',
    'OS',
    'PATHEXT',
    'PROCESSOR_ARCHITECTURE',
    'PROCESSOR_IDENTIFIER',
    'PROGRAMDATA',
    'PROGRAMFILES',
    'PROGRAMFILES(X86)',
    'PROGRAMW6432',
    'PUBLIC',
    'PYTHONIOENCODING',
    'PYTHONUTF8',
    'SYSTEMDRIVE',
    'SYSTEMROOT',
    'TEMP',
    'TMP',
    'TZ',
    'USERPROFILE',
    'WINDIR'
)

function Assert-PlainDirectory([string]$Path, [string]$ExpectedParent) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $resolved = [IO.Path]::GetFullPath($item.FullName)
    if (-not $item.PSIsContainer) {
        throw "Caminho de runtime nao e diretorio: $Path"
    }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Diretorio de runtime reparse/link recusado: $Path"
    }
    if ([IO.Path]::GetDirectoryName($resolved) -ne [IO.Path]::GetFullPath($ExpectedParent)) {
        throw 'Diretorio de runtime resolveu fora da raiz do projeto.'
    }
}

function Assert-PlainFile([string]$Path, [string]$ExpectedParent = '') {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $resolved = [IO.Path]::GetFullPath($item.FullName)
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Arquivo executavel/script reparse/link/diretorio recusado: $Path"
    }
    if ($ExpectedParent -and
        [IO.Path]::GetDirectoryName($resolved) -ne [IO.Path]::GetFullPath($ExpectedParent)) {
        throw "Arquivo executavel/script resolveu fora do diretorio permitido: $Path"
    }
    return $resolved
}

function Initialize-PlainLog([string]$Path, [string]$ExpectedParent) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    if ([IO.Path]::GetDirectoryName($fullPath) -ne [IO.Path]::GetFullPath($ExpectedParent)) {
        throw 'Log resolveu fora do diretorio de runtime.'
    }
    if (Test-Path -LiteralPath $fullPath) {
        $item = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if ($item.PSIsContainer -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Log reparse/link/diretorio recusado: $fullPath"
        }
        Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
    }
    $stream = [IO.File]::Open(
        $fullPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    $stream.Dispose()
}

function Assert-LoopbackPortAvailable([int]$Port) {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
    } catch [Net.Sockets.SocketException] {
        throw "Porta local $Port ja esta em uso; nenhum processo foi iniciado."
    } finally {
        $listener.Stop()
    }
}

function Wait-HttpReady(
    [string]$Uri,
    [Diagnostics.Process]$Process,
    [int]$TimeoutSeconds = 30
) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "Servidor terminou antes de ficar pronto (exit $($Process.ExitCode)): $Uri"
        }
        $response = $null
        try {
            $request = [Net.HttpWebRequest]::CreateHttp($Uri)
            $request.AllowAutoRedirect = $false
            $request.Proxy = $null
            $request.Timeout = 1000
            $request.ReadWriteTimeout = 1000
            $response = [Net.HttpWebResponse]$request.GetResponse()
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 400) {
                return
            }
        } catch [Net.WebException] {
            # O socket ainda pode estar subindo; o processo e o prazo continuam sendo checados.
        } finally {
            if ($null -ne $response) {
                $response.Dispose()
            }
        }
        Start-Sleep -Milliseconds 200
    }
    throw "Servidor nao respondeu dentro de $TimeoutSeconds segundos: $Uri"
}

function Start-IsolatedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$StandardOutput,
        [Parameter(Mandatory = $true)][string]$StandardError,
        [Parameter(Mandatory = $true)]
        [ValidateSet('Backend', 'Frontend')][string]$Profile
    )

    $snapshot = [Collections.Generic.Dictionary[string, string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in Get-ChildItem Env:) {
        $snapshot[$entry.Name] = [string]$entry.Value
    }
    $allowed = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($name in $baseEnvironmentNames) {
        [void]$allowed.Add($name)
    }
    foreach ($name in $snapshot.Keys) {
        if ($Profile -eq 'Backend' -and
            $name.StartsWith('POKER_', [StringComparison]::OrdinalIgnoreCase)) {
            [void]$allowed.Add($name)
        }
    }

    try {
        foreach ($name in @($snapshot.Keys)) {
            if (-not $allowed.Contains($name)) {
                [Environment]::SetEnvironmentVariable($name, $null, 'Process')
            }
        }
        [Environment]::SetEnvironmentVariable('COMSPEC', $safeComSpec, 'Process')
        [Environment]::SetEnvironmentVariable('PATH', $safePath, 'Process')
        if ($Profile -eq 'Backend') {
            [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE', '1', 'Process')
            [Environment]::SetEnvironmentVariable('PYTHONSAFEPATH', '1', 'Process')
        } else {
            [Environment]::SetEnvironmentVariable('VITE_API', $frontendApi, 'Process')
        }
        return Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory `
            -ArgumentList $ArgumentList `
            -RedirectStandardOutput $StandardOutput `
            -RedirectStandardError $StandardError `
            -WindowStyle Hidden -PassThru
    } finally {
        foreach ($entry in Get-ChildItem Env:) {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
        foreach ($name in $snapshot.Keys) {
            [Environment]::SetEnvironmentVariable($name, $snapshot[$name], 'Process')
        }
    }
}

function Get-StartedTreeSnapshot([Diagnostics.Process]$Root) {
    $Root.Refresh()
    $rootTicks = $Root.StartTime.ToUniversalTime().Ticks
    $rows = @([PokerArena.NativeProcessTree]::Snapshot().GetEnumerator())
    $children = @{}
    foreach ($row in $rows) {
        $parent = [int]$row.Value
        if (-not $children.ContainsKey($parent)) {
            $children[$parent] = [Collections.Generic.List[int]]::new()
        }
        $children[$parent].Add([int]$row.Key)
    }
    $queue = [Collections.Generic.Queue[object]]::new()
    $queue.Enqueue([pscustomobject]@{ pid = $Root.Id; depth = 0 })
    $seen = [Collections.Generic.HashSet[int]]::new()
    $result = @()
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        if (-not $seen.Add([int]$current.pid)) { continue }
        $process = Get-Process -Id ([int]$current.pid) -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            $process.Refresh()
            $ticks = $process.StartTime.ToUniversalTime().Ticks
            if ($ticks -lt $rootTicks) {
                throw "Descendente PID $($current.pid) anterior ao processo iniciado."
            }
            $result += [pscustomobject]@{
                pid = [int]$current.pid
                startTicks = [long]$ticks
                executable = [IO.Path]::GetFullPath($process.Path)
                depth = [int]$current.depth
            }
        }
        if ($children.ContainsKey([int]$current.pid)) {
            foreach ($childPid in $children[[int]$current.pid]) {
                $queue.Enqueue([pscustomobject]@{
                    pid = [int]$childPid
                    depth = [int]$current.depth + 1
                })
            }
        }
    }
    return @($result)
}

function Stop-StartedTree([Diagnostics.Process]$Root) {
    if ($Root.HasExited) { return }
    $owned = @(Get-StartedTreeSnapshot $Root)
    & $taskkill /PID $Root.Id /T /F | Out-Null
    [void]$Root.WaitForExit(5000)
    if (-not $Root.HasExited) {
        # Close the spawn-to-snapshot window before terminating the root.
        $owned += @(Get-StartedTreeSnapshot $Root)
        $rootIdentity = $owned | Where-Object { $_.pid -eq $Root.Id } |
            Select-Object -First 1
        $fresh = Get-Process -Id $Root.Id -ErrorAction SilentlyContinue
        if ($null -eq $rootIdentity -or $null -eq $fresh) {
            throw 'Identidade do processo iniciado indisponivel no fallback.'
        }
        $fresh.Refresh()
        if ($fresh.StartTime.ToUniversalTime().Ticks -ne $rootIdentity.startTicks -or
            [IO.Path]::GetFullPath($fresh.Path) -ine $rootIdentity.executable) {
            throw 'PID do processo iniciado mudou; fallback bloqueado.'
        }
        Stop-Process -Id $Root.Id -Force -ErrorAction Stop
        [void]$fresh.WaitForExit(5000)
    }
    foreach ($identity in @($owned | Sort-Object depth -Descending)) {
        $candidate = Get-Process -Id ([int]$identity.pid) -ErrorAction SilentlyContinue
        if ($null -eq $candidate) { continue }
        $candidate.Refresh()
        if ($candidate.StartTime.ToUniversalTime().Ticks -ne $identity.startTicks -or
            [IO.Path]::GetFullPath($candidate.Path) -ine $identity.executable) {
            throw "PID $($identity.pid) mudou; cleanup de inicializacao bloqueado."
        }
        Stop-Process -Id ([int]$identity.pid) -Force -ErrorAction Stop
        [void]$candidate.WaitForExit(5000)
        if (-not $candidate.HasExited) {
            throw "PID $($identity.pid) permaneceu ativo no cleanup de inicializacao."
        }
    }
}

if (Test-Path -LiteralPath $pidFile) {
    throw 'Ja existe um registro de processos. Execute assets\stop.ps1 primeiro.'
}
$nodeCommand = Get-Command node -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $nodeCommand) {
    throw 'Node.js nao encontrado no PATH.'
}

$python = Assert-PlainFile $python (Join-Path $projectRoot 'backend\.venv\Scripts')
$node = Assert-PlainFile ([string]$nodeCommand.Source)
$vite = Assert-PlainFile $vite (Join-Path $projectRoot 'frontend\node_modules\vite\bin')
$taskkill = Assert-PlainFile $taskkill ([Environment]::SystemDirectory)
$safeComSpec = Assert-PlainFile $safeComSpec ([Environment]::SystemDirectory)
$safePathDirectories = @(
    (Split-Path $python -Parent),
    (Split-Path $node -Parent),
    ([Environment]::SystemDirectory),
    (Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0')
)
$safePath = (($safePathDirectories | Sort-Object -Unique) -join [IO.Path]::PathSeparator)

Assert-LoopbackPortAvailable $backendPort
Assert-LoopbackPortAvailable $frontendPort

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
Assert-PlainDirectory $runtimeDir $projectRoot
$backendStdout = Join-Path $runtimeDir 'backend.stdout.log'
$backendStderr = Join-Path $runtimeDir 'backend.stderr.log'
$frontendStdout = Join-Path $runtimeDir 'frontend.stdout.log'
$frontendStderr = Join-Path $runtimeDir 'frontend.stderr.log'
foreach ($logPath in @($backendStdout, $backendStderr, $frontendStdout, $frontendStderr)) {
    Initialize-PlainLog $logPath $runtimeDir
}

$started = @()
try {
    $backend = Start-IsolatedProcess `
        -FilePath $python `
        -WorkingDirectory (Join-Path $projectRoot 'backend') `
        -ArgumentList @(
            '-m',
            'uvicorn',
            'poker_arena.api.app:app',
            '--host',
            '127.0.0.1',
            '--port',
            "$backendPort"
        ) `
        -StandardOutput $backendStdout `
        -StandardError $backendStderr `
        -Profile Backend
    $started += $backend
    Wait-HttpReady "http://127.0.0.1:$backendPort/ready" $backend

    $frontend = Start-IsolatedProcess `
        -FilePath $node `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') `
        -ArgumentList @(
            $vite,
            '--configLoader',
            'runner',
            '--host',
            '127.0.0.1',
            '--port',
            "$frontendPort",
            '--strictPort'
        ) `
        -StandardOutput $frontendStdout `
        -StandardError $frontendStderr `
        -Profile Frontend
    $started += $frontend
    Wait-HttpReady "http://127.0.0.1:$frontendPort/" $frontend

    $pidPayload = [ordered]@{
        schema = $pidSchema
        root = $projectRoot
        processes = @(
            [ordered]@{
                role = 'backend'
                pid = $backend.Id
                executable = $python
                startTicks = $backend.StartTime.ToUniversalTime().Ticks
            },
            [ordered]@{
                role = 'frontend'
                pid = $frontend.Id
                executable = $node
                startTicks = $frontend.StartTime.ToUniversalTime().Ticks
            }
        )
    }
    $pidJson = $pidPayload | ConvertTo-Json -Depth 4
    $pidStream = [IO.File]::Open(
        $pidFile,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $writer = [IO.StreamWriter]::new($pidStream, [Text.UTF8Encoding]::new($false))
        try {
            $writer.Write($pidJson)
        } finally {
            $writer.Dispose()
        }
    } finally {
        if ($null -ne $pidStream) {
            $pidStream.Dispose()
        }
    }
} catch {
    $launchError = $_
    foreach ($process in @($started)) {
        try {
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-StartedTree $process
            }
        } catch {
            # Preserve the original launch failure after attempting every owned tree.
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    throw $launchError
}

Write-Host "Poker Arena iniciado: backend PID $($backend.Id), frontend PID $($frontend.Id)."
Write-Host "Logs: $runtimeDir"
Show-SolutionUrls
if ($OpenBrowser) {
    Start-Process 'http://127.0.0.1:5173/?view=capture'
}
