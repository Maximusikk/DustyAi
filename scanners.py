"""Расширенные сканеры: умный Temp, установки Python, дубликаты файлов.
Всё, что может быть удалено, получает динамический id и регистрируется в реестре
(scan_data['dynamic']); перед удалением app.py заново проверяет путь через verify_*."""
import hashlib
import ntpath
import os
import re
import time

from concurrent.futures import ThreadPoolExecutor

from util import IS_WINDOWS, expand, folder_size, folder_size_ex, gb, ps_json

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


def scan_duplicates(deadline=45, progress=None, roots=None):
    stop, by_size = time.monotonic() + deadline, {}
    min_bytes = DUP_MIN_MB * 1024 ** 2
    for root in (roots if roots is not None else dup_roots()):
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


# ───────────────────────────── обзор диска ─────────────────────────────

JUNK_NAMES = {"node_modules": "Зависимости Node.js", ".venv": "Виртуальное окружение Python",
              "venv": "Виртуальное окружение Python", "__pycache__": "Скомпилированный кэш Python",
              ".tox": "Окружения tox"}
JUNK_MIN_MB = 50
BIG_FILE_MB = 500
# на несистемных дисках пропускаем только служебное; на системном — ещё сам Windows (его не чистят руками)
SKIP_TOP = {"$recycle.bin", "system volume information", "recovery", "$windows.~bt", "$windows.~ws",
            "config.msi", "msocache", "$winreagent"}
SKIP_TOP_SYSTEM = SKIP_TOP | {"windows"}
ROOT_FILES = "(файлы в корне диска)"

