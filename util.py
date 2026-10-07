"""Общие помощники: PowerShell, размеры папок, проверка процессов."""
import json
import os
import shutil
import subprocess
import time

IS_WINDOWS = os.name == "nt"
SIZE_TIMEOUT = 45  # сек на замер одной папки — защита от зависания на гигантских деревьях


def run_ps(command, timeout=60):
    """Выполняет PowerShell-команду. Возвращает (stdout, stderr)."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return "", "PowerShell not found"
    try:
        r = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
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


def folder_size(path, deadline=SIZE_TIMEOUT):
    """Размер папки в байтах. Не следует по симлинкам/junction, глотает ошибки доступа."""
    total, stop = 0, time.monotonic() + deadline
    stack = [path]
    while stack:
        if time.monotonic() > stop:
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
    return total


def gb(nbytes):
    return round(nbytes / 1024 ** 3, 2)


def running_blockers(names):
    """Какие из процессов-блокировщиков сейчас запущены."""
    names = sorted(set(names))
    if not names or not IS_WINDOWS:
        return []
    quoted = ",".join(f"'{n}'" for n in names)
    out, _ = run_ps(
        f"Get-Process -Name {quoted} -EA SilentlyContinue | "
        "Select-Object -ExpandProperty Name -Unique | ConvertTo-Json -Compress"
    )
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [data] if isinstance(data, str) else list(data)


