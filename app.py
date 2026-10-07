"""Dusty Ai — Flask-приложение в нативном окне: сканирует выбранные диски Windows,
объясняет находки и удаляет по белому списку. Всё работает локально."""
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, jsonify, redirect, render_template, request

import catalog
import scanners
from util import (IS_WINDOWS, drive_of, expand, extract_icons, first_existing, folder_size, gb, list_drives,
                  close_processes, describe_lockers, find_lockers, is_admin, lp, process_names, ps_json, purge, run_ps,
                  running_blockers, running_names, system_drive, _rm)

APP_NAME = "Dusty Ai"
ADMIN = is_admin()
app = Flask(__name__)
app.jinja_env.globals.update(APP_NAME=APP_NAME, IS_ADMIN=ADMIN, CAN_ELEVATE=IS_WINDOWS and not ADMIN)


@app.template_filter("size")
def size_filter(g):
    """ГБ → «512 МБ» / «1,4 ГБ»: мелочь в гигабайтах выглядит как «0,0». Запятая — по-русски,
    неразрывный пробел — чтобы число не отрывалось от единицы при переносе.
    Точность: ≥100 ГБ — целые, ≥10 — один знак, иначе два."""
    g = g or 0
    if g < 1:
        return f"{round(g * 1024)}\u00a0МБ"
    s = f"{g:.{0 if g >= 100 else 1 if g >= 10 else 2}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",") + "\u00a0ГБ"


@app.template_filter("num")
def num_filter(v, digits=1):
    """Число с русской запятой без хвоста нулей: 103.0 → «103», 7.60 → «7,6»."""
    s = f"{(v or 0):.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


HOST, PORT = "127.0.0.1", 5000
SCANS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scans")
HISTORY_KEEP = 20
HISTORY_RE = re.compile(r"^scan_\d{8}_\d{6}\.json$")
SCAN_WORKERS = 8

_lock = threading.Lock()
scan_state = {"status": "idle", "progress": 0, "message": ""}
scan_data = {}
_drive_cache = {"t": 0.0, "v": []}
_mock_unlocked = set()
MOCK_LOCKED = {
    "user_temp": {"files": ["~DF3A91.tmp", "pycharm-cache.lock", "chrome_scoped_dir"], "procs": [
        {"pid": 5151, "app": "PyCharm", "proc": "pycharm64", "protected": False, "why": ""},
        {"pid": 4242, "app": "Google Chrome", "proc": "chrome", "protected": False, "why": ""},
        {"pid": 1200, "app": "Проводник Windows", "proc": "explorer", "protected": True, "why": "системный процесс"}]},
    "chrome_ai_model": {"files": ["weights.bin"], "procs": [
        {"pid": 4242, "app": "Google Chrome", "proc": "chrome", "protected": False, "why": ""}]},
}


# ───────────────────────────────── диски ─────────────────────────────────

def add_pct(drives):
    for d in drives:
        d["Pct"] = round(d["UsedGB"] / d["TotalGB"] * 100) if d.get("TotalGB") else 0


def get_drives(force=False):
    """Список дисков; PowerShell дорогой, поэтому кэш на 20 секунд."""
    if not force and time.time() - _drive_cache["t"] < 20 and _drive_cache["v"]:
        return [dict(d) for d in _drive_cache["v"]]
    drives = [dict(d) for d in catalog.MOCK["drives"]] if not IS_WINDOWS else list_drives()
    add_pct(drives)
    _drive_cache.update(t=time.time(), v=drives)
    return [dict(d) for d in drives]


# ─────────────────────────────── сканирование ───────────────────────────────

def set_state(**kw):
    with _lock:
        scan_state.update(kw)


def scan_programs():
    programs = ps_json(
        "$keys='HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*';"
        "Get-ItemProperty $keys -EA SilentlyContinue | "
        "Where-Object { $_.DisplayName -and $_.EstimatedSize -gt 300000 -and -not $_.SystemComponent } | "
        "Sort-Object EstimatedSize -Descending | Select-Object -First 20 | "
        "Select DisplayName, DisplayVersion, InstallLocation, DisplayIcon, UninstallString,"
        "@{n='SizeMB';e={[math]::Round($_.EstimatedSize/1024,0)}} | ConvertTo-Json -Compress"
    )
    for p in programs:
        loc = p.get("InstallLocation")
        if loc and os.path.isdir(loc):  # реестр врёт: берём реальный размер папки
            p["SizeMB"] = round(folder_size(loc, 10) / 1024 ** 2)
        m = re.match(r'^"?([^",]+\.(?:exe|ico))', p.get("DisplayIcon") or "", re.I)
        p["icon_src"] = m.group(1) if m else None
        p["drive"] = drive_of(loc or p["icon_src"] or "", system_drive())
        cmd = (p.pop("UninstallString", None) or "").strip()
        # MSI: «/I{GUID}» открывает «изменить/восстановить», а нужно «удалить» — /X
        p["_cmd"] = re.sub(r"(?i)(msiexec(?:\.exe)?\s+)/I", r"\1/X", cmd) if cmd else None
        p["id"] = scanners.short_id("app_", p["DisplayName"] + str(p.get("DisplayVersion")))
    return [p for p in programs if p.get("SizeMB", 0) > 300]


def scan_item(item):
    path = expand(item["path"])
    size = folder_size(path) if os.path.isdir(path) else 0
    return {**item, "resolved": path, "exists": os.path.isdir(path), "size_gb": gb(size),
            "drive": drive_of(path)}


