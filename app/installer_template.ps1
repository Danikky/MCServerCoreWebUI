#PSBEGIN
# Автоустановщик сборки для TLauncher. Этот файл — шаблон: панель подставляет
# адрес сборки и отдаёт его как /pack/<id>/installer.ps1; .bat у игрока —
# только маленький загрузчик этого скрипта (см. app/client_pack.py), так что
# исправления здесь доходят до всех без перекачивания .bat.
# Только синтаксис Windows PowerShell 5.1 (без ?:, ??, && из PowerShell 7).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$PackUrl = '__PACK_URL__'
$IsWin = ($env:OS -eq 'Windows_NT')
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }

function Get-Sha1([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA1).Hash.ToLower()
}

function Get-RemoteText([string]$Url) {
    $c = New-Object System.Net.WebClient
    $c.Encoding = [System.Text.Encoding]::UTF8
    $c.Headers.Add('User-Agent', 'MCServerCore-Installer/2')
    try { return $c.DownloadString($Url) } finally { $c.Dispose() }
}

# Потоковое скачивание во временный .part с таймаутами и (для больших
# файлов) процентами в одной строке — иначе на сотнях мегабайт окно минутами
# молчит и выглядит зависшим.
function Save-Url([string]$Url, [string]$Part, [bool]$ShowProgress) {
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.UserAgent = 'MCServerCore-Installer/2'
    $req.Timeout = 30000
    $req.ReadWriteTimeout = 60000
    $resp = $req.GetResponse()
    try {
        $total = $resp.ContentLength
        $in = $resp.GetResponseStream()
        $out = [System.IO.File]::Create($Part)
        try {
            $buf = New-Object byte[] 262144
            $done = 0
            $shownAt = [DateTime]::MinValue
            while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                $out.Write($buf, 0, $n)
                $done += $n
                if ($ShowProgress -and $total -gt 0 -and ((Get-Date) - $shownAt).TotalMilliseconds -gt 400) {
                    Write-Host -NoNewline ("`r    {0:N1} из {1:N1} МБ ({2}%)   " -f ($done / 1MB), ($total / 1MB), [math]::Floor($done * 100 / $total))
                    $shownAt = Get-Date
                }
            }
            if ($ShowProgress -and $total -gt 0) { Write-Host ("`r    {0:N1} МБ — скачано          " -f ($total / 1MB)) }
        } finally { $out.Dispose(); $in.Dispose() }
    } finally { $resp.Close() }
}

# Три попытки с паузой: на сотнях модов разовый сетевой сбой — обычное дело.
# Проверка sha1 до того, как файл ляжет на место, — оборванная загрузка не
# оставит битый мод в папке.
function Get-RemoteFile([string]$Url, [string]$Dest, [string]$Sha1, [long]$Size = 0) {
    $part = "$Dest.part"
    $showProgress = ($Size -gt 5MB)
    $hashMismatch = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Save-Url $Url $part $showProgress
            if ($Sha1 -and ((Get-Sha1 $part) -ne $Sha1)) {
                $hashMismatch = $true
                throw 'не совпала контрольная сумма'
            }
            Move-Item -LiteralPath $part -Destination $Dest -Force
            return
        } catch {
            if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue }
            if ($attempt -eq 3) {
                if ($hashMismatch) {
                    throw "Файл на сервере не совпадает с описанием сборки — скорее всего, её обновили прямо во время установки. Запусти установщик ещё раз. ($Url)"
                }
                throw "Не удалось скачать $Url : $($_.Exception.Message)"
            }
            Say "    сбой загрузки ($($_.Exception.Message)), повтор $($attempt + 1)/3..." Yellow
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
}

# Читает текстовый файл, даже если его держит открытым другая программа
# (TLauncher не отпускает свой tlauncher-2.0.properties, пока запущен).
# Не получилось — $null, не исключение.
function Read-SharedText([string]$Path) {
    try {
        $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        $fs = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
        try {
            $reader = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
            return $reader.ReadToEnd()
        } finally { $fs.Dispose() }
    } catch {
        return $null
    }
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return ([System.IO.File]::ReadAllText($Path) | ConvertFrom-Json) } catch { return $null }
}

