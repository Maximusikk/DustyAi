"""Расширенные сканеры: умный Temp, установки Python, дубликаты файлов.
Всё, что может быть удалено, получает динамический id и регистрируется в реестре
(scan_data['dynamic']); перед удалением app.py заново проверяет путь через verify_*."""
import hashlib
import ntpath
import os
import re
import time

from util import IS_WINDOWS, expand, folder_size, gb, ps_json

TEMP_ROOTS = ["%TEMP%", "%LOCALAPPDATA%\\Temp"]
TEMP_PATTERNS = ("vs_", "setup", "installer")
TEMP_MIN_AGE_DAYS = 7
TEMP_MIN_MB = 10          # мельче — не шум
TEMP_BIG_MB = 500         # крупная старая папка без «говорящего» имени (вроде dtuv0qr3)
DUP_MIN_MB = 50
DUP_ROOTS = ["%USERPROFILE%\\Downloads", "%USERPROFILE%\\Documents"]
DUP_MAX_GROUPS = 20


def short_id(prefix, path):
    return prefix + hashlib.sha1(os.path.normcase(path).encode("utf-8", "replace")).hexdigest()[:10]


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


# ───────────────────────────── умный Temp ─────────────────────────────

def temp_roots():
    seen, roots = set(), []
    for r in TEMP_ROOTS:
        p = expand(r)
        if os.path.isdir(p) and _norm(p) not in seen:
            seen.add(_norm(p))
            roots.append(p)
    return roots


def temp_reason(name, size_bytes):
    low = name.lower()
    if any(p in low for p in TEMP_PATTERNS):
        return "Похоже на остатки установщика (по имени папки)."
    if size_bytes >= TEMP_BIG_MB * 1024 ** 2:
        return "Крупная папка, к которой не прикасались больше недели — вероятно, распакованный установщик."
    return None


def scan_smart_temp():
    now, items = time.time(), []
    for root in temp_roots():
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink() or not e.is_dir(follow_symlinks=False):
                    continue
                age = (now - e.stat().st_mtime) / 86400
            except OSError:
                continue
            if age < TEMP_MIN_AGE_DAYS:
                continue
            size = folder_size(e.path, 20)
            if size < TEMP_MIN_MB * 1024 ** 2:
                continue
            reason = temp_reason(e.name, size)
            if not reason:
                continue
            items.append(dict(
                id=short_id("tmp_", e.path), name=e.name, icon="📁", path=e.path, resolved=e.path,
                kind="folder", deletable=True, blockers=["vs_installer", "devenv"],
                size_gb=gb(size), exists=True, age_days=int(age), parent=root,
                desc=f"{reason} Не изменялась {int(age)} дн.",
                restore="Ничего: если установщик понадобится, он распакуется заново."))
    items.sort(key=lambda i: -i["size_gb"])
    return items


def verify_smart_temp(path):
    """Повторная проверка перед удалением: прямой потомок Temp, не ссылка, старше 7 дней."""
    try:
        if not os.path.isdir(path) or os.path.islink(path):
            return False
        parent = _norm(os.path.dirname(path))
        if parent not in {_norm(r) for r in temp_roots()}:
            return False
        return (time.time() - os.stat(path).st_mtime) / 86400 >= TEMP_MIN_AGE_DAYS
    except OSError:
        return False


# ───────────────────────────── Python ─────────────────────────────

PY_PATH_RE = re.compile(r"([A-Za-z]:\\[^\r\n]*?python[w]?\.exe)", re.I)
PY_VER_RE = re.compile(r"-V:(\S+)|-(\d+\.\d+(?:-\d+)?)")


def parse_py_list(text):
    """Разбор вывода `py -0p` → [(версия, папка установки)]."""
    result, seen = [], set()
    for line in text.splitlines():
        m = PY_PATH_RE.search(line)
        if not m:
            continue
        folder = ntpath.dirname(m.group(1))
        if folder.lower() in seen:
            continue
        seen.add(folder.lower())
        v = PY_VER_RE.search(line)
        result.append(((v.group(1) or v.group(2)) if v else "?", folder))
    return result


