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


def is_reparse(path):
    """Junction/symlink: в такие точки каталожных шаблонов не заходим."""
    try:
        return os.path.islink(path) or bool(os.lstat(path).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


def expand_all(patterns):
    """Существующие папки по шаблонам каталога: переменные окружения и `*` (например, все профили браузера).
    Ссылки и неразвёрнутые переменные пропускаем; дубли убираем."""
    import glob
    out, seen = [], set()
    for pat in patterns:
        for p in sorted(glob.glob(os.path.expandvars(pat).replace("\\", os.sep))):
            key = os.path.normcase(p)
            if "%" in p or key in seen or not os.path.isdir(p) or is_reparse(p):
                continue
            seen.add(key)
            out.append(p)
    # вложенные пути (GPUCache внутри ShaderCache) не считаем и не удаляем дважды
    norm = [os.path.normcase(p) + os.sep for p in out]
    return [p for p, n in zip(out, norm) if not any(n != o and n.startswith(o) for o in norm)]


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


def drive_media():
    """{буква: 'SSD'|'HDD'}. Тип носителя определяет, сколько потоков можно пускать (на HDD много потоков
    дают лишние перемещения головки) и насколько долгим будет скан. Не вышло определить — пусто."""
    rows = ps_json("$m=@{}; Get-PhysicalDisk | ForEach-Object { $m[[string]$_.DeviceId]=[string]$_.MediaType }; "
                   "Get-Partition | Where-Object DriveLetter | ForEach-Object { [pscustomobject]@{L=[string]$_.DriveLetter; "
                   "M=$m[[string]$_.DiskNumber]} } | ConvertTo-Json -Compress", timeout=30)
    names = {"SSD": "SSD", "HDD": "HDD"}
    return {r["L"].upper(): names[r["M"]] for r in rows if isinstance(r, dict) and r.get("L") and r.get("M") in names}


def list_drives():
    """Диски системы. Type: local / removable / network. Сканировать можно local и removable."""
    rows = ps_json("Get-CimInstance Win32_LogicalDisk | Where-Object { $_.Size } | "
                   "Select DeviceID,DriveType,VolumeName,Size,FreeSpace | ConvertTo-Json -Compress")
    kinds = {2: "removable", 3: "local", 4: "network"}
    media = drive_media()
    drives = []
    for r in rows:
        total, free = r["Size"] / 1024 ** 3, r["FreeSpace"] / 1024 ** 3
        if r["DriveType"] not in kinds:
            continue
        drives.append({
            "Name": r["DeviceID"][:1].upper(), "Label": r.get("VolumeName") or "", "Type": kinds[r["DriveType"]],
            "UsedGB": round(total - free, 1), "FreeGB": round(free, 1), "TotalGB": round(total, 1),
            "Pct": round((total - free) / total * 100) if total else 0,
            "scannable": r["DriveType"] in (2, 3),
            "Media": media.get(r["DeviceID"][:1].upper(), "")})
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


def _rm(path):
    """Удаляет один файл. Снимает атрибут «только чтение»; занятый/защищённый файл — не ошибка."""
    try:
        os.remove(lp(path))
        return True
    except FileNotFoundError:
        return True
    except OSError:
        try:
            os.chmod(lp(path), 0o700)
            os.remove(lp(path))
            return True
        except OSError:
            return False


def purge(path, remove_root=True, collect=None):
    """Удаляет папку целиком, но то, что занято программами или требует прав, пропускает.
    Возвращает число пропущенных файлов; их пути (образцы) складывает в collect."""
    skipped = 0
    for dirpath, dirs, files in os.walk(lp(path), topdown=False):
        for f in files:
            p = os.path.join(dirpath, f)
            if not _rm(p):
                skipped += 1
                if collect is not None and len(collect) < 300:  # образцы для поиска «кто держит файл»
                    collect.append(p[4:] if p.startswith("\\\\?\\") else p)
        for d in dirs:
            p = os.path.join(dirpath, d)
            try:
                if os.path.islink(p):
                    os.unlink(p) if not os.path.isdir(p) else os.rmdir(p)  # ссылку убираем, цель не трогаем
                else:
                    os.rmdir(p)  # не пустая (внутри пропущенные файлы) — это уже посчитано выше
            except OSError:
                pass
    if remove_root:
        try:
            os.rmdir(lp(path))
        except OSError:
            pass
    return skipped


def is_admin():
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# ───────────────────── кто держит файл (Windows Restart Manager) ─────────────────────

PROTECTED_PROCS = {"system", "registry", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "svchost",
                   "dwm", "explorer", "fontdrvhost", "sihost", "taskhostw", "ctfmon", "searchhost", "searchindexer",
                   "runtimebroker", "audiodg", "wuauserv", "msmpeng", "securityhealthservice"}


def find_lockers(paths):
    """Какие процессы держат указанные файлы. Windows Restart Manager — штатный способ,
    им же пользуются установщики. Возвращает [{pid, app, kind}]; вне Windows — пусто."""
    if not IS_WINDOWS or not paths:
        return []
    import ctypes
    from ctypes import wintypes
    rm = ctypes.WinDLL("rstrtmgr")

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("pid", wintypes.DWORD), ("start", FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [("Process", RM_UNIQUE_PROCESS), ("app", ctypes.c_wchar * 256), ("service", ctypes.c_wchar * 64),
                    ("kind", ctypes.c_int), ("status", ctypes.c_ulong), ("session", wintypes.DWORD),
                    ("restartable", wintypes.BOOL)]

    session, key = wintypes.DWORD(0), ctypes.create_unicode_buffer(33)
    if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return []
    try:
        files = (ctypes.c_wchar_p * len(paths))(*paths)
        if rm.RmRegisterResources(session, len(paths), files, 0, None, 0, None) != 0:
            return []
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        r = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
        if r == 0 or not needed.value:
            return []
        if r != 234:  # ERROR_MORE_DATA — штатный ответ «дайте буфер побольше»
            return []
        infos = (RM_PROCESS_INFO * needed.value)()
        count = wintypes.UINT(needed.value)
        if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)) != 0:
            return []
        return [{"pid": infos[i].Process.pid, "app": infos[i].app or infos[i].service, "kind": infos[i].kind}
                for i in range(count.value)]
    except Exception:  # noqa: BLE001 — определить не вышло, это не причина падать
        return []
    finally:
        rm.RmEndSession(session)