function ConvertTo-Hashtable($Object) {
    $h = @{}
    if ($Object) { foreach ($p in $Object.PSObject.Properties) { $h[$p.Name] = [string]$p.Value } }
    return $h
}

# ---- папка игры TLauncher ----------------------------------------------------
# Порядок: путь, переданный .bat-файлу аргументом -> папка из настроек
# TLauncher -> стандартная %APPDATA%\.minecraft -> спросить у игрока.
function Find-GameDir {
    if ($env:MCSC_GAMEDIR) {
        $explicit = $env:MCSC_GAMEDIR.Trim('"').TrimEnd('\', '/')
        if (-not (Test-Path -LiteralPath $explicit -PathType Container)) { throw "Папка не найдена: $explicit" }
        return $explicit
    }
    $candidates = @()
    if ($env:APPDATA) {
        $props = Join-Path (Join-Path $env:APPDATA '.tlauncher') 'tlauncher-2.0.properties'
        $propsText = $null
        if (Test-Path -LiteralPath $props) { $propsText = Read-SharedText $props }
        if ($propsText) {
            foreach ($line in ($propsText -split "`r?`n")) {
                # Точное имя ключа не задокументировано — берём любой ключ с
                # «gamedir» в названии (minecraft.gamedir и т.п.).
                if ($line -match '^\s*[\w.\-]*gamedir[\w.\-]*\s*=\s*(.+)$') {
                    # .properties экранирует "\" и ":" -> C\:\\Games\\mc
                    $candidates += (($Matches[1].Trim() -replace '\\\\', '\') -replace '\\:', ':')
                }
            }
        }
        $candidates += (Join-Path $env:APPDATA '.minecraft')
    }
    # Сначала папка, где уже есть versions (TLauncher в ней работал), потом любая существующая.
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath (Join-Path $c 'versions') -PathType Container)) { return $c.TrimEnd('\', '/') }
    }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c -PathType Container)) { return $c.TrimEnd('\', '/') }
    }
    Say 'Не нашёл папку игры TLauncher автоматически.' Yellow
    Say 'Открой TLauncher -> значок папки рядом с кнопкой запуска, скопируй путь из адресной строки проводника.'
    while ($true) {
        $answer = (Read-Host 'Путь к папке игры (.minecraft)').Trim().Trim('"').TrimEnd('\', '/')
        if ($answer -and (Test-Path -LiteralPath $answer -PathType Container)) { return $answer }
        Say 'Такой папки нет, попробуй ещё раз.' Yellow
    }
}

# ---- TLauncher и игра ---------------------------------------------------------
# Пока открыт TLauncher, он держит свои файлы и может перезаписать их при
# выходе; пока запущена игра, заняты файлы модов. Поэтому перед установкой
# закрываем оба, а TLauncher в конце запускаем снова.
# 'game' — запущенный Minecraft (любой лаунчер), 'launcher' — сам TLauncher.
function Get-ProcessKind([string]$Name, [string]$CommandLine) {
    if ($CommandLine -match '--gameDir|--assetsDir|net\.minecraft\.|bootstraplauncher|cpw\.mods') { return 'game' }
    if ($Name -eq 'TLauncher.exe' -or $CommandLine -match 'tlauncher') { return 'launcher' }
    return ''
}

function Get-MinecraftProcesses {
    $result = @{ Game = @(); Launcher = @() }
    if (-not $IsWin) { return $result }
    $procs = @(Get-CimInstance Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe' OR Name='TLauncher.exe'" -ErrorAction SilentlyContinue)
    foreach ($p in $procs) {
        $kind = Get-ProcessKind $p.Name ([string]$p.CommandLine)
        if ($kind -eq 'game') { $result.Game += $p }
        elseif ($kind -eq 'launcher') { $result.Launcher += $p }
    }
    return $result
}

function Stop-ProcessList($List) {
    foreach ($p in $List) {
        $proc = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
        if ($proc) { [void]$proc.CloseMainWindow() }
    }
    for ($i = 0; $i -lt 10; $i++) {
        $alive = @($List | Where-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue })
        if (-not $alive.Count) { return }
        Start-Sleep -Milliseconds 500
    }
    foreach ($p in $List) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

function Close-Minecraft {
    $found = Get-MinecraftProcesses
    if ($found.Game.Count) {
        Say 'Сейчас запущен Minecraft. Сохранись и выйди из мира — игра будет закрыта.' Yellow
        [void](Read-Host 'Нажми Enter, чтобы закрыть игру и продолжить')
        Stop-ProcessList $found.Game
        Say '  игра закрыта'
    }
    if ($found.Launcher.Count) {
        foreach ($p in $found.Launcher) {
            if ($p.Name -eq 'TLauncher.exe' -and $p.ExecutablePath) { $script:TLauncherExe = $p.ExecutablePath }
        }
        Stop-ProcessList $found.Launcher
        $script:TLauncherClosed = $true
    }
    # Не закрылось (обычно — запущено от имени администратора, а у скрипта
    # таких прав нет): просим закрыть руками, а не ставим сборку поверх.
    for ($try = 1; $try -le 3; $try++) {
        $left = Get-MinecraftProcesses
        if (-not ($left.Game.Count + $left.Launcher.Count)) { break }
        Say 'Не получилось закрыть TLauncher или игру (возможно, они запущены от имени администратора).' Yellow
        [void](Read-Host 'Закрой их вручную и нажми Enter')
    }
    if ($script:TLauncherClosed) { Say '  TLauncher закрыт, после установки запущу его снова' }
}

function Start-TLauncher([string]$GameDir) {
    $exe = $script:TLauncherExe
    if (-not $exe) {
        $candidates = @()
        if ($GameDir) { $candidates += (Join-Path $GameDir 'TLauncher.exe') }
        if ($env:APPDATA) { $candidates += (Join-Path (Join-Path $env:APPDATA '.minecraft') 'TLauncher.exe') }
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c) { $exe = $c; break }
        }
    }
    if ($exe) {
        Start-Process -FilePath $exe -ErrorAction SilentlyContinue
        Say 'TLauncher запускается...'
    } else {
        Say 'Запусти TLauncher вручную.'
    }
}

# Права администратора нужны, только если папка игры лежит там, куда
# обычному пользователю писать нельзя (например, Program Files). Тогда
# перезапускаемся с правами администратора и передаём уже найденный путь
# аргументом: у администратора свой %APPDATA%, сам он папку не найдёт.
function Test-NeedsElevation([string]$GameDir) {
    $versions = Join-Path $GameDir 'versions'
    try {
        [System.IO.Directory]::CreateDirectory($versions) | Out-Null
        $probe = Join-Path $versions ('.mcsc-write-test-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
        [System.IO.File]::WriteAllText($probe, 'ok')
        Remove-Item -LiteralPath $probe -Force
        return $false
    } catch [System.UnauthorizedAccessException] {
        return $true
    }
}

function Test-IsAdmin {
    if (-not $IsWin) { return $false }
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object System.Security.Principal.WindowsPrincipal($id)).IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---- Java --------------------------------------------------------------------
# Установщику Forge/NeoForge нужна Java не старее той, что требует сама версия
# Minecraft (на старой он падает с невнятной ошибкой). Своя Java у игрока стоит
# редко, зато TLauncher качает её сам в <папка игры>\runtime — ищем там и в
# обычных местах установки.
function Get-RequiredJava([string]$Minecraft) {
    if ($Minecraft -notmatch '^1\.\d+') { return 21 }   # снапшоты вида 24w14a — новые версии
    try {
        $parts = $Minecraft.Split('.')
        $minor = [int]$parts[1]
        $patch = 0
        if ($parts.Count -gt 2) { $patch = [int]$parts[2] }
    } catch {
        return 21
    }
    if ($minor -gt 20 -or ($minor -eq 20 -and $patch -ge 5)) { return 21 }
    if ($minor -ge 18) { return 17 }
    if ($minor -eq 17) { return 16 }
    return 8
}

function Get-JavaMajor([string]$Exe) {
    $release = Join-Path (Split-Path (Split-Path $Exe -Parent) -Parent) 'release'
    $text = $null
    if (Test-Path -LiteralPath $release) { $text = Read-SharedText $release }
    if ($text) {
        foreach ($line in ($text -split "`r?`n")) {
            if ($line -match '^JAVA_VERSION="?(\d+)(?:\.(\d+))?') {
                $major = [int]$Matches[1]
                if ($major -eq 1 -and $Matches[2]) { $major = [int]$Matches[2] }   # "1.8.0_51" -> 8
                return $major
            }
        }
    }
    return 0
}

function Find-Java([string]$GameDir, [int]$MinMajor) {
    $exeName = 'java'
    if ($IsWin) { $exeName = 'java.exe' }
    $roots = @((Join-Path $GameDir 'runtime'))
    if ($env:APPDATA) { $roots += (Join-Path $env:APPDATA '.tlauncher') }
    if ($env:JAVA_HOME) { $roots += $env:JAVA_HOME }
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $pf) { continue }
        foreach ($sub in @('Java', 'Eclipse Adoptium', 'Microsoft', 'Zulu', 'BellSoft', 'Minecraft Launcher\runtime')) {
            $roots += (Join-Path $pf $sub)
        }
    }
    if ($env:LOCALAPPDATA) {
        $roots += (Join-Path $env:LOCALAPPDATA 'Packages\Microsoft.4297127D64EC6_8wekyb3d8bbwe\LocalCache\Local\runtime')
    }
    $found = @()
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $found += @(Get-ChildItem -LiteralPath $root -Recurse -Filter $exeName -File -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName })
    }
    $onPath = Get-Command java -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($onPath) { $found += $onPath.Source }

    $best = $null
    $bestMajor = -1
    $unknown = $null
    $seen = @()
    foreach ($exe in $found) {
        $major = Get-JavaMajor $exe
        if ($major -eq 0) { if (-not $unknown) { $unknown = $exe }; continue }
        $seen += $major
        if ($major -ge $MinMajor -and $major -gt $bestMajor) { $best = $exe; $bestMajor = $major }
    }
    if ($best) { return $best }
    # Версию определить не удалось (нет файла release) — пробуем как последний шанс.
    if ($unknown) { return $unknown }
    $script:JavaSeen = ($seen | Sort-Object -Unique) -join ', '
    return $null
}