def compute_totals(d):
    d["safe_gb"] = round(sum(i["size_gb"] for i in d["safe"]) + sum(i["size_gb"] for i in d.get("recycle", [])), 2)
    # дубликаты и мусор разработчика — решение пользователя, поэтому «на усмотрение»;
    # остатки Temp уже входят в размер самого Temp и отдельно не суммируются
    d["review_gb"] = round(sum(i["size_gb"] for i in d["review"]) + sum(i["size_gb"] for i in d.get("junk", []))
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
    for i in data["safe"] + data["review"]:
        i["icon_exe"] = first_existing(i.get("icon_src"))
    for p in data["programs"]:
        p["icon_exe"] = p.get("icon_src")
    for p in data["python"]:
        p["icon_exe"] = os.path.join(p["path"], "python.exe")
    every = data["safe"] + data["review"] + data["programs"] + data["python"]
    icons = extract_icons([i.get("icon_exe") for i in every])
    for i in every:
        i["icon_img"] = icons.get(i.get("icon_exe"))


def extra_item(kind, d):
    """Элемент таблицы из обзора диска (мусор разработчика / корзина)."""
    if kind == "junk":
        return dict(id=d.get("id") or scanners.short_id("junk_", d["path"]), name=f'{d["name"]} · {ntpath.basename(ntpath.dirname(d["path"]))}',
                    icon="🧰", path=d["path"], resolved=d["path"], size_gb=d["size_gb"], deletable=True, drive=drive_of(d["path"]),
                    desc=f'{d["what"]}. Восстанавливается командой установки зависимостей проекта.',
                    restore="npm install / pip install / python -m venv — проект снова заработает.")
    return dict(id=f'recycle_{d["drive"]}', name=f'Корзина {d["drive"]}:', icon="🗑️", path=f'{d["drive"]}:\\$Recycle.Bin',
                resolved=f'{d["drive"]}:\\$Recycle.Bin', size_gb=d["size_gb"], deletable=True, drive=d["drive"],
                desc="Файлы, которые вы уже удалили, но они всё ещё занимают место.",
                restore="Восстановить файлы из корзины после очистки будет нельзя.")


def _mock_big_warning(f):
    low = f["path"].lower()
    if "site-packages" in low:
        return scanners_warn_site
    if "\\appdata\\" in low:
        return "Лежит в: данные приложения в AppData. Программа, которой это принадлежит, может перестать работать — лучше удалить её через «Программы»."
    return ""


scanners_warn_site = "Часть установленного Python-пакета — после удаления пакет перестанет работать (переустановка: pip install --force-reinstall)."


def _mock_big_deletable(f):
    """В демо считаем так же, как в жизни, но по виртуальным путям."""
    low = f["path"].lower()
    if low.endswith(("pagefile.sys", "hiberfil.sys", "swapfile.sys")):
        return False, "файл подкачки/гибернации — им управляет Windows (отключается в настройках системы)"
    if "\\windows\\" in low:
        return False, "папка Windows — удаление может сломать систему"
    return True, ""


def assemble_extras(data, deep, recycle):
    """Кладёт результаты обзора дисков в отчёт и регистрирует динамические id."""
    dyn = data["dynamic"]
    data["overview"], data["junk"], data["recycle"], data["bigfiles"] = {}, [], [], []
    for letter, res in deep.items():
        for f in res["big_files"]:
            f.setdefault("id", scanners.short_id("big_", f["path"]))
            kind, icon = scanners.classify_file(f["name"])
            f.setdefault("kind", kind)
            f.setdefault("icon", icon)
            f["drive"] = letter
            ok, why = scanners.big_deletable(f["path"]) if not data["mock"] else _mock_big_deletable(f)
            f["deletable"], f["why"] = ok, why
            f["warn"] = (scanners.big_warning(f["path"]) if not data["mock"] else _mock_big_warning(f)) if ok else ""
            dyn[f["id"]] = {"type": "bigdel" if ok else "bigfile", "path": f["path"]}
            data["bigfiles"].append(f)
        for j in res["junk"]:
            item = extra_item("junk", j)
            data["junk"].append(item)
            dyn[item["id"]] = {"type": "junk", "path": j["path"]}
        for t in res["top_dirs"]:
            t["id"] = scanners.short_id("td_", t["path"])
            dyn[t["id"]] = {"type": "bigfile", "path": t["path"]}  # только показать в проводнике
        data["overview"][letter] = {"top_dirs": res["top_dirs"], "big_files": res["big_files"], "partial": res["partial"]}
    data["bigfiles"].sort(key=lambda f: -f["size_gb"])
    for letter, size in recycle.items():
        if size > 0:
            item = extra_item("recycle", {"drive": letter, "size_gb": size})
            data["recycle"].append(item)
            dyn[item["id"]] = {"type": "recycle", "drive": letter}


def register_dynamic(data):
    dyn = data["dynamic"]
    for t in data["temp_items"]:
        dyn[t["id"]] = {"type": "temp", "path": t["path"]}
    for g in data["dups"]:
        for f in g["files"]:
            dyn[f["id"]] = {"type": "dup", "path": f["path"], "group": g["hash"]}
    for f in data.get("downloads", []):
        dyn[f["id"]] = {"type": "download", "path": f["path"]}
    for grp in data.get("profile", []):
        for i in grp["entries"]:
            dyn[i["id"]] = {"type": "bigfile", "path": i["path"]}  # только показать в проводнике
    for p in data["programs"]:
        dyn[p["id"]] = {"type": "uninstall", "cmd": p.pop("_cmd", None), "name": p["DisplayName"]}


def mock_extras(data, sel):
    """Демо-данные для умного Temp, Python, дубликатов, программ и обзора дисков."""
    dyn = data["dynamic"]
    for t in catalog.MOCK["smart_temp"]:
        item = dict(id=scanners.short_id("tmp_", t["path"]), name=t["name"], icon="📁", path=t["path"],
                    resolved=t["path"], kind="folder", deletable=True, size_gb=t["size_gb"], drive="C",
                    age_days=t["age_days"], desc=f'{t["reason"]} Не изменялась {t["age_days"]} дн.',
                    restore="Ничего: если установщик понадобится, он распакуется заново.")
        data["temp_items"].append(item)
    for g in catalog.MOCK["dups"]:
        group = {"hash": scanners.short_id("grp_", g["files"][0]["path"]), "size_gb": g["size_gb"],
                 "wasted_gb": g["wasted_gb"], "files": []}
        for f in g["files"]:
            group["files"].append({**f, "id": scanners.short_id("dup_", f["path"])})
        data["dups"].append(group)
    data["python"] = [dict(p, drive=drive_of(p["path"])) for p in catalog.MOCK["python"]]
    data["programs"] = []
    for p in catalog.MOCK["programs"]:
        p = dict(p, drive="C", _cmd="mock")
        p["id"] = scanners.short_id("app_", p["DisplayName"])
        data["programs"].append(p)
    if "C" in sel:
        for f in catalog.MOCK["downloads"]:
            data["downloads"].append(dict(f, id=scanners.short_id("dl_", f["path"])))
        data["profile"] = [dict(g, entries=[dict(i, id=scanners.short_id("pf_", i["path"])) for i in g["entries"]])
                           for g in catalog.MOCK["profile"]]
    deep = {L: {**catalog.MOCK["deep"][L]} for L in sel if L in catalog.MOCK["deep"]}
    recycle = {L: catalog.MOCK["recycle"][L] for L in sel if L in catalog.MOCK["recycle"]}
    return deep, recycle


def do_scan(opts):
    try:
        mock = not IS_WINDOWS
        _mock_unlocked.clear()
        set_state(status="scanning", progress=2, message="Определяю диски…")
        all_drives = get_drives(force=True)
        sel = [d["Name"] for d in all_drives if d["Name"] in opts["drives"] and d.get("scannable")]
        if not sel:
            raise ValueError("не выбран ни один доступный диск")
        sysd = system_drive() if not mock else "C"
        want_dups = opts.get("dups", True)

        data = {"drives": all_drives, "scanned": sel, "system_drive": sysd, "programs": [], "python": [],
                "dups": [], "temp_items": [], "junk": [], "recycle": [], "overview": {}, "dynamic": {},
                "downloads": [], "profile": [],
                "protected": catalog.DO_NOT_TOUCH, "mock": mock, "readonly": False,
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        for d in data["drives"]:
            d["scanned"] = d["Name"] in sel

        items = [i for i in catalog.SAFE + catalog.REVIEW if drive_of(expand(i["path"]), sysd) in sel]
        found, deep, recycle = [], {}, {}

        if mock:
            for n, item in enumerate(items):
                set_state(progress=5 + int(70 * n / max(len(items), 1)), message=f"Замеряю: {item['name']}")
                it = scan_item(item)
                it.update(size_gb=catalog.MOCK["sizes"].get(it["id"], 0), drive="C")
                it["exists"] = it["size_gb"] > 0
                found.append(it)
                time.sleep(0.04)
            set_state(progress=80, message="Windows не обнаружена — показываю демо-данные")
            deep, recycle = mock_extras(data, sel)
        else:
            tasks = {}
            for item in items:
                tasks[f"item:{item['id']}"] = (item["name"], lambda it=item: scan_item(it))
            if sysd in sel:
                tasks["temp"] = ("остатки установщиков в Temp", scanners.scan_smart_temp)
            tasks["programs"] = ("установленные программы", scan_programs)
            tasks["python"] = ("установки Python", scanners.scan_python)
            roots = [r for r in scanners.dup_roots() if drive_of(r) in sel]
            if want_dups and roots:
                tasks["dups"] = ("дубликаты файлов", lambda: scanners.scan_duplicates(roots=roots))
            if drive_of(scanners.downloads_root(), sysd) in sel:
                tasks["downloads"] = ("крупные файлы в Загрузках", scanners.scan_downloads)
            if opts.get("profile", True) and drive_of(expand("%USERPROFILE%"), sysd) in sel:
                tasks["profile"] = ("обзор профиля и AppData", scanners.scan_profile_overview)
            for L in sel:
                tasks[f"recycle:{L}"] = (f"корзина {L}:", lambda L=L: scanners.scan_recycle(L))
                if L != sysd or opts.get("deep_system", True):
                    tasks[f"deep:{L}"] = (f"обзор диска {L}: целиком", lambda L=L: scanners.scan_drive_deep(
                        L, deadline=150 if L == sysd else 90, system=(L == sysd)))
            results, done = {}, 0
            with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
                futs = {pool.submit(fn): (key, label) for key, (label, fn) in tasks.items()}
                for fut in as_completed(futs):
                    key, label = futs[fut]
                    try:
                        results[key] = fut.result()
                    except Exception:  # noqa: BLE001 — один сбойный сканер не должен ронять весь скан
                        results[key] = None
                    done += 1
                    set_state(progress=5 + int(85 * done / len(tasks)), message=f"Готово: {label}")
            found = [results[k] for k in results if k.startswith("item:") and results[k]]
            data["temp_items"] = [t for t in (results.get("temp") or [])]
            data["programs"] = [p for p in (results.get("programs") or []) if p["drive"] in sel]
            data["python"] = [p for p in (results.get("python") or []) if drive_of(p["path"]) in sel]
            data["dups"] = results.get("dups") or []
            data["downloads"] = results.get("downloads") or []
            data["profile"] = results.get("profile") or []
            for p in data["python"]:
                p["drive"] = drive_of(p["path"])
            deep = {k[5:]: v for k, v in results.items() if k.startswith("deep:") and v}
            recycle = {k[8:]: v for k, v in results.items() if k.startswith("recycle:") and v is not None}

        seen, unique = set(), []
        for it in found:  # %TEMP% и %LOCALAPPDATA%\Temp — обычно одна папка, не считаем дважды
            key = os.path.normcase(os.path.realpath(it["resolved"]))
            if key not in seen:
                seen.add(key)
                unique.append(it)
        data["safe"] = [i for i in unique if catalog.ZONE[i["id"]] == "safe" and i["exists"]]
        data["review"] = [i for i in unique if catalog.ZONE[i["id"]] == "review" and i["exists"]]
        for t in data["temp_items"]:
            t.setdefault("drive", drive_of(t["path"], sysd))
        register_dynamic(data)
        for t in data["temp_items"]:
            data["dynamic"][t["id"]] = {"type": "temp", "path": t["path"]}
        assemble_extras(data, deep, recycle)
        link_temp_parents(data)
        if not mock:
            set_state(progress=94, message="Загружаю иконки приложений…")
            attach_icons(data)

        by_size = lambda i: -i["size_gb"]
        for k in ("safe", "review", "junk"):
            data[k].sort(key=by_size)
        compute_totals(data)
        c = next((d for d in data["drives"] if d["Name"] == sysd), None)
        data["free_c"] = c["FreeGB"] if c and c["scanned"] else next(
            (d["FreeGB"] for d in data["drives"] if d["scanned"]), None)

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
    return {k: v for k, v in d.items() if k not in ("dynamic", "readonly", "_locks")}


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
                         "free_c": d.get("free_c"), "mock": d.get("mock"),
                         "drives": ", ".join(x + ":" for x in d.get("scanned", ["C"]))})
        except (OSError, ValueError):
            continue
    return rows