def top_packages(py_dir, n=5):
    sp = os.path.join(py_dir, "Lib", "site-packages")
    pkgs = []
    try:
        for e in os.scandir(sp):
            if e.is_dir(follow_symlinks=False) and not e.name.endswith((".dist-info", ".egg-info")) \
                    and e.name != "__pycache__":
                pkgs.append((e.name, round(folder_size(e.path, 10) / 1024 ** 2)))
    except OSError:
        pass
    return sorted(pkgs, key=lambda p: -p[1])[:n]


def scan_python():
    from util import run_ps
    out, _ = run_ps("py -0p")
    installs = parse_py_list(out)
    procs = ps_json("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'python' } | "
                    "Select Name,CommandLine | ConvertTo-Json -Compress")
    result = []
    for ver, folder in installs:
        low = folder.lower()
        users = [(p.get("CommandLine") or "")[:160] for p in procs if low in (p.get("CommandLine") or "").lower()]
        result.append(dict(
            version=ver, path=folder, size_gb=gb(folder_size(folder, 30)),
            packages=top_packages(folder), in_use=users,
            mcp=any("mcp" in u.lower() for u in users)))
    return result


# ───────────────────────────── дубликаты ─────────────────────────────

def md5_file(path, chunk=1024 * 1024, limit=None):
    h, read = hashlib.md5(), 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            read += len(b)
            if limit and read >= limit:
                break
    return h.hexdigest()


def dup_roots():
    return [expand(r) for r in DUP_ROOTS if os.path.isdir(expand(r))]


def scan_duplicates(deadline=90, progress=None):
    stop, by_size = time.monotonic() + deadline, {}
    min_bytes = DUP_MIN_MB * 1024 ** 2
    for root in dup_roots():
        for dirpath, dirs, files in os.walk(root):
            if time.monotonic() > stop:
                break
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))
                       and d not in ("node_modules", ".git", "venv", ".venv")]
            for f in files:
                p = os.path.join(dirpath, f)
                try:
                    if os.path.islink(p):
                        continue
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_size >= min_bytes:
                    by_size.setdefault(st.st_size, []).append((p, st.st_mtime))
    candidates = [(s, fl) for s, fl in by_size.items() if len(fl) > 1]
    groups = []
    for n, (size, files) in enumerate(candidates):
        if progress:
            progress(n, len(candidates))
        if time.monotonic() > stop:
            break
        by_hash = {}
        try:
            for p, mt in files:
                # быстрый отсев по первому мегабайту, затем полный хэш
                quick = md5_file(p, limit=1024 * 1024)
                by_hash.setdefault(quick, []).append((p, mt))
            for fl in by_hash.values():
                if len(fl) < 2:
                    continue
                full = {}
                for p, mt in fl:
                    full.setdefault(md5_file(p), []).append((p, mt))
                for h, same in full.items():
                    if len(same) > 1:
                        same.sort(key=lambda x: x[1])  # старейший — оригинал
                        groups.append(dict(
                            hash=h, size_gb=gb(size), wasted_gb=gb(size * (len(same) - 1)),
                            files=[dict(id=short_id("dup_", p), path=p,
                                        date=time.strftime("%Y-%m-%d", time.localtime(mt)),
                                        original=(i == 0)) for i, (p, mt) in enumerate(same)]))
        except OSError:
            continue
    groups.sort(key=lambda g: -g["wasted_gb"])
    return groups[:DUP_MAX_GROUPS]


def verify_duplicate(path, siblings):
    """Можно ли удалить файл: он в Downloads/Documents, а идентичная копия остаётся.
    siblings — пути остальных файлов группы."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        np = _norm(path)
        if not any(np.startswith(_norm(r) + os.sep) for r in dup_roots()):
            return False
        size, digest = os.path.getsize(path), None
        for s in siblings:
            if s != path and os.path.isfile(s) and not os.path.islink(s) and os.path.getsize(s) == size:
                digest = digest or md5_file(path)
                if md5_file(s) == digest:
                    return True
    except OSError:
        return False
    return False