def describe_lockers(raw):
    """Дополняет список именами процессов и помечает те, которые закрывать из приложения нельзя."""
    if not raw:
        return []
    ids = ",".join(str(p["pid"]) for p in raw)
    names = {r["Id"]: (r.get("ProcessName") or "") for r in ps_json(
        f"Get-Process -Id {ids} -EA SilentlyContinue | Select Id,ProcessName | ConvertTo-Json -Compress")}
    own = {os.getpid(), os.getppid()}
    out, seen = [], set()
    for p in raw:
        if p["pid"] in seen:
            continue
        seen.add(p["pid"])
        proc = names.get(p["pid"], "")
        why = ("это само приложение" if p["pid"] in own else
               "системный процесс" if proc.lower() in PROTECTED_PROCS or p["kind"] in (3, 4, 1000) else "")
        out.append({"pid": p["pid"], "app": p["app"] or proc, "proc": proc, "protected": bool(why), "why": why})
    return out


def wait_exit(pids, timeout=6.0):
    """Ждёт завершения процессов. Возвращает те, что всё ещё работают."""
    if not IS_WINDOWS:
        return []
    import ctypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    alive, stop = [], time.monotonic() + timeout
    for pid in pids:
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            continue  # процесса уже нет
        left = max(int((stop - time.monotonic()) * 1000), 0)
        if k.WaitForSingleObject(h, left) != 0:
            alive.append(pid)
        k.CloseHandle(ctypes.c_void_p(h))
    return alive


def close_processes(pids, force=False):
    """Просит программы закрыться (taskkill без /F: как нажатие на крестик). С force — завершает принудительно.
    Возвращает pid, которые остались работать."""
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(int(pid))] + (["/F"] if force else []),
                       capture_output=True, timeout=15)
    return wait_exit(pids, 2.0 if force else 8.0)


def process_names(pids):
    if not pids:
        return {}
    ids = ",".join(str(int(p)) for p in pids)
    return {r["Id"]: (r.get("ProcessName") or "").lower() for r in ps_json(
        f"Get-Process -Id {ids} -EA SilentlyContinue | Select Id,ProcessName | ConvertTo-Json -Compress")}