function Format-Arg([string]$Value) {
    if ($IsWin) { return '"' + $Value + '"' }
    return $Value
}

# ---- загрузчик (Forge/NeoForge) -----------------------------------------------
# Ставится один раз на папку игры; список успешно установленных — в
# <папка игры>\.mcsc-loaders.json. Наличия versions\<id>\<id>.json мало:
# установщик пишет его раньше, чем заканчивает патчить игру, и после сбоя
# посередине «установленный» загрузчик не запустился бы.
function Install-Loader($Manifest, [string]$GameDir, [string]$Tmp) {
    $loaderId = [string]$Manifest.loader.id
    $versionsDir = Join-Path $GameDir 'versions'
    $listPath = Join-Path $GameDir '.mcsc-loaders.json'
    $installed = @()
    $saved = Read-JsonFile $listPath
    if ($saved) { $installed = @($saved) }
    if ($installed -contains $loaderId) {
        Step "Загрузчик $loaderId уже установлен"
        return
    }

    $mcVersion = [string]$Manifest.loader.minecraft
    $minJava = Get-RequiredJava $mcVersion
    $offline = [bool]$Manifest.installer.offline
    if ($offline) {
        Step "Устанавливаю $loaderId (всё нужное качается с сервера сборки)"
    } else {
        Step "Устанавливаю $loaderId (несколько минут, качает Minecraft и библиотеки)"
    }
    $java = Find-Java $GameDir $minJava
    if (-not $java) {
        $hint = ''
        if ($script:JavaSeen) { $hint = " Найдена только Java $($script:JavaSeen) — для Minecraft $mcVersion нужна $minJava или новее." }
        throw ("Не нашёл подходящую Java.$hint Запусти в TLauncher один раз обычный Minecraft $mcVersion " +
            '(лаунчер сам скачает нужную Java), закрой игру и запусти этот установщик снова.')
    }
    Say "  Java: $java"
    $installerJar = Join-Path $Tmp 'loader-installer.jar'
    Get-RemoteFile $Manifest.installer.url $installerJar $Manifest.installer.sha1 ([long]$Manifest.installer.size)

    # Установщик отказывается работать без launcher_profiles.json (файл
    # официального лаунчера) и дописывает в него свой профиль. Своё
    # содержимое игрока сохраняем и возвращаем как было.
    $profiles = Join-Path $GameDir 'launcher_profiles.json'
    $profilesBackup = $null
    if (Test-Path -LiteralPath $profiles) {
        $profilesBackup = [System.IO.File]::ReadAllBytes($profiles)
    } else {
        [System.IO.File]::WriteAllText($profiles, '{"profiles":{}}', $Utf8NoBom)
    }
    $loaderDir = Join-Path $versionsDir $loaderId
    $hadLoaderDir = Test-Path -LiteralPath $loaderDir
    try {
        $argList = @('-jar', (Format-Arg $installerJar), '--installClient', (Format-Arg $GameDir))
        if ($offline) { $argList += '--offline' }
        $proc = Start-Process -FilePath $java -ArgumentList $argList -WorkingDirectory $Tmp -NoNewWindow -Wait -PassThru
        $exitCode = $proc.ExitCode
    } finally {
        if ($profilesBackup) {
            [System.IO.File]::WriteAllBytes($profiles, $profilesBackup)
        } elseif (Test-Path -LiteralPath $profiles) {
            Remove-Item -LiteralPath $profiles -Force
        }
    }
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $loaderDir "$loaderId.json"))) {
        throw "Установщик загрузчика завершился с ошибкой (код $exitCode). Его журнал: $Tmp"
    }
    $installed += $loaderId
    [System.IO.File]::WriteAllText($listPath, (ConvertTo-Json @($installed)), $Utf8NoBom)
    # Версия сборки самодостаточна (в ней тот же JSON), а отдельная
    # «neoforge-…» в списке TLauncher только путает: игроки запускают её и
    # получают игру без модов. Убираем, если её создали мы, а не игрок раньше.
    if (-not $hadLoaderDir) { Remove-Item -LiteralPath $loaderDir -Recurse -Force -ErrorAction SilentlyContinue }
}

