"""PC Cleaner — Flask-приложение: сканирует известные места с мусором на Windows,
объясняет находки и удаляет по белому списку. Всё работает локально."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request

import catalog
import scanners
from util import (IS_WINDOWS, expand, folder_size, gb, ps_json, run_ps,
                  running_blockers)

app = Flask(__name__)

HOST, PORT = "127.0.0.1", 5000
SCANS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scans")
HISTORY_KEEP = 20
HISTORY_RE = re.compile(r"^scan_\d{8}_\d{6}\.json$")

_lock = threading.Lock()
scan_state = {"status": "idle", "progress": 0, "message": ""}
scan_data = {}


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
    add_pct(drives)
    return drives


def add_pct(drives):
    for d in drives:
        d["Pct"] = round(d["UsedGB"] / d["TotalGB"] * 100) if d.get("TotalGB") else 0


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


def compute_totals(d):
    d["safe_gb"] = round(sum(i["size_gb"] for i in d["safe"]), 2)
    # дубликаты — решение пользователя, поэтому идут в «на усмотрение»;
    # остатки Temp уже входят в размер самого Temp и отдельно не суммируются
    d["review_gb"] = round(sum(i["size_gb"] for i in d["review"])
                           + sum(g["wasted_gb"] for g in d["dups"]), 2)
    d["total_gb"] = round(d["safe_gb"] + d["review_gb"], 2)


def mock_extras(data):
    """Демо-данные для умного Temp, Python и дубликатов + реестр динамических id."""
    dyn = data["dynamic"]
    for t in catalog.MOCK["smart_temp"]:
        item = dict(id=scanners.short_id("tmp_", t["path"]), name=t["name"], icon="📁", path=t["path"],
                    resolved=t["path"], kind="folder", deletable=True, size_gb=t["size_gb"],
                    age_days=t["age_days"], desc=f'{t["reason"]} Не изменялась {t["age_days"]} дн.',
                    restore="Ничего: если установщик понадобится, он распакуется заново.")
        data["temp_items"].append(item)
        dyn[item["id"]] = {"type": "temp", "path": t["path"]}
    for g in catalog.MOCK["dups"]:
        group = {"hash": scanners.short_id("grp_", g["files"][0]["path"]), "size_gb": g["size_gb"],
                 "wasted_gb": g["wasted_gb"], "files": []}
        for f in g["files"]:
            fid = scanners.short_id("dup_", f["path"])
            group["files"].append({**f, "id": fid})
            dyn[fid] = {"type": "dup", "path": f["path"], "group": group["hash"]}
        data["dups"].append(group)
    data["python"] = [dict(p) for p in catalog.MOCK["python"]]


def register_dynamic(data):
    dyn = data["dynamic"]
    for t in data["temp_items"]:
        dyn[t["id"]] = {"type": "temp", "path": t["path"]}
    for g in data["dups"]:
        for f in g["files"]:
            dyn[f["id"]] = {"type": "dup", "path": f["path"], "group": g["hash"]}


def do_scan():
    try:
        mock = not IS_WINDOWS
        set_state(status="scanning", progress=2, message="Определяю диски…")
        drives = scan_drives() if IS_WINDOWS else []

        items, found, seen = catalog.SAFE + catalog.REVIEW, [], set()
        for n, item in enumerate(items):
            set_state(progress=5 + int(60 * n / len(items)), message=f"Замеряю: {item['name']}")
            it = scan_item(item)
            key = os.path.normcase(os.path.realpath(it["resolved"]))
            if key in seen:  # %TEMP% и %LOCALAPPDATA%\Temp — обычно одна папка, не считаем дважды
                continue
            seen.add(key)
            found.append(it)

        data = {"drives": drives, "programs": [], "python": [], "dups": [], "temp_items": [],
                "dynamic": {}, "protected": catalog.DO_NOT_TOUCH, "mock": mock, "readonly": False,
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")}

        if mock:
            set_state(progress=70, message="Windows не обнаружена — показываю демо-данные")
            data["drives"] = [dict(d) for d in catalog.MOCK["drives"]]
            add_pct(data["drives"])
            for i in found:
                i["size_gb"] = catalog.MOCK["sizes"].get(i["id"], 0)
                i["exists"] = i["size_gb"] > 0
            data["programs"] = list(catalog.MOCK["programs"])
            mock_extras(data)
        else:
            set_state(progress=68, message="Ищу остатки установщиков в Temp…")
            data["temp_items"] = scanners.scan_smart_temp()
            set_state(progress=74, message="Читаю список установленных программ…")
            data["programs"] = scan_programs()
            set_state(progress=80, message="Проверяю установки Python…")
            data["python"] = scanners.scan_python()
            set_state(progress=86, message="Ищу дубликаты в Загрузках и Документах…")
            data["dups"] = scanners.scan_duplicates(
                progress=lambda n, t: set_state(progress=86 + int(12 * n / max(t, 1))))
            register_dynamic(data)

        by_size = lambda i: -i["size_gb"]
        data["safe"] = sorted((i for i in found if catalog.ZONE[i["id"]] == "safe" and i["exists"]), key=by_size)
        data["review"] = sorted((i for i in found if catalog.ZONE[i["id"]] == "review" and i["exists"]), key=by_size)
        compute_totals(data)
        c = next((d for d in data["drives"] if d["Name"].upper() == "C"),
                 data["drives"][0] if data["drives"] else None)
        data["free_c"] = c["FreeGB"] if c else None

        save_history(data)
        with _lock:
            scan_data.clear()
            scan_data.update(data)
        set_state(status="done", progress=100, message="Готово")
    except Exception as e:  # noqa: BLE001 — поток не должен падать молча
        set_state(status="error", message=f"Ошибка сканирования: {e}")


# ───────────────────────────── история и экспорт ─────────────────────────────

def public_data(d):
    """Данные отчёта без служебного реестра динамических id."""
    return {k: v for k, v in d.items() if k not in ("dynamic", "readonly")}


def save_history(data):
    try:
        os.makedirs(SCANS_DIR, exist_ok=True)
        name = time.strftime("scan_%Y%m%d_%H%M%S.json")
        with open(os.path.join(SCANS_DIR, name), "w", encoding="utf-8") as f:
            json.dump(public_data(data), f, ensure_ascii=False)
        for old in sorted(f for f in os.listdir(SCANS_DIR) if HISTORY_RE.match(f))[:-HISTORY_KEEP]:
            os.remove(os.path.join(SCANS_DIR, old))
    except OSError:
        pass  # история — удобство, не причина ронять скан


def list_history(limit=3):
    if not os.path.isdir(SCANS_DIR):
        return []
    rows = []
    for name in sorted((f for f in os.listdir(SCANS_DIR) if HISTORY_RE.match(f)), reverse=True)[:limit]:
        try:
            with open(os.path.join(SCANS_DIR, name), encoding="utf-8") as f:
                d = json.load(f)
            rows.append({"name": name, "scanned_at": d.get("scanned_at"), "total_gb": d.get("total_gb"),
                         "free_c": d.get("free_c"), "mock": d.get("mock")})
        except (OSError, ValueError):
            continue
    return rows


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


def err(msg, code):
    return jsonify(ok=False, error=msg), code


# ───────────────────────────────── маршруты ─────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html", catalog=catalog, history=list_history())


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


@app.get("/export")
def export():
    with _lock:
        if not scan_data:
            return redirect("/")
        body = json.dumps(public_data(scan_data), ensure_ascii=False, indent=2)
    fname = time.strftime("report_%Y%m%d_%H%M%S.json")
    return app.response_class(body, mimetype="application/json",
                              headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/history/<name>")
def history(name):
    if not HISTORY_RE.match(name):
        return err("Неверное имя", 404)
    try:
        with open(os.path.join(SCANS_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return redirect("/")
    d.update(dynamic={}, readonly=True)  # старый отчёт — только просмотр
    with _lock:
        scan_data.clear()
        scan_data.update(d)
    return redirect("/report")


def find_item(zone_list, item_id):
    return next((i for i in zone_list if i["id"] == item_id), None)


@app.post("/delete")
def delete():
    item_id = (request.get_json(silent=True) or {}).get("id")
    with _lock:
        if scan_data.get("readonly"):
            return err("Это сохранённый отчёт — он только для просмотра", 403)
        dyn = scan_data.get("dynamic", {}).get(item_id)
        mock = scan_data.get("mock", False)

    if item_id in catalog.DELETABLE_IDS:
        kind, item = "static", catalog.ALL_ITEMS[item_id]
        blockers = item["blockers"] + catalog.GLOBAL_BLOCKERS
    elif dyn:
        kind, item = dyn["type"], dyn
        blockers = (["vs_installer", "devenv"] + catalog.GLOBAL_BLOCKERS) if kind == "temp" else []
    else:
        return err("Этот пункт нельзя удалять через приложение", 403)

    busy = running_blockers(blockers)
    if busy:
        return err("Сначала закройте: " + ", ".join(busy), 409)

    freed = remaining = 0.0
    if kind == "static":
        if mock:
            freed = next((i["size_gb"] for i in scan_data["safe"] + scan_data["review"] if i["id"] == item_id), 0)
        else:
            freed, remaining = delete_item(item)
    elif kind == "temp":
        if mock:
            freed = find_item(scan_data["temp_items"], item_id)["size_gb"]
        else:
            if not scanners.verify_smart_temp(item["path"]):
                return err("Папка изменилась или больше не подходит под правила — пересканируйте", 409)
            freed, remaining = delete_item({"path": item["path"], "kind": "folder"})
    else:  # dup
        with _lock:
            group = next((g for g in scan_data["dups"] if g["hash"] == item["group"]), None)
        if not group:
            return err("Группа дубликатов не найдена", 404)
        if mock:
            freed = group["size_gb"]
        else:
            siblings = [f["path"] for f in group["files"]]
            if not scanners.verify_duplicate(item["path"], siblings):
                return err("Нельзя удалить: не найдена идентичная копия, которая останется на диске", 409)
            try:
                size = os.path.getsize(item["path"])
                os.remove(item["path"])
            except OSError as e:
                return err(f"Не удалось удалить файл: {e}", 500)
            freed = gb(size)

    with _lock:
        d = scan_data
        if kind == "static":
            for i in d["safe"] + d["review"]:
                if i["id"] == item_id:
                    i["size_gb"] = remaining
        elif kind == "temp":
            t = find_item(d["temp_items"], item_id)
            t["size_gb"] = remaining
            parent = os.path.normcase(os.path.dirname(t["path"]))
            for i in d["safe"]:  # размер Temp уменьшился на освобождённое
                if os.path.normcase(os.path.realpath(i.get("resolved", ""))) == parent \
                        or os.path.normcase(i.get("resolved", "")) == parent:
                    i["size_gb"] = round(max(i["size_gb"] - freed, 0), 2)
        else:
            group["files"] = [f for f in group["files"] if f["id"] != item_id]
            d["dynamic"].pop(item_id, None)
            group["wasted_gb"] = round(group["size_gb"] * (len(group["files"]) - 1), 2)
            if len(group["files"]) < 2:
                for f in group["files"]:
                    d["dynamic"].pop(f["id"], None)  # последняя копия больше не удаляема
                d["dups"].remove(group)
        compute_totals(d)
        totals = {k: d[k] for k in ("safe_gb", "review_gb", "total_gb")}
    return jsonify(ok=True, freed_gb=freed, reload=(kind == "dup"), **totals)


if __name__ == "__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"PC Cleaner: http://localhost:{PORT}  (Ctrl+C — остановить)")
    app.run(host=HOST, port=PORT, debug=False)
