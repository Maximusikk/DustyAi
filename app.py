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
                  lp, ps_json, run_ps, running_blockers, running_names, system_drive)

APP_NAME = "Dusty Ai"
app = Flask(__name__)
app.jinja_env.globals["APP_NAME"] = APP_NAME


@app.template_filter("size")
def size_filter(g):
    """ГБ → «512 МБ» / «1.4 ГБ»: мелочь в гигабайтах выглядит как «0.0»."""
    g = g or 0
    return f"{g:.2f}".rstrip("0").rstrip(".") + " ГБ" if g >= 1 else f"{round(g * 1024)} МБ"

HOST, PORT = "127.0.0.1", 5000
SCANS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scans")
HISTORY_KEEP = 20
HISTORY_RE = re.compile(r"^scan_\d{8}_\d{6}\.json$")
SCAN_WORKERS = 8

_lock = threading.Lock()
scan_state = {"status": "idle", "progress": 0, "message": ""}
scan_data = {}
_drive_cache = {"t": 0.0, "v": []}


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


def assemble_extras(data, deep, recycle):
    """Кладёт результаты обзора дисков в отчёт и регистрирует динамические id."""
    dyn = data["dynamic"]
    data["overview"], data["junk"], data["recycle"] = {}, [], []
    for letter, res in deep.items():
        for f in res["big_files"]:
            f.setdefault("id", scanners.short_id("big_", f["path"]))
            f["drive"] = letter
            dyn[f["id"]] = {"type": "bigfile", "path": f["path"]}
        for j in res["junk"]:
            item = extra_item("junk", j)
            data["junk"].append(item)
            dyn[item["id"]] = {"type": "junk", "path": j["path"]}
        data["overview"][letter] = {"top_dirs": res["top_dirs"], "big_files": res["big_files"], "partial": res["partial"]}
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
                if L != sysd:
                    tasks[f"deep:{L}"] = (f"обзор диска {L}:", lambda L=L: scanners.scan_drive_deep(L))
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
                         "free_c": d.get("free_c"), "mock": d.get("mock"),
                         "drives": ", ".join(x + ":" for x in d.get("scanned", ["C"]))})
        except (OSError, ValueError):
            continue
    return rows


# ─────────────────────────────── удаление ───────────────────────────────

def remove_entry(p):
    try:
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(lp(p), ignore_errors=True)
        else:
            os.remove(lp(p))
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
        shutil.rmtree(lp(path), ignore_errors=True)
    after = folder_size(path, 120) if os.path.isdir(path) else 0
    return gb(max(before - after, 0)), gb(after)


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


def summary_facts(d, drive=None):
    """Данные для промпта: топ-5 находок и суммы по зонам A/B/C. Только названия и размеры —
    пути к файлам наружу не отправляются."""
    rows = [r for r in build_rows(d) if r["kind"] != "temp" and (not drive or r["drive"] == drive)]
    dup_gb = sum(g["wasted_gb"] for g in d["dups"] if not drive or drive in g.get("drives", []))
    zones = {"A": 0.0, "B": dup_gb, "C": 0.0}
    for r in rows:
        zones[r["cat"]] += r["size_gb"]
    top = [{"name": r["name"][:60], "gb": r["size_gb"], "zone": r["cat"]} for r in rows[:5]]
    return top, {k: round(v, 2) for k, v in zones.items()}


def build_prompt(d, drive=None):
    top, zones = summary_facts(d, drive)
    lines = "\n".join(f"- {t['name']}: {t['gb']} ГБ (зона {t['zone']})" for t in top) or "- ничего не найдено"
    return (
        "Ты — ассистент по очистке Windows. Вот результаты сканирования ПК:\n"
        f"Топ-5 находок:\n{lines}\n"
        f"Суммарно: зона A (безопасно удалить) — {zones['A']} ГБ, зона B (на усмотрение) — {zones['B']} ГБ, "
        f"зона C (только вручную) — {zones['C']} ГБ.\n"
        "Как читать зоны: A — кэши и временные файлы, они пересоздаются сами, удалять безопасно; "
        "B — удалять можно, но пользователь сам решает; C — программа ничего не удаляет, только вручную, "
        "поэтому в C ничего не советуй удалять.\n"
        "Напиши сводку: 1) главный вывод одной фразой, 2) что удалить первым и почему, "
        "3) что точно не трогать. Кратко, 4-5 предложений, без воды."
    )


CF_SYSTEM = (
    "Отвечай только по-русски, обычным текстом без заголовков и вложенных списков. Укладывайся в 4-5 предложений "
    "и ровно три пункта 1), 2), 3). Используй только данные из запроса, ничего не выдумывай. "
    "Названия находок пиши как в данных. Не советуй трогать зону C и не называй безопасное (зона A) нужным системе."
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
    opts = {"drives": letters, "dups": bool(body.get("dups", True)), "profile": bool(body.get("profile", True))}
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

    dev = ["node", "npm", "python", "pythonw", "code"]
    if item_id in catalog.DELETABLE_IDS:
        kind, item = "static", catalog.ALL_ITEMS[item_id]
        blockers = item["blockers"] + catalog.GLOBAL_BLOCKERS
    elif dyn and dyn["type"] in ("temp", "dup", "junk", "recycle", "download"):
        kind, item = dyn["type"], dyn
        blockers = {"temp": ["vs_installer", "devenv"] + catalog.GLOBAL_BLOCKERS,
                    "junk": catalog.GLOBAL_BLOCKERS + dev}.get(kind, [])
    else:
        return fail("Этот пункт нельзя удалять через приложение", 403)

    busy = running_blockers(blockers, running)
    if busy:
        return fail("Сначала закройте: " + ", ".join(busy), 409)

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
            freed, remaining = delete_item(item)
    elif kind == "temp":
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_smart_temp(item["path"]):
                return fail("Папка изменилась или больше не подходит под правила — пересканируйте", 409)
            freed, remaining = delete_item({"path": item["path"], "kind": "folder"})
    elif kind == "junk":
        if mock:
            freed = entry["size_gb"]
        else:
            if not scanners.verify_junk(item["path"], [f"{L}:\\" for L in scanned]):
                return fail("Папка больше не подходит под правила — пересканируйте", 409)
            freed, remaining = delete_item({"path": item["path"], "kind": "folder"})
    elif kind == "recycle":
        freed = entry["size_gb"]
        if not mock:
            letter = item["drive"]
            if not re.fullmatch(r"[A-Z]", letter):
                return fail("Неверный диск", 400)
            run_ps(f"Clear-RecycleBin -DriveLetter {letter} -Force -ErrorAction SilentlyContinue", timeout=120)
            remaining = scanners.scan_recycle(letter)
            freed = round(max(entry["size_gb"] - remaining, 0), 2)
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

    with _lock:
        d = scan_data
        if kind == "download":
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
    return {"ok": True, "id": item_id, "freed_gb": freed, "kind": kind, "remaining_gb": remaining}, 200


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
    freed = round(sum(r.get("freed_gb", 0) for r in results if r["ok"]), 2)
    return jsonify(ok=True, results=results, freed_gb=freed, failed=[r for r in results if not r["ok"]])


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
            webview.create_window(APP_NAME, url, width=1360, height=860, min_size=(1000, 640))
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
