# Stop only the exact process trees recorded by assets/start.ps1.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$pidFile = Join-Path $projectRoot '.poker-arena.pids.json'
$pidSchema = 'poker-arena-pids-v1'
$maxPidFileBytes = 16 * 1024
$taskkill = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'

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

function Assert-PlainPidFile {
    $item = Get-Item -LiteralPath $pidFile -Force -ErrorAction Stop
    $resolved = [IO.Path]::GetFullPath($item.FullName)
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $item.LinkType) {
        throw 'Registro de PID reparse/link/diretorio recusado.'
    }
    if ([IO.Path]::GetDirectoryName($resolved) -ne $projectRoot -or
        [IO.Path]::GetFileName($resolved) -cne '.poker-arena.pids.json') {
        throw 'Registro de PID resolveu fora do caminho fixado.'
    }
    if ($item.Length -lt 2 -or $item.Length -gt $maxPidFileBytes) {
        throw 'Registro de PID possui tamanho fora do limite permitido.'
    }
}

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Context
    )
    if ($Value -isnot [pscustomobject]) {
        throw "$Context nao e um objeto JSON."
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $wanted = @($Expected | Sort-Object)
    if ($actual.Count -ne $wanted.Count -or
        @(Compare-Object -ReferenceObject $wanted -DifferenceObject $actual).Count -ne 0) {
        throw "$Context possui campos ausentes ou desconhecidos."
    }
}

function Convert-StrictPositiveInteger {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][long]$Maximum,
        [Parameter(Mandatory = $true)][string]$Field
    )
    if ($Value -is [bool] -or $Value -is [string]) {
        throw "$Field deve ser inteiro JSON positivo."
    }
    $integerTypeCodes = @(
        [TypeCode]::Byte,
        [TypeCode]::SByte,
        [TypeCode]::Int16,
        [TypeCode]::UInt16,
        [TypeCode]::Int32,
        [TypeCode]::UInt32,
        [TypeCode]::Int64,
        [TypeCode]::UInt64
    )
    if ($integerTypeCodes -notcontains [Type]::GetTypeCode($Value.GetType())) {
        throw "$Field deve ser inteiro JSON positivo."
    }
    try {
        $number = [Convert]::ToInt64($Value)
    } catch {
        throw "$Field excede o intervalo inteiro permitido."
    }
    if ($number -lt 1 -or $number -gt $Maximum) {
        throw "$Field esta fora do intervalo permitido."
    }
    return $number
}

function Get-Sha256Hex([byte[]]$Payload) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($Payload))).Replace('-', '')
    } finally {
        $sha256.Dispose()
    }
}