FILE_KINDS = [  # (расширения, подпись, иконка)
    ({".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".h5", ".tflite"}, "ИИ-модель (веса)", "🧠"),
    ({".vhd", ".vhdx", ".vmdk", ".vdi", ".qcow2"}, "Образ виртуального диска (ВМ/WSL/Docker)", "💽"),
    ({".iso", ".img", ".wim", ".esd"}, "Образ диска / установщик системы", "📀"),
    ({".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".bz2"}, "Архив", "🗜️"),
    ({".dmp", ".mdmp", ".hdmp"}, "Дамп памяти", "💥"),
    ({".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"}, "Видео", "🎞️"),
    ({".exe", ".msi", ".msix", ".appx"}, "Установщик / программа", "📦"),
    ({".bin"}, "Бинарный файл (часто веса модели или данные игры)", "📄"),
    ({".bak", ".old", ".tmp", ".log"}, "Резервная копия / временный / лог", "🗃️"),
    ({".sys"}, "Системный файл (подкачка/гибернация) — не удалять вручную", "🔒"),
]


def classify_file(name):
    ext = os.path.splitext(name)[1].lower()
    for exts, label, icon in FILE_KINDS:
        if ext in exts:
            return label, icon
    return "Файл", "📄"


def protected_prefixes():
    """Папки установленных программ и системы: node_modules/venv внутри них — часть самих программ
    (например Electron-приложений), удалять их нельзя."""
    raw = [expand(r) for r in ("%ProgramFiles%", "%ProgramFiles(x86)%", "%ProgramData%", "%SystemRoot%")]
    profile = expand("%USERPROFILE%")
    raw.append(os.path.join(profile, "AppData"))
    return [os.path.normcase(p) for p in raw if "%" not in p]


def junk_allowed(path):
    p = os.path.normcase(path)
    return not any(p == pre or p.startswith(pre + os.sep) for pre in protected_prefixes())


def _reparse(e):
    """Junction/symlink: не заходим, иначе посчитаем одно и то же дважды или уйдём в цикл."""
    try:
        return e.is_symlink() or bool(e.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


def _walk(path, stop):
    """Обход одной ветки. Возвращает (размер, крупные файлы, мусор разработчика, оборвано ли по времени)."""
    size, big, junk, cut = 0, [], [], False
    stack = [path]
    while stack:
        if time.monotonic() > stop:
            return size, big, junk, True
        try:
            it = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in it:
            try:
                if _reparse(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name.lower() in JUNK_NAMES and junk_allowed(e.path):
                        js = folder_size(e.path, 30)
                        size += js
                        if js >= JUNK_MIN_MB * 1024 ** 2:
                            junk.append(dict(id=short_id("junk_", e.path), name=e.name, path=e.path,
                                             what=JUNK_NAMES[e.name.lower()], size=js))
                    else:
                        stack.append(e.path)
                else:
                    st = e.stat(follow_symlinks=False)
                    sz = st.st_size
                    size += sz
                    if sz >= BIG_FILE_MB * 1024 ** 2:
                        big.append(dict(id=short_id("big_", e.path), name=e.name, path=e.path, size=sz, mt=st.st_mtime))
            except OSError:
                continue
    return size, big, junk, cut


def scan_drive_deep(letter, deadline=90, system=False, workers=8, root=None):
    """Обход диска целиком: крупнейшие папки верхнего уровня, крупные файлы с типом, мусор разработчика.
    Работает параллельно: корень и папки второго уровня (например, каждый профиль в Users) идут отдельными
    задачами. Не пересекает junction, общий лимит по времени. На системном диске пропускает сам Windows."""
    root = root or f"{letter}:\\"
    skip = SKIP_TOP_SYSTEM if system else SKIP_TOP
    stop = time.monotonic() + deadline
    top, big, junk, partial, jobs = {}, [], [], False, []

    def add(tn, size):
        top[tn] = top.get(tn, 0) + size

    try:
        entries = list(os.scandir(root))
    except OSError:
        entries = []
    for e in entries:
        try:
            if _reparse(e):
                continue
            if e.is_dir(follow_symlinks=False):
                if e.name.lower() in skip:
                    continue
                try:  # второй уровень: больше параллелизма там, где одна папка огромна (Users, Program Files)
                    kids = list(os.scandir(e.path))
                except OSError:
                    continue
                for k in kids:
                    if _reparse(k):
                        continue
                    if k.is_dir(follow_symlinks=False):
                        jobs.append((e.name, k.path))
                    else:
                        st = k.stat(follow_symlinks=False)
                        sz = st.st_size
                        add(e.name, sz)
                        if sz >= BIG_FILE_MB * 1024 ** 2:
                            big.append(dict(id=short_id("big_", k.path), name=k.name, path=k.path, size=sz, mt=st.st_mtime))
            else:
                st = e.stat(follow_symlinks=False)
                sz = st.st_size
                add(ROOT_FILES, sz)
                if sz >= BIG_FILE_MB * 1024 ** 2:
                    big.append(dict(id=short_id("big_", e.path), name=e.name, path=e.path, size=sz, mt=st.st_mtime))
        except OSError:
            continue
    # папка уровня 1 с файлами, но без подпапок, всё равно должна попасть в список
    for e in entries:
        if e.is_dir(follow_symlinks=False) and e.name.lower() not in skip:
            top.setdefault(e.name, 0)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (tn, _), (sz, b, j, cut) in zip(jobs, ex.map(lambda job: _walk(job[1], stop), jobs)):
            add(tn, sz)
            big += b
            junk += j
            partial |= cut
    top_dirs = [dict(name=n, path=(root + n) if n != ROOT_FILES else root, size_gb=gb(s))
                for n, s in sorted(top.items(), key=lambda x: -x[1])[:(20 if system else 12)] if s > 0]
    big.sort(key=lambda f: -f["size"])
    junk.sort(key=lambda j: -j["size"])
    big_out = []
    for f in big[:20]:
        label, icon = classify_file(f["name"])
        mt = f.pop("mt", None)
        big_out.append(dict(f, size_gb=gb(f.pop("size")), kind=label, icon=icon,
                            date=time.strftime("%Y-%m-%d", time.localtime(mt)) if mt else "",
                            age_days=int((time.time() - mt) / 86400) if mt else None))
    return dict(top_dirs=top_dirs, partial=partial, big_files=big_out,
                junk=[dict(j, size_gb=gb(j.pop("size"))) for j in junk[:40]])


def scan_recycle(letter):
    return gb(folder_size(f"{letter}:\\$Recycle.Bin", 30))


def verify_junk(path, allowed_roots):
    """Удаляем только папки с «мусорным» именем на отсканированном диске, не ссылки."""
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            return False
        if os.path.basename(path.rstrip("\\/")).lower() not in JUNK_NAMES or not junk_allowed(path):
            return False
        np = _norm(path)
        return any(np.startswith(_norm(r)) for r in allowed_roots)
    except OSError:
        return False


# ───────────────────────────── Загрузки ─────────────────────────────

DL_MIN_MB = 50
DL_TOP = 25
INSTALLER_EXT = {".exe", ".msi", ".iso", ".zip", ".7z", ".rar", ".msix", ".appx", ".dmg", ".img"}


def downloads_root():
    return expand("%USERPROFILE%\\Downloads")


def scan_downloads(deadline=30):
    """Крупнейшие файлы в Загрузках с датами — пользователь сам решает, что из этого ещё нужно."""
    root, now, stop = downloads_root(), time.time(), time.monotonic() + deadline
    files = []
    for dirpath, dirs, names in os.walk(root):
        if time.monotonic() > stop:
            break
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
        for n in names:
            p = os.path.join(dirpath, n)
            try:
                if os.path.islink(p):
                    continue
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size >= DL_MIN_MB * 1024 ** 2:
                files.append((p, n, st.st_size, st.st_mtime))
    files.sort(key=lambda f: -f[2])
    return [dict(id=short_id("dl_", p), name=n, path=p, size_gb=gb(sz), date=time.strftime("%Y-%m-%d", time.localtime(mt)),
                 age_days=int((now - mt) / 86400), installer=os.path.splitext(n)[1].lower() in INSTALLER_EXT)
            for p, n, sz, mt in files[:DL_TOP]]


def verify_download(path):
    """Файл должен лежать внутри Загрузок и не быть ссылкой."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        return _norm(path).startswith(_norm(downloads_root()) + os.sep)
    except OSError:
        return False


# ───────────────────────── обзор профиля и AppData ─────────────────────────

PROFILE_ROOTS = [("Профиль пользователя", "%USERPROFILE%", {"appdata"}),
                 ("AppData\\Local", "%LOCALAPPDATA%", set()),
                 ("AppData\\Roaming", "%APPDATA%", set())]


def scan_profile_overview(top=12, deadline=25):
    """Крупнейшие папки профиля. Только показываем — ничего заранее не помечаем как мусор:
    так видно любые «жирные» программы, о которых каталог не знает."""
    groups = []
    for title, env, skip in PROFILE_ROOTS:
        root = expand(env)
        try:
            kids = [e for e in os.scandir(root) if e.is_dir(follow_symlinks=False) and not _reparse(e)
                    and e.name.lower() not in skip]
        except OSError:
            continue
        with ThreadPoolExecutor(max_workers=8) as ex:
            sized = list(ex.map(lambda e: (e, *folder_size_ex(e.path, deadline)), kids))
        sized.sort(key=lambda x: -x[1])
        items = [dict(id=short_id("pf_", e.path), name=e.name, path=e.path, size_gb=gb(sz), partial=cut)
                 for e, sz, cut in sized[:top] if sz > 0]
        groups.append(dict(title=title, root=root, entries=items))
    return groups


BIG_NEVER_EXT = {".sys", ".dll"}
BIG_MIN_DELETE_MB = 100


def big_deletable(path):
    """Можно ли предлагать удаление крупного файла. Не из папок программ и системы и не системные типы:
    внутри них лежат данные установленных приложений (игры, WSL-диски в AppData, драйверы)."""
    if os.path.splitext(path)[1].lower() in BIG_NEVER_EXT:
        return False, "системный тип файла"
    p = os.path.normcase(path)
    if any(p.startswith(pre + os.sep) for pre in protected_prefixes()):
        return False, "лежит в папке программ или системы (Program Files, ProgramData, AppData, Windows)"
    if os.path.basename(p) in ("pagefile.sys", "hiberfil.sys", "swapfile.sys"):
        return False, "системный файл"
    return True, ""


def verify_bigfile(path):
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
        return big_deletable(path)[0] and os.path.getsize(path) >= BIG_MIN_DELETE_MB * 1024 ** 2
    except OSError:
        return False