# ─────────────────────────────── удаление ───────────────────────────────

def delete_item(item):
    """Удаляет по каталогу, пропуская занятые файлы.
    Возвращает (освобождено ГБ, осталось ГБ, пропущено файлов, образцы путей пропущенных)."""
    path = expand(item["path"])
    if not os.path.isdir(path):
        return 0.0, 0.0, 0, []
    before = folder_size(path, 120)
    skipped, locked = 0, []
    if item["kind"] == "contents":
        with os.scandir(path) as it:
            for e in list(it):
                if e.is_dir(follow_symlinks=False):
                    skipped += purge(e.path, collect=locked)
                elif not _rm(e.path):
                    skipped += 1
                    locked.append(e.path)
    else:
        skipped = purge(path, collect=locked)
    after = folder_size(path, 120) if os.path.isdir(path) else 0
    return round(max(before - after, 0) / 1024 ** 3, 4), gb(after), skipped, locked


def err(msg, code):
    return jsonify(ok=False, error=msg), code


# ───────────────────────────────── строки отчёта ─────────────────────────────────

def build_rows(d):
    """Единый список строк таблицы: A — безопасно, B — на усмотрение, C — только вручную."""
    rows, sysd = [], d.get("system_drive", "C")

    def row(i, cat, kind):
        path = i.get("resolved") or i.get("path")
        rows.append(dict(
            id=i["id"], name=i["name"], path=path, size_gb=i["size_gb"], cat=cat, kind=kind,
            drive=i.get("drive") or drive_of(path, sysd), reason=i["desc"], restore=i.get("restore", ""),
            deletable=bool(i.get("deletable")) and not d.get("readonly"),
            icon=i.get("icon", "📁"), img=i.get("icon_img"), parent_id=i.get("parent_id")))

    for i in d["safe"]:
        row(i, "A", "static")
    for i in d.get("recycle", []):
        row(i, "A", "recycle")
    for i in d["temp_items"]:
        row(i, "A", "temp")
    for i in d["review"]:
        row(i, "B" if i.get("deletable") else "C", "static")
    for i in d.get("junk", []):
        row(i, "B", "junk")
    rows = [r for r in rows if r["size_gb"] > 0]
    rows.sort(key=lambda r: -r["size_gb"])
    return rows


