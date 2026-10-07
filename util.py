"""Общие помощники: PowerShell, размеры папок, проверка процессов."""
import json
import os
import re
import shutil
import subprocess
import time

IS_WINDOWS = os.name == "nt"
SIZE_TIMEOUT = 45  # сек на замер одной папки — защита от зависания на гигантских деревьях


def run_ps(command, timeout=60, env=None):
    """Выполняет PowerShell-команду. Возвращает (stdout, stderr)."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return "", "PowerShell not found"
    try:
        r = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            env={**os.environ, **env} if env else None,
        )
        return r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except OSError as e:
        return "", str(e)


def ps_json(command, timeout=60):
    out, _ = run_ps(command, timeout)
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def expand(path):
    return os.path.expandvars(path)


def folder_size_ex(path, deadline=SIZE_TIMEOUT):
    """Размер папки в байтах и флаг «замер оборвался по времени». Не следует по симлинкам/junction,
    глотает ошибки доступа."""
    total, stop, cut = 0, time.monotonic() + deadline, False
    stack = [lp(path)]
    while stack:
        if time.monotonic() > stop:
            cut = True
            break
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total, cut


def folder_size(path, deadline=SIZE_TIMEOUT):
    return folder_size_ex(path, deadline)[0]


def gb(nbytes):
    return round(nbytes / 1024 ** 3, 2)


def running_names():
    """Имена всех запущенных процессов (нижний регистр, без .exe) — одним вызовом PowerShell."""
    if not IS_WINDOWS:
        return set()
    out, _ = run_ps("Get-Process -EA SilentlyContinue | Select-Object -ExpandProperty Name -Unique | ConvertTo-Json -Compress")
    try:
        data = json.loads(out) if out else []
    except json.JSONDecodeError:
        return set()
    return {n.lower() for n in ([data] if isinstance(data, str) else data)}


def running_blockers(names, running=None):
    """Какие из процессов-блокировщиков сейчас запущены. running можно передать готовый
    (пакетное удаление спрашивает систему один раз, а не на каждый пункт)."""
    running = running_names() if running is None else running
    return sorted({n for n in names if n.lower() in running})


def lp(path):
    """Префикс длинных путей Windows (\\\\?\\): иначе node_modules глубже 260 символов не удалить."""
    if IS_WINDOWS and path and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def drive_of(path, default="C"):
    m = re.match(r"^([A-Za-z]):", path or "")
    return m.group(1).upper() if m else default


def system_drive():
    return (os.environ.get("SystemDrive") or "C:")[:1].upper()


def list_drives():
    """Диски системы. Type: local / removable / network. Сканировать можно local и removable."""
    rows = ps_json("Get-CimInstance Win32_LogicalDisk | Where-Object { $_.Size } | "
                   "Select DeviceID,DriveType,VolumeName,Size,FreeSpace | ConvertTo-Json -Compress")
    kinds = {2: "removable", 3: "local", 4: "network"}
    drives = []
    for r in rows:
        total, free = r["Size"] / 1024 ** 3, r["FreeSpace"] / 1024 ** 3
        if r["DriveType"] not in kinds:
            continue
        drives.append({
            "Name": r["DeviceID"][:1].upper(), "Label": r.get("VolumeName") or "", "Type": kinds[r["DriveType"]],
            "UsedGB": round(total - free, 1), "FreeGB": round(free, 1), "TotalGB": round(total, 1),
            "Pct": round((total - free) / total * 100) if total else 0,
            "scannable": r["DriveType"] in (2, 3)})
    return drives


def extract_icons(paths):
    """Иконки exe-файлов → {путь: data-URI PNG}. Один вызов PowerShell на все пути."""
    paths = sorted({p for p in paths if p and os.path.isfile(p)})
    if not paths or not IS_WINDOWS:
        return {}
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        "$paths = $env:PC_ICON_PATHS | ConvertFrom-Json;"
        "$out = foreach ($p in $paths) { try {"
        "$i=[System.Drawing.Icon]::ExtractAssociatedIcon($p); $ms=New-Object IO.MemoryStream;"
        "$i.ToBitmap().Save($ms,[System.Drawing.Imaging.ImageFormat]::Png);"
        "[pscustomobject]@{p=$p;d=[Convert]::ToBase64String($ms.ToArray())} } catch {} };"
        "@($out) | ConvertTo-Json -Compress"
    )
    out, _ = run_ps(script, timeout=60, env={"PC_ICON_PATHS": json.dumps(paths)})
    try:
        data = json.loads(out) if out else []
    except json.JSONDecodeError:
        return {}
    data = [data] if isinstance(data, dict) else data
    return {r["p"]: "data:image/png;base64," + r["d"] for r in data if r and r.get("d")}


def first_existing(patterns):
    """Первый существующий путь из списка шаблонов (с переменными окружения и *)."""
    import glob
    for pat in patterns or []:
        hits = sorted(glob.glob(os.path.expandvars(pat)))
        if hits:
            return hits[-1]
    return None