# ---- overrides ----------------------------------------------------------------
# Пишем только то, что админ изменил с прошлой установки (сравнение хэшей из
# манифеста: прошлый vs текущий), и удаляем то, что он убрал. Файлы, которые
# на сервере не менялись, не трогаем — правки игрока в конфигах переживают
# обновление сборки.
function Sync-Overrides($Manifest, [string]$VersionDir, [string]$Tmp, $OldFiles) {
    $newFiles = ConvertTo-Hashtable $Manifest.overrides.files
    $keepIfExists = @('options.txt', 'optionsof.txt', 'optionsshaders.txt')
    $toWrite = @{}
    foreach ($rel in $newFiles.Keys) {
        $dest = Join-Path $VersionDir $rel
        $exists = Test-Path -LiteralPath $dest
        if ($exists -and ($keepIfExists -contains $rel.ToLower())) { continue }
        if (-not $exists -or $OldFiles[$rel] -ne $newFiles[$rel]) { $toWrite[$rel] = $true }
    }
    $removed = 0
    foreach ($rel in $OldFiles.Keys) {
        if (-not $newFiles.ContainsKey($rel)) {
            $dest = Join-Path $VersionDir $rel
            if (Test-Path -LiteralPath $dest -PathType Leaf) { Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue; $removed++ }
        }
    }
    if (-not $toWrite.Count) {
        Step 'Конфиги и ресурсы уже актуальны'
        if ($removed) { Say "  удалено устаревших файлов: $removed" }
        return $newFiles
    }
    Step ("Конфиги и ресурсы: обновить {0} файл(ов), скачиваю {1:N1} МБ" -f $toWrite.Count, ($Manifest.overrides.size / 1MB))
    $zipPath = Join-Path $Tmp 'overrides.zip'
    Get-RemoteFile $Manifest.overrides.url $zipPath $Manifest.overrides.sha1 ([long]$Manifest.overrides.size)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $rootFull = [System.IO.Path]::GetFullPath($VersionDir).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $written = 0
    $failed = 0
    $firstError = $null
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $rel = $entry.FullName.Replace('\', '/')
            if (-not $toWrite.ContainsKey($rel)) { continue }
            $dest = [System.IO.Path]::GetFullPath((Join-Path $VersionDir $rel))
            if (-not $dest.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
            try {
                [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($dest)) | Out-Null
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
                $written++
            } catch {
                # Обычно — слишком длинный путь (ограничение Windows в 260
                # символов). Один такой файл не повод бросать всю установку.
                $failed++
                if (-not $firstError) { $firstError = "$rel : $($_.Exception.Message)" }
            }
        }
    } finally {
        $zip.Dispose()
    }
    Say "  обновлено файлов: $written, удалено устаревших: $removed"
    if ($failed) { Say "  не удалось распаковать: $failed (первый: $firstError)" Yellow }
    return $newFiles
}