def with_defaults(d):
    """Старые сохранённые отчёты не знают про новые поля."""
    d.setdefault("scanned", [x["Name"] for x in d.get("drives", [])] or ["C"])
    d.setdefault("system_drive", "C")
    for k in ("junk", "recycle", "dups", "python", "programs", "temp_items", "protected", "downloads", "profile"):
        d.setdefault(k, [])
    d.setdefault("overview", {})
    if "bigfiles" not in d:  # отчёты, сохранённые до отдельной вкладки
        d["bigfiles"] = [dict(f, drive=L, deletable=False, why="сохранённый отчёт")
                         for L, o in d["overview"].items() for f in o.get("big_files", [])]
        d["bigfiles"].sort(key=lambda f: -f["size_gb"])
    for x in d.get("drives", []):
        x.setdefault("scanned", x["Name"] in d["scanned"])
        x.setdefault("Type", "local")
        x.setdefault("Label", "")
    for p in d["programs"]:
        p.setdefault("drive", "C")
        p.setdefault("id", scanners.short_id("app_", p.get("DisplayName", "")))
    for f in d["downloads"]:
        f["drive"] = drive_of(f["path"], d["system_drive"])
    for g in d["dups"]:
        g["drives"] = sorted({drive_of(f["path"]) for f in g["files"]})
    return d



