"""PC Cleaner — Flask-приложение: сканирует известные места с мусором на Windows,
объясняет находки и удаляет по белому списку. Всё работает локально."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request

import catalog

app = Flask(__name__)

HOST, PORT = "127.0.0.1", 5000
SIZE_TIMEOUT = 45  # сек на замер одной папки — защита от зависания на гигантских деревьях
IS_WINDOWS = os.name == "nt"

_lock = threading.Lock()
scan_state = {"status": "idle", "progress": 0, "message": ""}
scan_data = {}


# ───────────────────────── низкоуровневые помощники ─────────────────────────

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


# ─────────────────────────────── сканирование ───────────────────────────────

def set_state(**kw):
    with _lock:
        scan_state.update(kw)


def scan_drives():
    drives = ps_json(
        "Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | "
        "Select Name,"
        "@{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}},"
        "@{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}},"
        "@{n='TotalGB';e={[math]::Round(($_.Used+$_.Free)/1GB,1)}} | ConvertTo-Json -Compress"
    )
    for d in drives:
        d["Pct"] = round(d["UsedGB"] / d["TotalGB"] * 100) if d.get("TotalGB") else 0
    return drives


def scan_programs():
    programs = ps_json(
        "$keys='HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*';"
        "Get-ItemProperty $keys -EA SilentlyContinue | "
        "Where-Object { $_.DisplayName -and $_.EstimatedSize -gt 300000 } | "
        "Sort-Object EstimatedSize -Descending | Select-Object -First 12 | "
        "Select DisplayName, DisplayVersion, InstallLocation,"
        "@{n='SizeMB';e={[math]::Round($_.EstimatedSize/1024,0)}} | ConvertTo-Json -Compress"
    )
    # Реестр врёт: если известен InstallLocation — берём реальный размер папки
    for p in programs:
        loc = p.get("InstallLocation")
        if loc and os.path.isdir(loc):
            p["SizeMB"] = round(folder_size(loc, 10) / 1024 ** 2)
    return [p for p in programs if p.get("SizeMB", 0) > 300]


def scan_item(item):
    path = expand(item["path"])
    size = folder_size(path) if os.path.isdir(path) else 0
    return {**item, "resolved": path, "exists": os.path.isdir(path), "size_gb": gb(size)}


def do_scan():
    try:
        set_state(status="scanning", progress=2, message="Определяю диски…")
        drives = scan_drives() if IS_WINDOWS else []

        items = catalog.SAFE + catalog.REVIEW
        found = []
        for n, item in enumerate(items):
            set_state(progress=5 + int(80 * n / len(items)), message=f"Замеряю: {item['name']}")
            found.append(scan_item(item))

        set_state(progress=88, message="Читаю список установленных программ…")
        programs = scan_programs() if IS_WINDOWS else []

        mock = not IS_WINDOWS or all(i["size_gb"] == 0 for i in found)
        if mock:
            set_state(message="Windows не обнаружена — показываю демо-данные")
            drives = catalog.MOCK["drives"]
            for d in drives:
                d["Pct"] = round(d["UsedGB"] / d["TotalGB"] * 100)
            for i in found:
                i["size_gb"] = catalog.MOCK["sizes"].get(i["id"], 0)
                i["exists"] = i["size_gb"] > 0
            programs = catalog.MOCK["programs"]

        safe = [i for i in found if catalog.ZONE[i["id"]] == "safe" and i["exists"]]
        review = [i for i in found if catalog.ZONE[i["id"]] == "review" and i["exists"]]
        by_size = lambda i: -i["size_gb"]
        safe.sort(key=by_size)
        review.sort(key=by_size)

        data = {
            "drives": drives, "safe": safe, "review": review, "programs": programs,
            "protected": catalog.DO_NOT_TOUCH, "mock": mock,
            "safe_gb": round(sum(i["size_gb"] for i in safe), 2),
            "review_gb": round(sum(i["size_gb"] for i in review), 2),
            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        data["total_gb"] = round(data["safe_gb"] + data["review_gb"], 2)
        c = next((d for d in drives if d["Name"].upper() == "C"), drives[0] if drives else None)
        data["free_c"] = c["FreeGB"] if c else None
        with _lock:
            scan_data.clear()
            scan_data.update(data)
        set_state(status="done", progress=100, message="Готово")
    except Exception as e:  # noqa: BLE001 — поток не должен падать молча
        set_state(status="error", message=f"Ошибка сканирования: {e}")


# ─────────────────────────────── удаление ───────────────────────────────

def remove_entry(p):
    try:
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)
    except OSError:
        pass


def delete_item(item):
    """Удаляет по каталогу. Возвращает (освобождено ГБ, осталось ГБ)."""
    path = expand(item["path"])
    if not os.path.isdir(path):
        return 0.0, 0.0
    before = folder_size(path, 120)
    if item["kind"] == "contents":
        with os.scandir(path) as it:
            for e in list(it):
                remove_entry(e.path)
    else:
        shutil.rmtree(path, ignore_errors=True)
    after = folder_size(path, 120) if os.path.isdir(path) else 0
    return gb(max(before - after, 0)), gb(after)


# ───────────────────────────────── маршруты ─────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html", catalog=catalog)


@app.post("/scan")
def scan():
    with _lock:
        if scan_state["status"] == "scanning":
            return jsonify(ok=True, already=True)
        scan_state.update(status="scanning", progress=0, message="Запуск…")
    threading.Thread(target=do_scan, daemon=True).start()
    return jsonify(ok=True)


@app.get("/status")
def status():
    with _lock:
        return jsonify(scan_state)


@app.get("/report")
def report():
    with _lock:
        if not scan_data:
            return redirect("/")
        return render_template("report.html", d=dict(scan_data))


@app.post("/delete")
def delete():
    payload = request.get_json(silent=True) or {}
    item_id = payload.get("id")
    if item_id not in catalog.DELETABLE_IDS:
        return jsonify(ok=False, error="Этот пункт нельзя удалять через приложение"), 403
    item = catalog.ALL_ITEMS[item_id]

    busy = running_blockers(item["blockers"] + catalog.GLOBAL_BLOCKERS)
    if busy:
        return jsonify(ok=False, error="Сначала закройте: " + ", ".join(busy)), 409

    with _lock:
        mock = scan_data.get("mock", False)
    if mock:  # демо-режим: ничего не трогаем на диске
        freed = next((i["size_gb"] for i in scan_data.get("safe", []) + scan_data.get("review", [])
                      if i["id"] == item_id), 0)
        remaining = 0.0
    else:
        freed, remaining = delete_item(item)

    with _lock:  # обновляем отчёт, чтобы он не показывал уже удалённое
        for zone in ("safe", "review"):
            for i in scan_data.get(zone, []):
                if i["id"] == item_id:
                    i["size_gb"] = remaining
        scan_data["safe_gb"] = round(sum(i["size_gb"] for i in scan_data.get("safe", [])), 2)
        scan_data["review_gb"] = round(sum(i["size_gb"] for i in scan_data.get("review", [])), 2)
        scan_data["total_gb"] = round(scan_data["safe_gb"] + scan_data["review_gb"], 2)
    return jsonify(ok=True, freed_gb=freed, safe_gb=scan_data["safe_gb"],
                   review_gb=scan_data["review_gb"], total_gb=scan_data["total_gb"])


if __name__ == "__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"PC Cleaner: http://localhost:{PORT}  (Ctrl+C — остановить)")
    app.run(host=HOST, port=PORT, debug=False)
