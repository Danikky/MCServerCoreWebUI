#PSBEGIN
# Автоустановщик сборки для TLauncher. Этот файл — шаблон: панель подставляет
# адрес сборки и приклеивает сверху .bat-шапку (см. app/client_pack.py).
# Только синтаксис Windows PowerShell 5.1 (без ?:, ??, && из PowerShell 7).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$PackUrl = '__PACK_URL__'
$IsWin = ($env:OS -eq 'Windows_NT')
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }

function New-Client {
    $c = New-Object System.Net.WebClient
    $c.Encoding = [System.Text.Encoding]::UTF8
    $c.Headers.Add('User-Agent', 'MCServerCore-Installer/1')
    return $c
}

function Get-Sha1([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA1).Hash.ToLower()
}

# Качает во временный .part, сверяет sha1 и только потом кладёт на место —
# оборванная загрузка не оставит битый мод в папке.
function Get-RemoteFile([string]$Url, [string]$Dest, [string]$Sha1) {
    $part = "$Dest.part"
    $c = New-Client
    try { $c.DownloadFile($Url, $part) } finally { $c.Dispose() }
    if ($Sha1 -and ((Get-Sha1 $part) -ne $Sha1)) {
        Remove-Item -LiteralPath $part -Force
        throw "Файл скачался с ошибкой (не совпала контрольная сумма): $Url"
    }
    Move-Item -LiteralPath $part -Destination $Dest -Force
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
        if (Test-Path -LiteralPath $props) {
            foreach ($line in [System.IO.File]::ReadAllLines($props)) {
                if ($line -match '^\s*minecraft\.gamedir\s*=\s*(.+)$') {
                    # .properties экранирует "\" и ":" -> C\:\\Games\\mc
                    $candidates += (($Matches[1].Trim() -replace '\\\\', '\') -replace '\\:', ':')
                }
            }
        }
        $candidates += (Join-Path $env:APPDATA '.minecraft')
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

# ---- Java --------------------------------------------------------------------
# Установщик Forge/NeoForge — это .jar, ему нужна Java. Своя Java у игрока
# стоит редко, зато TLauncher качает её сам в <папка игры>\runtime — берём
# оттуда (или любую системную), самую новую из найденных.
function Get-JavaMajor([string]$Exe) {
    $release = Join-Path (Split-Path (Split-Path $Exe -Parent) -Parent) 'release'
    if (Test-Path -LiteralPath $release) {
        foreach ($line in [System.IO.File]::ReadAllLines($release)) {
            if ($line -match '^JAVA_VERSION="?(\d+)(?:\.(\d+))?') {
                $major = [int]$Matches[1]
                if ($major -eq 1 -and $Matches[2]) { $major = [int]$Matches[2] }   # "1.8.0_51" -> 8
                return $major
            }
        }
    }
    return 0
}

function Find-Java([string]$GameDir) {
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
    foreach ($exe in $found) {
        $major = Get-JavaMajor $exe
        if ($major -gt $bestMajor) { $best = $exe; $bestMajor = $major }
    }
    return $best
}

function Format-Arg([string]$Value) {
    if ($IsWin) { return '"' + $Value + '"' }
    return $Value
}

# ---- overrides.zip -----------------------------------------------------------
function Expand-Overrides([string]$ZipPath, [string]$TargetDir, [string]$Prefix) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # Личные настройки игрока (управление, графика) не затираем при обновлении
    # сборки — кладём их только если таких файлов ещё нет.
    $keepIfExists = @('options.txt', 'optionsof.txt', 'optionsshaders.txt')
    $rootFull = [System.IO.Path]::GetFullPath($TargetDir).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $written = 0
    $failed = 0
    $firstError = $null
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $zip.Entries) {
            $rel = $entry.FullName.Replace('\', '/')
            if ($Prefix) {
                if (-not $rel.StartsWith($Prefix)) { continue }
                $rel = $rel.Substring($Prefix.Length)
            }
            if (-not $rel -or $rel.EndsWith('/')) { continue }
            $dest = [System.IO.Path]::GetFullPath((Join-Path $TargetDir $rel))
            if (-not $dest.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) { continue }
            if (($keepIfExists -contains $rel.ToLower()) -and (Test-Path -LiteralPath $dest)) { continue }
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
    Say "  распаковано файлов: $written"
    if ($failed) { Say "  не удалось распаковать: $failed (первый: $firstError)" Yellow }
}

# ---- установка ---------------------------------------------------------------
function Install-Pack {
    if ($PSVersionTable.PSVersion.Major -lt 5) { throw 'Нужен PowerShell 5 или новее (Windows 10/11).' }
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
    } catch { }

    Step 'Получаю описание сборки'
    $client = New-Client
    try { $manifestText = $client.DownloadString("$PackUrl/manifest.json") } finally { $client.Dispose() }
    $manifest = $manifestText | ConvertFrom-Json
    $name = [string]$manifest.name
    $loaderId = [string]$manifest.loader.id
    Say "  сборка: $name"
    Say "  Minecraft $($manifest.loader.minecraft), загрузчик $loaderId"
    Say "  модов: $(@($manifest.mods).Count)"

    Step 'Ищу папку игры TLauncher'
    $gameDir = Find-GameDir
    Say "  $gameDir"
    $versionsDir = Join-Path $gameDir 'versions'
    $versionDir = Join-Path $versionsDir $name
    $modsDir = Join-Path $versionDir 'mods'
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('mcsc-pack-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    [System.IO.Directory]::CreateDirectory($tmp) | Out-Null
    $script:TempDir = $tmp

    # Загрузчик ставится один раз: его версия (versions\<id>\<id>.json) и
    # библиотеки остаются в папке игры и переживают обновления сборки.
    $loaderJson = Join-Path (Join-Path $versionsDir $loaderId) "$loaderId.json"
    if (Test-Path -LiteralPath $loaderJson) {
        Step "Загрузчик $loaderId уже установлен"
    } else {
        Step "Устанавливаю $loaderId (несколько минут, качает Minecraft и библиотеки)"
        $java = Find-Java $gameDir
        if (-not $java) {
            throw ('Не нашёл Java. Запусти в TLauncher один раз обычный Minecraft ' + $manifest.loader.minecraft +
                ' (лаунчер сам скачает Java), закрой игру и запусти этот установщик снова.')
        }
        Say "  Java: $java"
        $installerJar = Join-Path $tmp 'loader-installer.jar'
        Get-RemoteFile $manifest.installer.url $installerJar $manifest.installer.sha1
        # Установщик отказывается работать без launcher_profiles.json (файл
        # официального лаунчера, у TLauncher его может не быть) — подкладываем
        # пустой и убираем за собой.
        $profiles = Join-Path $gameDir 'launcher_profiles.json'
        $profilesCreated = $false
        if (-not (Test-Path -LiteralPath $profiles)) {
            [System.IO.File]::WriteAllText($profiles, '{"profiles":{}}', $Utf8NoBom)
            $profilesCreated = $true
        }
        try {
            $argList = @('-jar', (Format-Arg $installerJar), '--installClient', (Format-Arg $gameDir))
            $proc = Start-Process -FilePath $java -ArgumentList $argList -WorkingDirectory $tmp -NoNewWindow -Wait -PassThru
            $exitCode = $proc.ExitCode
        } finally {
            if ($profilesCreated -and (Test-Path -LiteralPath $profiles)) { Remove-Item -LiteralPath $profiles -Force }
        }
        if (-not (Test-Path -LiteralPath $loaderJson)) {
            throw "Установщик загрузчика завершился с ошибкой (код $exitCode). Его журнал: $tmp"
        }
    }

    # Повторный запуск того же файла = обновление: признак — наш файл состояния
    # в папке версии (пишется в конце успешной установки).
    $statePath = Join-Path $versionDir '.mcsc-pack.json'
    if (Test-Path -LiteralPath $statePath) {
        Step "Сборка «$name» уже установлена — обновляю"
    } else {
        Step "Создаю версию «$name»"
    }
    [System.IO.Directory]::CreateDirectory($modsDir) | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $versionDir "$name.json"), [string]$manifest.version_json, $Utf8NoBom)

    # Что мы ставили в прошлый раз — чтобы при обновлении удалить моды,
    # убранные из сборки, и не трогать те, что игрок добавил сам.
    $oldMods = @()
    $oldOverrides = ''
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = [System.IO.File]::ReadAllText($statePath) | ConvertFrom-Json
            $oldMods = @($state.mods)
            $oldOverrides = [string]$state.overrides_sha1
        } catch { }
    }

    Step 'Моды'
    $mods = @($manifest.mods)
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
        Get-RemoteFile $mod.url $dest $mod.sha1
        $downloaded++
    }
    Say "  скачано: $downloaded, уже было: $($mods.Count - $downloaded), удалено лишних: $removed"

    $newOverrides = ''
    if ($manifest.overrides) {
        $newOverrides = [string]$manifest.overrides.sha1
        if ($newOverrides -eq $oldOverrides) {
            Step 'Конфиги и ресурсы не менялись'
        } else {
            Step ("Конфиги и ресурсы ({0} МБ)" -f [math]::Round($manifest.overrides.size / 1MB, 1))
            $zipPath = Join-Path $tmp 'overrides.zip'
            Get-RemoteFile $manifest.overrides.url $zipPath $newOverrides
            Expand-Overrides $zipPath $versionDir ([string]$manifest.overrides.prefix)
        }
    }

    $newState = @{ pack_url = $PackUrl; loader = $loaderId; mods = @($mods | ForEach-Object { [string]$_.name }); overrides_sha1 = $newOverrides }
    [System.IO.File]::WriteAllText($statePath, ($newState | ConvertTo-Json -Depth 4), $Utf8NoBom)

    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Say "Готово! Моды сборки актуальны. Открой TLauncher (если он был открыт — перезапусти) и выбери версию «$name»." Green
    Say 'Чтобы обновить сборку, просто запусти этот файл ещё раз — скачается только то, что изменилось.'
}

$logPath = Join-Path ([System.IO.Path]::GetTempPath()) 'mcsc-installer.log'
try { Start-Transcript -Path $logPath -Force | Out-Null } catch { }
try {
    Install-Pack
} catch {
    Write-Host ''
    Say "ОШИБКА: $($_.Exception.Message)" Red
    Say "Журнал установки: $logPath" Yellow
    if ($script:TempDir) { Say "Временные файлы: $($script:TempDir)" Yellow }
    Say 'Пришли журнал администратору сервера.' Yellow
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