# ───────────────────────────── AI-сводка (Cloudflare Workers AI) ─────────────────────────────

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
CF_MODEL = "@cf/meta/llama-3.2-3b-instruct"  # можно заменить переменной CF_MODEL (например, на модель побольше)
CF_MAX_TOKENS = 700  # по-русски токенов уходит в 2–3 раза больше, чем слов: 300 обрывало ответ
CF_BASE = "https://api.cloudflare.com/client/v4"
_ai_cache = {}


class AIError(Exception):
    """Ошибка AI-сводки; текст безопасен для показа пользователю (токен в нём не бывает)."""

    def __init__(self, message, code=502):
        super().__init__(message)
        self.code = code


def read_env_file(path=ENV_FILE):
    """Минимальный разбор .env (KEY=VALUE, # комментарии, кавычки) — без внешних библиотек."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return out


def cf_setting(name):
    """Переменная окружения важнее .env; заглушку из .env.example считаем «не задано»."""
    v = os.environ.get(name) or read_env_file().get(name) or ""
    return "" if v.startswith("your_") else v


def plan_groups(d, drive=None):
    """Готовый план из реальных находок. Букв A/B/C модели не даём: слабая модель начинает
    рассуждать про «зоны» вместо файлов — поэтому только слова и конкретные названия."""
    rows = [r for r in build_rows(d) if r["kind"] != "temp" and (not drive or r["drive"] == drive)]
    pick = lambda cats, n: [f"{r['name'][:50]} — {fmt_gb(r['size_gb'])}" for r in rows if r["cat"] in cats][:n]
    return {"safe": pick("A", 3), "ask": pick("B", 2), "manual": pick("C", 2),
            "safe_total": round(sum(r["size_gb"] for r in rows if r["cat"] == "A"), 1)}


def fmt_gb(g):
    return f"{g:g} ГБ" if g >= 1 else f"{round(g * 1024)} МБ"


def build_prompt(d, drive=None):
    p = plan_groups(d, drive)
    block = lambda items: "\n".join(f"- {x}" for x in items) or "- ничего"
    return (
        "Ты — ассистент по очистке Windows. Сканирование ПК нашло следующее.\n\n"
        f"Можно удалить сразу, это безопасно и само восстановится (всего {p['safe_total']} ГБ):\n{block(p['safe'])}\n\n"
        f"Удалять можно, но решать пользователю:\n{block(p['ask'])}\n\n"
        f"Не удалять автоматически, только вручную и осторожно:\n{block(p['manual'])}\n\n"
        "Перескажи это простыми словами тремя короткими предложениями, называя конкретные пункты из списков:\n"
        "1) главный вывод с общим объёмом безопасного мусора; "
        "2) что удалить первым и почему оно безопасно; "
        
        + ("3) что не трогать без раздумий (из последнего списка). Без воды."
           if p["manual"] else "3) что из списка «решать пользователю» стоит проверить перед удалением. Без воды.")
    )


CF_SYSTEM = (
    "Отвечай только по-русски, обычным текстом. Ровно три коротких предложения, пронумерованные 1), 2), 3). "
    "Называй программы и размеры точно как в данных, ничего не выдумывай. "
    "Слова «зона», «категория» и буквы A/B/C не используй."
)


def tidy_summary(text):
    """Ответ мог оборваться по лимиту токенов: обрезаем до последнего законченного предложения
    и убираем повисший маркер списка («5. **»)."""
    text = text.strip()
    if text and text[-1] not in ".!?…»)":
        cut = max(text.rfind(c) for c in ".!?…")
        if cut > len(text) * 0.4:
            text = text[:cut + 1]
    text = re.sub(r"(?:\n|\s)+\d+[.)]\s*(?:\*\*)?\s*$", "", text)
    return text.rstrip("* \n")


def cloudflare_ai_summary(data, drive=None):
    """Запрашивает у Cloudflare Workers AI краткую сводку по результатам скана."""
    account, token = cf_setting("CF_ACCOUNT_ID"), cf_setting("CF_API_TOKEN")
    if not token:
        raise AIError("CF_API_TOKEN not set", 400)
    if not account:
        raise AIError("CF_ACCOUNT_ID not set", 400)
    base = os.environ.get("CF_API_BASE", CF_BASE).rstrip("/")
    model = cf_setting("CF_MODEL") or CF_MODEL
    url = f"{base}/accounts/{account}/ai/run/{model}"
    body = json.dumps({"messages": [{"role": "system", "content": CF_SYSTEM},
                                    {"role": "user", "content": build_prompt(data, drive)}],
                       "max_tokens": CF_MAX_TOKENS, "temperature": 0.2}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msgs = [x.get("message", "") for x in json.load(e).get("errors", [])]
        except (ValueError, OSError):
            msgs = []
        hint = {401: "токен недействителен", 403: "у токена нет права Workers AI",
                429: "превышен лимит запросов"}.get(e.code, "")
        raise AIError(f"Cloudflare вернул {e.code}" + (f": {hint}" if hint else "")
                      + (f" ({'; '.join(m for m in msgs if m)[:200]})" if any(msgs) else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AIError(f"Нет связи с Cloudflare: {getattr(e, 'reason', e)}")
    except ValueError:
        raise AIError("Cloudflare вернул некорректный ответ")
    text = ((payload.get("result") or {}).get("response") or "").strip()
    if not payload.get("success", True) or not text:
        errs = "; ".join(x.get("message", "") for x in payload.get("errors") or [])[:200]
        raise AIError("Пустой ответ модели" + (f": {errs}" if errs else ""))
    return tidy_summary(text)


# ───────────────────────────────── маршруты ─────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html", catalog=catalog, history=list_history(), active="home")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/api/drives")
def api_drives():
    return jsonify(drives=get_drives(), system=system_drive() if IS_WINDOWS else "C")


@app.post("/scan")
def scan():
    body = request.get_json(silent=True) or {}
    letters = [str(x).upper()[:1] for x in body.get("drives") or []]
    if not letters:
        letters = [system_drive() if IS_WINDOWS else "C"]
    with _lock:
        if scan_state["status"] == "scanning":
            return jsonify(ok=True, already=True)
        scan_state.update(status="scanning", progress=0, message="Запуск…")
    opts = {"drives": letters, "dups": bool(body.get("dups", True)), "profile": bool(body.get("profile", True)),
            "deep_system": bool(body.get("deep_system", True))}
    threading.Thread(target=do_scan, args=(opts,), daemon=True).start()
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
        d = with_defaults(dict(scan_data))
        rows = build_rows(d)
    return render_template("report.html", d=d, rows=rows, active="report")


@app.get("/api/ai-summary")
def api_ai_summary():
    """AI-сводка по текущему отчёту. Запрос уходит наружу, поэтому только по явному клику
    со страницы приложения: чужие сайты (cross-site) не могут тратить токен."""
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify(summary=None, error="forbidden"), 403
    drive = (request.args.get("drive") or "").upper()[:1] or None
    with _lock:
        if not scan_data:
            return jsonify(summary=None, error="Сначала запустите сканирование"), 400
        d = with_defaults(dict(scan_data))
        key = (d.get("scanned_at"), d.get("total_gb"), drive)
    if not request.args.get("refresh") and key in _ai_cache:
        return jsonify(summary=_ai_cache[key], cached=True)
    try:
        summary = cloudflare_ai_summary(d, drive)
    except AIError as e:
        return jsonify(summary=None, error=str(e)), e.code
    _ai_cache.clear()
    _ai_cache[key] = summary
    return jsonify(summary=summary)


@app.get("/export")
def export():
    with _lock:
        if not scan_data:
            return redirect("/")
        body = json.dumps(public_data(scan_data), ensure_ascii=False, indent=2)
    fname = time.strftime("dusty_report_%Y%m%d_%H%M%S.json")
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


def perform_delete(item_id, running=None):
    """Удаляет один пункт. Возвращает (payload, http_code). running — готовый список процессов."""
    def fail(msg, code):
        return {"ok": False, "id": item_id, "error": msg}, code

    with _lock:
        if scan_data.get("readonly"):
            return fail("Это сохранённый отчёт — он только для просмотра", 403)
        dyn = scan_data.get("dynamic", {}).get(item_id)
        mock = scan_data.get("mock", False)
        scanned = list(scan_data.get("scanned", []))

    if item_id in catalog.DELETABLE_IDS:
        kind, item = "static", catalog.ALL_ITEMS[item_id]
    elif dyn and dyn["type"] in ("temp", "dup", "junk", "recycle", "download", "bigdel"):
        kind, item = dyn["type"], dyn
    else:
        return fail("Этот пункт нельзя удалять через приложение", 403)

    # Жёстко блокируем только то, что реально опасно: чистка Temp посреди установки может её сломать.
    # Всё остальное (кэши) удаляем сразу: занятые файлы просто пропускаются, об этом скажем в ответе.
    is_temp = kind == "temp" or item_id in ("user_temp", "local_temp", "windows_temp")
    running = running_names() if running is None else running
    installing = running_blockers(["vs_installer"], running) if is_temp else []
    if installing:
        return fail("Сейчас идёт установка (" + ", ".join(installing) + ") — дождитесь её завершения, "
                    "иначе её можно повредить", 409)
    hints = running_blockers(item.get("blockers", []) if kind == "static" else [], running)
    skipped, locked_paths = 0, []

    if mock and item_id in MOCK_LOCKED and item_id not in _mock_unlocked:  # демо: показываем, как выглядит «файл занят»
        lock = {"count": 7, "files": MOCK_LOCKED[item_id]["files"], "procs": MOCK_LOCKED[item_id]["procs"]}
        with _lock:
            scan_data.setdefault("_locks", {})[item_id] = {p["pid"]: p for p in lock["procs"] if not p["protected"]}
        return {"ok": False, "id": item_id, "freed_gb": 0, "locked": lock,
                "error": "Часть файлов занята программами"}, 409
    freed = remaining = 0.0
    group = None
    pool = {"static": lambda: scan_data["safe"] + scan_data["review"], "temp": lambda: scan_data["temp_items"],
            "junk": lambda: scan_data["junk"], "recycle": lambda: scan_data["recycle"]}
    if kind in pool:
        entry = find_item(pool[kind](), item_id)
        if not entry:
            return fail("Пункт не найден — пересканируйте", 404)
    if kind == "static":
        if mock:
            freed = entry["size_gb"]
        else:
            freed, remaining, skipped, locked_paths = delete_item(item)
    elif kind == "temp":
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_smart_temp(item["path"]):
                return fail("Папка изменилась или больше не подходит под правила — пересканируйте", 409)
            freed, remaining, skipped, locked_paths = delete_item({"path": item["path"], "kind": "folder"})
    elif kind == "junk":
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_junk(item["path"], [f"{L}:\\" for L in scanned]):
                return fail("Папка больше не подходит под правила — пересканируйте", 409)
            freed, remaining, skipped, locked_paths = delete_item({"path": item["path"], "kind": "folder"})
    elif kind == "recycle":
        freed = entry["size_gb"]
        if not mock:
            letter = item["drive"]
            if not re.fullmatch(r"[A-Z]", letter):
                return fail("Неверный диск", 400)
            run_ps(f"Clear-RecycleBin -DriveLetter {letter} -Force -ErrorAction SilentlyContinue", timeout=120)
            remaining = scanners.scan_recycle(letter)
            freed = round(max(entry["size_gb"] - remaining, 0), 2)
    elif kind == "bigdel":
        with _lock:
            entry = find_item(scan_data["bigfiles"], item_id)
        if not entry:
            return fail("Файл не найден в отчёте — пересканируйте", 404)
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_bigfile(item["path"]):
                return fail("Файл нельзя удалить из приложения (системный, в папке программ или уже удалён)", 409)
            try:
                size = os.path.getsize(item["path"])
                os.remove(lp(item["path"]))
            except PermissionError:
                lock = lock_info(item_id, 1, [item["path"]])
                return {"ok": False, "id": item_id, "freed_gb": 0, "locked": lock,
                        "error": "Файл занят программой или защищён"}, 409
            except OSError as e:
                return fail(f"Не удалось удалить файл: {e}", 500)
            freed = gb(size)
    elif kind == "download":
        with _lock:
            entry = find_item(scan_data["downloads"], item_id)
        if not entry:
            return fail("Файл не найден в отчёте — пересканируйте", 404)
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_download(item["path"]):
                return fail("Файл не в Загрузках или уже удалён — пересканируйте", 409)
            try:
                size = os.path.getsize(item["path"])
                os.remove(lp(item["path"]))
            except OSError as e:
                return fail(f"Не удалось удалить файл: {e}", 500)
            freed = gb(size)
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

    lock = lock_info(item_id, skipped, locked_paths) if skipped else None
    if skipped and freed == 0:
        out = {"ok": False, "id": item_id, "freed_gb": 0, "locked": lock,
               "error": skipped_message(item_id, skipped, hints)}
        return out, 409

    with _lock:
        d = scan_data
        if kind == "bigdel":
            d["bigfiles"].remove(entry)
            for o in d["overview"].values():
                o["big_files"] = [f for f in o["big_files"] if f["id"] != item_id]
            d["dynamic"].pop(item_id, None)
        elif kind == "download":
            d["downloads"].remove(entry)
            d["dynamic"].pop(item_id, None)
        elif kind in pool:
            entry["size_gb"] = remaining
            if kind == "temp":
                for i in d["safe"]:  # размер Temp уменьшился на освобождённое
                    if i["id"] == entry.get("parent_id"):
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
    out = {"ok": True, "id": item_id, "freed_gb": freed, "kind": kind, "remaining_gb": remaining, "skipped": skipped}
    if skipped:
        out["warn"] = skipped_message(item_id, skipped, hints)
        out["locked"] = lock
    return out, 200


def lock_info(item_id, skipped, paths):
    """Кто держит пропущенные файлы. Список процессов запоминаем на сервере: закрывать потом
    можно только их (клиент присылает pid, но мы сверяем с этим списком)."""
    procs = describe_lockers(find_lockers(paths)) if IS_WINDOWS else []
    with _lock:
        scan_data.setdefault("_locks", {})[item_id] = {p["pid"]: p for p in procs if not p["protected"]}
    return {"count": skipped, "files": [os.path.basename(p) for p in paths[:3]], "procs": procs}


def skipped_message(item_id, skipped, hints):
    who = f"закройте {', '.join(hints)}" if hints else "закройте программы, которые могли их занять"
    msg = f"{skipped} файл(ов) заняты и пропущены — {who} и повторите"
    if item_id == "windows_temp" and not ADMIN:
        msg = f"{skipped} файл(ов) системного Temp требуют прав администратора — запустите Dusty Ai от имени администратора"
    return msg


@app.post("/delete")
def delete():
    item_id = (request.get_json(silent=True) or {}).get("id")
    payload, code = perform_delete(item_id)
    if payload["ok"]:
        payload["reload"] = payload["kind"] == "dup"
    return jsonify(payload), code


@app.post("/delete_batch")
def delete_batch():
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 200:
        return err("Нужен непустой список id", 400)
    running = running_names()  # один вызов PowerShell на всю партию
    results, seen = [], set()
    # сначала остатки Temp, потом сам Temp: так «родитель» не успеет удалить «детей» из-под ног
    ordered = sorted((i for i in ids if isinstance(i, str)), key=lambda i: not i.startswith("tmp_"))
    for item_id in ordered:
        if item_id in seen:
            continue
        seen.add(item_id)
        payload, _ = perform_delete(item_id, running)
        results.append(payload)
    freed = round(sum(r.get("freed_gb", 0) for r in results if r["ok"]), 4)
    return jsonify(ok=True, results=results, freed_gb=freed,
                   failed=[r for r in results if not r["ok"] and not r.get("locked")])


@app.post("/api/unlock-retry")
def unlock_retry():
    """Закрывает выбранные пользователем программы, которые держат файлы, и повторяет удаление.
    Закрыть можно только процессы из нашего же списка блокировщиков (id из клиента сверяются с ним)."""
    body = request.get_json(silent=True) or {}
    ids = [i for i in body.get("ids") or [] if isinstance(i, str)][:50]
    want = {int(p) for p in body.get("pids") or [] if isinstance(p, int)}
    force = bool(body.get("force"))
    with _lock:
        if scan_data.get("readonly"):
            return err("Это сохранённый отчёт — он только для просмотра", 403)
        mock = scan_data.get("mock", False)
        allowed = {}
        for i in ids:
            allowed.update(scan_data.get("_locks", {}).get(i, {}))
    pids = sorted(want & set(allowed))
    closed, still = [], []
    if pids and mock:
        closed = [allowed[p]["app"] for p in pids]
        _mock_unlocked.update(ids)
    elif pids:
        now = process_names(pids)  # pid мог достаться другой программе, пока пользователь думал
        safe = [p for p in pids if now.get(p) and now[p] == (allowed[p].get("proc") or "").lower()]
        still = close_processes(safe, force)
        closed = [allowed[p]["app"] for p in safe if p not in still]
    running = running_names()
    results = [perform_delete(i, running)[0] for i in ids]
    freed = round(sum(r.get("freed_gb", 0) for r in results if r["ok"]), 4)
    return jsonify(ok=True, results=results, freed_gb=freed, closed=closed, still_running=still,
                   failed=[r for r in results if not r["ok"] and not r.get("locked")])


@app.post("/api/elevate")
def elevate():
    """Перезапускает приложение с правами администратора (Windows покажет окно UAC)."""
    if not IS_WINDOWS or ADMIN:
        return err("Уже запущено с правами администратора" if ADMIN else "Доступно только в Windows", 400)
    import ctypes
    here = os.path.dirname(os.path.abspath(__file__))
    params = "" if getattr(sys, "frozen", False) else f'"{os.path.abspath(__file__)}"'
    if ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, here, 1) <= 32:
        return err("Запуск от администратора отменён", 409)
    threading.Timer(1.5, lambda: os._exit(0)).start()  # старый экземпляр закрываем, чтобы не держать порт
    return jsonify(ok=True)


@app.post("/open")
def open_location():
    """Показывает папку/файл в проводнике. Путь берётся только из каталога или отчёта."""
    item_id = (request.get_json(silent=True) or {}).get("id")
    path = None
    with _lock:
        pools = (scan_data.get("safe", []) + scan_data.get("review", []) + scan_data.get("temp_items", [])
                 + scan_data.get("junk", []) + scan_data.get("recycle", []))
        for i in pools:
            if i["id"] == item_id:
                path = i.get("resolved") or i.get("path")
        dyn = scan_data.get("dynamic", {}).get(item_id)
        if dyn and dyn.get("path"):
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


@app.post("/uninstall")
def uninstall():
    """Запускает штатный деинсталлятор программы (его команда берётся из реестра при скане,
    клиент присылает только id). Windows сама покажет свои окна подтверждения."""
    item_id = (request.get_json(silent=True) or {}).get("id")
    with _lock:
        if scan_data.get("readonly"):
            return err("Это сохранённый отчёт — он только для просмотра", 403)
        dyn = scan_data.get("dynamic", {}).get(item_id)
        mock = scan_data.get("mock", False)
    if not dyn or dyn["type"] != "uninstall":
        return err("Неизвестная программа", 404)
    if mock:
        return jsonify(ok=True, demo=True)
    try:
        if dyn["cmd"]:
            subprocess.Popen(dyn["cmd"], shell=True)  # noqa: S602 — команда из реестра, не от клиента
            return jsonify(ok=True, mode="uninstaller")
        os.startfile("ms-settings:appsfeatures")  # noqa: S606 — у программы нет команды удаления
        return jsonify(ok=True, mode="settings")
    except OSError as e:
        return err(f"Не удалось запустить деинсталлятор: {e}", 500)


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


def window_background():
    """Цвет окна до загрузки страницы: в тёмной теме Windows не мигаем белым при старте."""
    if IS_WINDOWS:
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0:
                    return "#0a0d13"
        except OSError:
            pass
    return "#f2f4f9"


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
            webview.create_window(APP_NAME, url, width=1360, height=860, min_size=(1000, 640),
                                  background_color=window_background(), text_select=True)  # пути и AI-текст можно копировать
            webview.start()  # блокирует до закрытия окна
            server.shutdown()
            return
        except ImportError:
            print("pywebview не установлен — открываю в браузере (pip install pywebview)")
        except Exception as e:  # noqa: BLE001 — нет WebView2 и т.п.
            print(f"Не удалось открыть окно ({e}) — открываю в браузере")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    print(f"{APP_NAME}: {url}  (Ctrl+C — остановить)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
