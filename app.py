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
from util import (IS_WINDOWS, expand, extract_icons, first_existing, folder_size, gb,
                  ps_json, run_ps, running_blockers)

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
        "Select DisplayName, DisplayVersion, InstallLocation, DisplayIcon,"
        "@{n='SizeMB';e={[math]::Round($_.EstimatedSize/1024,0)}} | ConvertTo-Json -Compress"
    )
    # Реестр врёт: если известен InstallLocation — берём реальный размер папки
    for p in programs:
        loc = p.get("InstallLocation")
        if loc and os.path.isdir(loc):
            p["SizeMB"] = round(folder_size(loc, 10) / 1024 ** 2)
    programs = [p for p in programs if p.get("SizeMB", 0) > 300]
    for p in programs:
        m = re.match(r'^"?([^",]+\.(?:exe|ico))', p.get("DisplayIcon") or "", re.I)
        p["icon_src"] = m.group(1) if m else None
    return programs


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


def link_temp_parents(data):
    """Привязывает остатки установщиков к пункту Temp, в размер которого они входят."""
    for t in data["temp_items"]:
        parent = os.path.normcase(os.path.dirname(t["path"]))
        t["parent_id"] = next(
            (i["id"] for i in data["safe"]
             if os.path.normcase(i["resolved"]) == parent
             or os.path.normcase(os.path.realpath(i["resolved"])) == os.path.normcase(os.path.realpath(parent))),
            "local_temp" if data["mock"] else None)


def attach_icons(data):
    """Иконки приложений: для пунктов каталога, программ и установок Python."""
    wanted = {}
    for i in data["safe"] + data["review"]:
        i["icon_exe"] = first_existing(i.get("icon_src"))
        wanted[id(i)] = i["icon_exe"]
    for p in data["programs"]:
        p["icon_exe"] = p.get("icon_src")
    for p in data["python"]:
        p["icon_exe"] = os.path.join(p["path"], "python.exe")
    paths = [i["icon_exe"] for i in data["safe"] + data["review"] + data["programs"] + data["python"]]
    icons = extract_icons(paths)
    for i in data["safe"] + data["review"] + data["programs"] + data["python"]:
        i["icon_img"] = icons.get(i.get("icon_exe"))


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

        data["safe"] = [i for i in found if catalog.ZONE[i["id"]] == "safe" and i["exists"]]
        data["review"] = [i for i in found if catalog.ZONE[i["id"]] == "review" and i["exists"]]
        link_temp_parents(data)
        if not mock:
            set_state(progress=98, message="Загружаю иконки приложений…")
            attach_icons(data)

        by_size = lambda i: -i["size_gb"]
        data["safe"].sort(key=by_size)
        data["review"].sort(key=by_size)
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


# ───────────────────────────────── строки отчёта ─────────────────────────────────

def build_rows(d):
    """Единый список строк таблицы: A — безопасно, B — на усмотрение, C — только вручную."""
    rows = []

    def row(i, cat, kind):
        rows.append(dict(
            id=i["id"], name=i["name"], path=i.get("resolved") or i.get("path"), size_gb=i["size_gb"],
            cat=cat, kind=kind, reason=i["desc"], restore=i.get("restore", ""),
            deletable=bool(i.get("deletable")) and not d.get("readonly"),
            icon=i.get("icon", "📁"), img=i.get("icon_img"), parent_id=i.get("parent_id")))

    for i in d["safe"]:
        row(i, "A", "static")
    for i in d["temp_items"]:
        row(i, "A", "temp")
    for i in d["review"]:
        row(i, "B" if i.get("deletable") else "C", "static")
    rows = [r for r in rows if r["size_gb"] > 0]
    rows.sort(key=lambda r: -r["size_gb"])
    return rows


# ───────────────────────────────── маршруты ─────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html", catalog=catalog, history=list_history(), active="home")


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
        d = dict(scan_data)
        rows = build_rows(d)
    return render_template("report.html", d=d, rows=rows, active="report")