function Get-VerifiedOwnedTree([object]$RootRecord) {
    # Capture the parent relation before taskkill and bind every descendant to
    # its immutable process creation time. This gives the native fallback an
    # exact identity proof instead of terminating an unverified/reused PID.
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
    $queue.Enqueue([pscustomobject]@{ pid = [int]$RootRecord.pid; depth = 0 })
    $seen = [Collections.Generic.HashSet[int]]::new()
    $result = @()
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        if (-not $seen.Add([int]$current.pid)) {
            continue
        }
        $process = Get-Process -Id ([int]$current.pid) -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            try {
                $process.Refresh()
                $ticks = $process.StartTime.ToUniversalTime().Ticks
                $path = [IO.Path]::GetFullPath($process.Path)
            } catch {
                throw "Nao foi possivel provar a identidade do descendente PID $($current.pid)."
            }
            if ($ticks -lt [long]$RootRecord.startTicks) {
                throw "Descendente PID $($current.pid) e anterior ao processo raiz; fallback bloqueado."
            }
            $result += [pscustomobject]@{
                pid = [int]$current.pid
                startTicks = [long]$ticks
                executable = $path
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

function Stop-VerifiedIdentity([object]$Identity) {
    $current = Get-Process -Id ([int]$Identity.pid) -ErrorAction SilentlyContinue
    if ($null -eq $current) {
        return
    }
    try {
        $current.Refresh()
        $actualTicks = $current.StartTime.ToUniversalTime().Ticks
        $actualPath = [IO.Path]::GetFullPath($current.Path)
    } catch {
        throw "Nao foi possivel reverificar PID $($Identity.pid) no fallback."
    }
    if ($actualTicks -ne [long]$Identity.startTicks -or
        $actualPath -ine [string]$Identity.executable) {
        throw "PID $($Identity.pid) mudou de identidade; fallback bloqueado."
    }
    Stop-Process -Id ([int]$Identity.pid) -Force -ErrorAction Stop
    [void]$current.WaitForExit(5000)
    if (-not $current.HasExited) {
        throw "PID $($Identity.pid) permaneceu ativo apos fallback nativo."
    }
}

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'Poker Arena nao possui processos registrados.'
    exit 0
}

Assert-PlainPidFile
$taskkillItem = Get-Item -LiteralPath $taskkill -Force -ErrorAction Stop
if ($taskkillItem.PSIsContainer -or
    ($taskkillItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw 'taskkill.exe do sistema nao e um arquivo regular.'
}

$pidBytes = [IO.File]::ReadAllBytes($pidFile)
$pidDigest = Get-Sha256Hex $pidBytes
try {
    $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
    $payload = $strictUtf8.GetString($pidBytes) | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw 'Registro de PID nao e JSON UTF-8 valido.'
}

Assert-ExactProperties $payload @('schema', 'root', 'processes') 'Registro de PID'
if ($payload.schema -isnot [string] -or $payload.schema -cne $pidSchema) {
    throw 'Schema do registro de PID nao reconhecido.'
}
if ($payload.root -isnot [string] -or
    [IO.Path]::GetFullPath($payload.root) -ine $projectRoot) {
    throw 'Registro de PID pertence a outro diretorio; encerramento bloqueado.'
}

$records = @($payload.processes)
if ($records.Count -ne 2) {
    throw 'Registro de PID deve conter exatamente backend e frontend.'
}
$nodeCommand = Get-Command node -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -eq $nodeCommand) {
    throw 'Node.js esperado nao foi encontrado; encerramento fail-closed.'
}
$allowedExecutables = @{
    backend = [IO.Path]::GetFullPath(
        (Join-Path $projectRoot 'backend\.venv\Scripts\python.exe')
    )
    frontend = [IO.Path]::GetFullPath([string]$nodeCommand.Source)
}
$requiredRoles = @('backend', 'frontend')
$seenRoles = @{}
$seenPids = @{}
$validated = @()

foreach ($record in $records) {
    Assert-ExactProperties $record @('role', 'pid', 'executable', 'startTicks') 'Processo'
    if ($record.role -isnot [string] -or $requiredRoles -cnotcontains $record.role) {
        throw 'Role desconhecida no registro de PID.'
    }
    $role = [string]$record.role
    if ($seenRoles.ContainsKey($role)) {
        throw 'Role duplicada no registro de PID.'
    }
    $seenRoles[$role] = $true

    $recordedPid = Convert-StrictPositiveInteger $record.pid ([int]::MaxValue) 'pid'
    if ($seenPids.ContainsKey($recordedPid)) {
        throw 'PID duplicado no registro de processos.'
    }
    $seenPids[$recordedPid] = $true
    $startTicks = Convert-StrictPositiveInteger $record.startTicks ([long]::MaxValue) 'startTicks'
    if ($record.executable -isnot [string] -or
        $record.executable.Length -lt 1 -or
        $record.executable.Length -gt 1024 -or
        $record.executable.IndexOf([char]0) -ge 0) {
        throw 'Executavel invalido no registro de PID.'
    }
    try {
        $declaredExecutable = [IO.Path]::GetFullPath([string]$record.executable)
    } catch {
        throw 'Executavel nao canonico no registro de PID.'
    }
    if ($declaredExecutable -ine $allowedExecutables[$role]) {
        throw "Executavel fora da allowlist para a role $role."
    }
    $validated += [pscustomobject]@{
        role = $role
        pid = [int]$recordedPid
        executable = $declaredExecutable
        startTicks = [long]$startTicks
        process = $null
    }
}
if (@($seenRoles.Keys).Count -ne $requiredRoles.Count) {
    throw 'Roles obrigatorias ausentes no registro de PID.'
}

# Validate every live root before terminating any tree.
foreach ($record in $validated) {
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        continue
    }
    try {
        $process.Refresh()
        $actualExecutable = [IO.Path]::GetFullPath($process.Path)
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
    } catch {
        throw "Nao foi possivel verificar a identidade do PID $($record.pid)."
    }
    if ($actualExecutable -ine $record.executable -or
        $actualTicks -ne $record.startTicks) {
        throw "PID $($record.pid) foi reutilizado ou nao pertence ao Poker Arena."
    }
    $record.process = $process
}

foreach ($record in $validated) {
    $process = $record.process
    if ($null -eq $process) {
        Write-Host "$($record.role) (PID $($record.pid)) ja estava encerrado."
        continue
    }
    $ownedTree = @(Get-VerifiedOwnedTree $record)
    & $taskkill /PID $process.Id /T | Out-Null
    [void]$process.WaitForExit(5000)
    if (-not $process.HasExited) {
        & $taskkill /PID $process.Id /T /F | Out-Null
        [void]$process.WaitForExit(5000)
    }
    if (-not $process.HasExited) {
        # Block further spawning first, then terminate the exact captured
        # descendants deepest-first without depending on taskkill privileges.
        # Recapture immediately before stopping the root so descendants born
        # while taskkill was blocked cannot be reparented out of the snapshot.
        $ownedTree += @(Get-VerifiedOwnedTree $record)
        $rootIdentity = $ownedTree | Where-Object { $_.pid -eq $record.pid } |
            Select-Object -First 1
        if ($null -eq $rootIdentity) {
            throw "Identidade raiz $($record.pid) ausente do snapshot de fallback."
        }
        Stop-VerifiedIdentity $rootIdentity
    }
    $uniqueOwned = @{}
    foreach ($identity in $ownedTree) {
        $key = "$($identity.pid):$($identity.startTicks)"
        $uniqueOwned[$key] = $identity
    }
    foreach ($identity in @($uniqueOwned.Values | Sort-Object depth -Descending)) {
        Stop-VerifiedIdentity $identity
    }
    $remaining = @($uniqueOwned.Values | Where-Object {
        $candidate = Get-Process -Id ([int]$_.pid) -ErrorAction SilentlyContinue
        if ($null -eq $candidate) { return $false }
        try {
            $candidate.Refresh()
            return $candidate.StartTime.ToUniversalTime().Ticks -eq [long]$_.startTicks
        } catch {
            return $true
        }
    })
    if ($remaining.Count -ne 0) {
        throw "Processo $($record.pid) ou descendente permaneceu ativo apos fallback verificado."
    }
    Write-Host "Encerrado $($record.role) (PID $($record.pid))."
}

# Refuse to remove a swapped/reparsed record after process termination.
Assert-PlainPidFile
if ((Get-Sha256Hex ([IO.File]::ReadAllBytes($pidFile))) -cne $pidDigest) {
    throw 'Registro de PID mudou durante o encerramento; remocao bloqueada.'
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction Stop
Write-Host 'Processos registrados do Poker Arena encerrados.'