# ---- установка ---------------------------------------------------------------
function Install-Pack {
    if ($PSVersionTable.PSVersion.Major -lt 5) { throw 'Нужен PowerShell 5 или новее (Windows 10/11).' }
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
    } catch { }

    Step 'Получаю описание сборки'
    $manifest = Get-RemoteText "$PackUrl/manifest.json" | ConvertFrom-Json
    $name = [string]$manifest.name
    $mods = @($manifest.mods)
    Say "  сборка: $name"
    Say "  Minecraft $($manifest.loader.minecraft), загрузчик $($manifest.loader.id)"
    Say "  модов: $($mods.Count)"

    if ($IsWin) {
        Step 'Закрываю TLauncher и игру'
        Close-Minecraft
    }

    Step 'Ищу папку игры TLauncher'
    $gameDir = Find-GameDir
    Say "  $gameDir"
    if (Test-NeedsElevation $gameDir) {
        if ((Test-IsAdmin) -or -not $env:MCSC_SELF) { throw "Нет прав на запись в папку игры: $gameDir" }
        Say '  в эту папку нельзя писать без прав администратора — перезапускаюсь с ними (подтверди запрос Windows)' Yellow
        Start-Process -FilePath $env:MCSC_SELF -ArgumentList ('"' + $gameDir + '"') -Verb RunAs
        Say '  установка продолжится в новом окне, это можно закрыть'
        $script:HandedOver = $true
        return
    }
    $versionsDir = Join-Path $gameDir 'versions'
    $versionDir = Join-Path $versionsDir $name
    $modsDir = Join-Path $versionDir 'mods'
    $statePath = Join-Path $versionDir '.mcsc-pack.json'

    # Место на диске: моды + архив overrides (он и качается, и распаковывается)
    # + запас на Minecraft с библиотеками загрузчика.
    $need = 600MB
    foreach ($mod in $mods) { $need += [long]$mod.size }
    if ($manifest.overrides) { $need += 3 * [long]$manifest.overrides.size }
    try {
        $drive = New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($gameDir)))
        if ($drive.AvailableFreeSpace -lt $need) {
            throw ("Мало места на диске {0}: свободно {1:N1} ГБ, нужно около {2:N1} ГБ." -f $drive.Name, ($drive.AvailableFreeSpace / 1GB), ($need / 1GB))
        }
    } catch [System.ArgumentException] { }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('mcsc-pack-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [System.IO.Directory]::CreateDirectory($tmp) | Out-Null
    $script:TempDir = $tmp

    Install-Loader $manifest $gameDir $tmp

    # Сборку переименовали на панели — переносим старую папку (миры, настройки,
    # скриншоты) под новое имя, а не ставим рядом вторую копию на гигабайт.
    $packPath = ([uri]$PackUrl).AbsolutePath
    if (-not (Test-Path -LiteralPath $versionDir) -and (Test-Path -LiteralPath $versionsDir)) {
        foreach ($dir in @(Get-ChildItem -LiteralPath $versionsDir -Directory -ErrorAction SilentlyContinue)) {
            $old = Read-JsonFile (Join-Path $dir.FullName '.mcsc-pack.json')
            if ($old -and $old.pack_url -and (([uri][string]$old.pack_url).AbsolutePath -eq $packPath)) {
                Step "Сборка переименована: «$($dir.Name)» -> «$name», переношу миры и настройки"
                Move-Item -LiteralPath $dir.FullName -Destination $versionDir
                $oldJson = Join-Path $versionDir "$($dir.Name).json"
                if (Test-Path -LiteralPath $oldJson) { Remove-Item -LiteralPath $oldJson -Force }
                break
            }
        }
    }

    $state = Read-JsonFile $statePath
    if ($state) {
        Step "Сборка «$name» уже установлена — обновляю"
    } else {
        Step "Создаю версию «$name»"
    }
    [System.IO.Directory]::CreateDirectory($modsDir) | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $versionDir "$name.json"), [string]$manifest.version_json, $Utf8NoBom)

    # Что мы ставили в прошлый раз — чтобы при обновлении удалить моды,
    # убранные из сборки, и не трогать те, что игрок добавил сам.
    $oldMods = @()
    $oldOverrideFiles = @{}
    if ($state) {
        $oldMods = @($state.mods)
        $oldOverrideFiles = ConvertTo-Hashtable $state.overrides_files
    }

    Step 'Моды'
    Get-ChildItem -LiteralPath $modsDir -Filter '*.part' -File -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    $wanted = @{}
    foreach ($mod in $mods) { $wanted[[string]$mod.name] = $true }
    $removed = 0
    foreach ($old in $oldMods) {
        if ($old -and -not $wanted.ContainsKey([string]$old)) {
            $stale = Join-Path $modsDir $old
            if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale -Force; $removed++ }
        }
    }
    $downloaded = 0
    $index = 0
    foreach ($mod in $mods) {
        $index++
        $dest = Join-Path $modsDir $mod.name
        if ((Test-Path -LiteralPath $dest) -and ((Get-Item -LiteralPath $dest).Length -eq [long]$mod.size) -and ((Get-Sha1 $dest) -eq $mod.sha1)) {
            continue
        }
        Say ("  [{0}/{1}] {2}" -f $index, $mods.Count, $mod.name)
        Get-RemoteFile $mod.url $dest $mod.sha1 ([long]$mod.size)
        $downloaded++
    }
    Say "  скачано: $downloaded, уже было: $($mods.Count - $downloaded), удалено лишних: $removed"
    $extra = @(Get-ChildItem -LiteralPath $modsDir -Filter '*.jar' -File -ErrorAction SilentlyContinue |
        Where-Object { -not $wanted.ContainsKey($_.Name) } | ForEach-Object { $_.Name })
    if ($extra.Count) {
        Say ("  в папке есть моды не из сборки ({0}): {1}" -f $extra.Count, (($extra | Select-Object -First 8) -join ', ')) Yellow
        Say '  если игра вылетает при запуске — сначала убери их.' Yellow
    }

    $newOverrideFiles = @{}
    if ($manifest.overrides) {
        $newOverrideFiles = Sync-Overrides $manifest $versionDir $tmp $oldOverrideFiles
    }

    $newState = @{
        pack_url = $PackUrl
        loader = [string]$manifest.loader.id
        mods = @($mods | ForEach-Object { [string]$_.name })
        overrides_files = $newOverrideFiles
    }
    [System.IO.File]::WriteAllText($statePath, ($newState | ConvertTo-Json -Depth 4), $Utf8NoBom)

    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Say "Готово! В TLauncher выбери версию «$name»." Green
    if ($manifest.ram_gb) {
        $ram = [int]$manifest.ram_gb
        Say "Выдели игре память: в настройках TLauncher (шестерёнка) поставь не меньше $ram ГБ — иначе сборка будет вылетать или тормозить." Yellow
        if ($IsWin) {
            try {
                $total = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
                if ($total -lt ($ram + 2) * 1GB) {
                    Say ("На этом компьютере всего {0:N0} ГБ памяти — для сборки маловато, возможны вылеты." -f ($total / 1GB)) Yellow
                }
            } catch { }
        }
    }
    Say 'Чтобы обновить сборку, просто запусти этот файл ещё раз — скачается только то, что изменилось.'
    if ($IsWin -and -not (Get-MinecraftProcesses).Launcher.Count) { Start-TLauncher $gameDir }
}

$logPath = Join-Path ([System.IO.Path]::GetTempPath()) 'mcsc-installer.log'
try { Start-Transcript -Path $logPath -Force | Out-Null } catch { }
try {
    Install-Pack
} catch {
    Write-Host ''
    Say "ОШИБКА: $($_.Exception.Message)" Red
    if ($script:TLauncherClosed) { Start-TLauncher '' }
    Say "Журнал установки: $logPath" Yellow
    if ($script:TempDir) { Say "Временные файлы: $($script:TempDir)" Yellow }
    Say 'Пришли журнал администратору сервера.' Yellow
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