@app.get("/export")
def export():
    with _lock:
        if not scan_data:
            return redirect("/")
        body = json.dumps(public_data(scan_data), ensure_ascii=False, indent=2)
    fname = time.strftime("report_%Y%m%d_%H%M%S.json")
    return app.response_class(body, mimetype="application/json",
                              headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/history")
def history_list():
    return render_template("history.html", history=list_history(HISTORY_KEEP), active="history")


@app.get("/history/<name>")
def history(name):
    if not HISTORY_RE.match(name):
        return err("Неверное имя", 404)
    try:
        with open(os.path.join(SCANS_DIR, name), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return redirect("/history")
    d.update(dynamic={}, readonly=True)  # старый отчёт — только просмотр
    with _lock:
        scan_data.clear()
        scan_data.update(d)
    return redirect("/report")


def find_item(zone_list, item_id):
    return next((i for i in zone_list if i["id"] == item_id), None)


def perform_delete(item_id):
    """Удаляет один пункт. Возвращает (payload, http_code)."""
    def fail(msg, code):
        return {"ok": False, "id": item_id, "error": msg}, code

    with _lock:
        if scan_data.get("readonly"):
            return fail("Это сохранённый отчёт — он только для просмотра", 403)
        dyn = scan_data.get("dynamic", {}).get(item_id)
        mock = scan_data.get("mock", False)

    if item_id in catalog.DELETABLE_IDS:
        kind, item = "static", catalog.ALL_ITEMS[item_id]
        blockers = item["blockers"] + catalog.GLOBAL_BLOCKERS
    elif dyn:
        kind, item = dyn["type"], dyn
        blockers = (["vs_installer", "devenv"] + catalog.GLOBAL_BLOCKERS) if kind == "temp" else []
    else:
        return fail("Этот пункт нельзя удалять через приложение", 403)

    busy = running_blockers(blockers)
    if busy:
        return fail("Сначала закройте: " + ", ".join(busy), 409)

    freed = remaining = 0.0
    group = None
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
                return fail("Папка изменилась или больше не подходит под правила — пересканируйте", 409)
            freed, remaining = delete_item({"path": item["path"], "kind": "folder"})
    else:  # dup
        with _lock:
            group = next((g for g in scan_data["dups"] if g["hash"] == item["group"]), None)
        if not group:
            return fail("Группа дубликатов не найдена", 404)
        if mock:
            freed = group["size_gb"]
        else:
            siblings = [f["path"] for f in group["files"]]
            if not scanners.verify_duplicate(item["path"], siblings):
                return fail("Нельзя удалить: не найдена идентичная копия, которая останется на диске", 409)
            try:
                size = os.path.getsize(item["path"])
                os.remove(item["path"])
            except OSError as e:
                return fail(f"Не удалось удалить файл: {e}", 500)
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
            for i in d["safe"]:  # размер Temp уменьшился на освобождённое
                if i["id"] == t.get("parent_id"):
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
    return {"ok": True, "id": item_id, "freed_gb": freed, "kind": kind,
            "remaining_gb": remaining}, 200


@app.post("/delete")
def delete():
    item_id = (request.get_json(silent=True) or {}).get("id")
    payload, code = perform_delete(item_id)
    if payload["ok"]:
        payload["reload"] = payload["kind"] == "dup"
    else:
        payload["error"] = payload.get("error")
    return jsonify(payload), code


@app.post("/delete_batch")
def delete_batch():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 200:
        return err("Нужен непустой список id", 400)
    results, seen = [], set()
    # сначала остатки Temp, потом сам Temp: так «родитель» не успеет удалить «детей» из-под ног
    ordered = sorted((i for i in ids if isinstance(i, str)), key=lambda i: not i.startswith("tmp_"))
    for item_id in ordered:
        if item_id in seen:
            continue
        seen.add(item_id)
        payload, _ = perform_delete(item_id)
        results.append(payload)
    freed = round(sum(r.get("freed_gb", 0) for r in results if r["ok"]), 2)
    return jsonify(ok=True, results=results, freed_gb=freed,
                   failed=[r for r in results if not r["ok"]])


@app.post("/open")
def open_location():
    """Показывает папку/файл в проводнике. Путь берётся только из каталога или отчёта."""
    item_id = (request.get_json(silent=True) or {}).get("id")
    path = None
    with _lock:
        for i in scan_data.get("safe", []) + scan_data.get("review", []) + scan_data.get("temp_items", []):
            if i["id"] == item_id:
                path = i.get("resolved") or i.get("path")
        dyn = scan_data.get("dynamic", {}).get(item_id)
        if dyn:
            path = dyn["path"]
    if not path:
        return err("Неизвестный пункт", 404)
    if not IS_WINDOWS:
        return jsonify(ok=True, demo=True)
    try:
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        elif os.path.isdir(path):
            os.startfile(path)  # noqa: S606 — путь из белого списка
        else:
            return err("Папка уже не существует", 404)
    except OSError as e:
        return err(str(e), 500)
    return jsonify(ok=True)


# ─────────────────────────────── запуск в окне ───────────────────────────────

def free_port(preferred=PORT):
    import socket
    for p in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind((HOST, p))
                return s.getsockname()[1]
            except OSError:
                continue


def main():
    """Flask в фоновом потоке + нативное окно (pywebview). Без pywebview — браузер."""
    from werkzeug.serving import make_server
    port = free_port()
    server = make_server(HOST, port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{HOST}:{port}"

    if "--browser" not in sys.argv:
        try:
            import webview
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window("PC Cleaner", url, width=1360, height=860, min_size=(1000, 640))
            webview.start()  # блокирует до закрытия окна
            server.shutdown()
            return
        except ImportError:
            print("pywebview не установлен — открываю в браузере (pip install pywebview)")
        except Exception as e:  # noqa: BLE001 — нет WebView2 и т.п.
            print(f"Не удалось открыть окно ({e}) — открываю в браузере")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    print(f"PC Cleaner: {url}  (Ctrl+C — остановить)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
