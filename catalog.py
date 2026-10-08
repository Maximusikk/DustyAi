"""Каталог известных мест, где копится мусор. Единственный источник путей:
клиент присылает только id, путь всегда берётся отсюда."""

# kind: "contents" — удаляем содержимое, корень оставляем; "folder" — удаляем папку целиком
# deletable: можно ли удалять через API
# blockers: процессы, при которых удаление запрещено
SAFE = [
    dict(id="user_temp", name="Временные файлы пользователя", icon="🗑️", path="%TEMP%",
         kind="contents", deletable=True, blockers=["vs_installer", "devenv"],
         desc="Файлы, которые программы создали на время работы и не убрали за собой.",
         restore="Ничего — программы создадут нужные файлы заново."),
    dict(id="local_temp", name="Локальный Temp", icon="🗑️", path="%LOCALAPPDATA%\\Temp",
         kind="contents", deletable=True, blockers=["vs_installer", "devenv"],
         desc="Остатки установщиков (например Visual Studio), распакованные архивы, логи.",
         restore="Ничего. Занятые файлы Windows просто пропустит."),
    dict(id="crash_dumps", name="Дампы сбоев", icon="💥", path="%LOCALAPPDATA%\\CrashDumps",
         kind="contents", deletable=True, blockers=[],
         desc="Снимки памяти упавших программ. Нужны только для отладки.",
         restore="Ничего. Новые дампы появятся только при новых сбоях."),
    dict(id="windows_temp", name="Системный Temp", icon="🗑️", path="%SystemRoot%\\Temp",
         kind="contents", deletable=True, blockers=["vs_installer"],
         desc="Временные файлы Windows и служб. Часть файлов может требовать прав администратора.",
         restore="Ничего."),
    dict(id="pip_cache", icon_src=['%LOCALAPPDATA%\\Programs\\Python\\Python3*\\python.exe', 'C:\\Python3*\\python.exe'], name="Кэш pip", icon="🐍", path="%LOCALAPPDATA%\\pip\\Cache",
         kind="folder", deletable=True, blockers=[],
         desc="Скачанные ранее wheel-пакеты Python.",
         restore="pip скачает пакеты заново при следующей установке."),
]

REVIEW = [
    dict(id="gradle_cache", icon_src=['%ProgramFiles%\\Android\\Android Studio\\bin\\studio64.exe', '%ProgramFiles%\\JetBrains\\*\\bin\\idea64.exe'], name="Кэш Gradle", icon="🐘", path="%USERPROFILE%\\.gradle\\caches",
         kind="folder", deletable=True, blockers=["idea64", "studio64", "java"],
         desc="Скачанные зависимости и артефакты сборки Gradle/Android.",
         restore="Gradle скачает зависимости заново — следующая сборка будет долгой."),
    dict(id="npm_cache", icon_src=['%ProgramFiles%\\nodejs\\node.exe'], name="Кэш npm", icon="📦", path="%APPDATA%\\npm-cache",
         kind="folder", deletable=True, blockers=["node", "npm"],
         desc="Кэш скачанных npm-пакетов.",
         restore="npm скачает пакеты заново."),
    dict(id="nuget_cache", icon_src=['%ProgramFiles%\\dotnet\\dotnet.exe'], name="Пакеты NuGet", icon="🟣", path="%USERPROFILE%\\.nuget\\packages",
         kind="folder", deletable=True, blockers=["devenv", "dotnet"],
         desc="Глобальные пакеты .NET для всех проектов.",
         restore="dotnet restore скачает всё заново."),
    dict(id="cargo_registry", icon_src=['%USERPROFILE%\\.cargo\\bin\\cargo.exe'], name="Реестр Cargo", icon="🦀", path="%USERPROFILE%\\.cargo\\registry",
         kind="folder", deletable=True, blockers=["cargo", "rustc"],
         desc="Исходники и индекс скачанных Rust-крейтов.",
         restore="cargo скачает крейты заново при сборке."),
    dict(id="arduino_staging", icon_src=['%LOCALAPPDATA%\\Programs\\Arduino IDE\\Arduino IDE.exe', '%ProgramFiles%\\Arduino IDE\\Arduino IDE.exe'], name="Arduino staging", icon="🔌", path="%LOCALAPPDATA%\\Arduino15\\staging",
         kind="folder", deletable=True, blockers=["arduino", "Arduino IDE"],
         desc="Скачанные архивы плат и библиотек — после установки они не нужны.",
         restore="Ничего — установленные платы остаются."),
    dict(id="huggingface_cache", name="Модели Hugging Face", icon="🤗", path="%USERPROFILE%\\.cache\\huggingface",
         kind="folder", deletable=False, blockers=[],
         desc="Скачанные ИИ-модели. Решите, какие из них вам ещё нужны.",
         restore="Модели придётся скачать заново (иногда это гигабайты)."),
    dict(id="playwright_browsers", icon_src=['%LOCALAPPDATA%\\ms-playwright\\chromium-*\\chrome-win\\chrome.exe'], name="Браузеры Playwright", icon="🎭", path="%LOCALAPPDATA%\\ms-playwright",
         kind="folder", deletable=False, blockers=[],
         desc="Chromium/Firefox/WebKit для e2e-тестов. Нужны, только если вы запускаете Playwright.",
         restore="Восстановится командой `playwright install`."),
    dict(id="ollama_models", icon_src=['%LOCALAPPDATA%\\Programs\\Ollama\\ollama app.exe'], name="Модели Ollama", icon="🦙", path="%USERPROFILE%\\.ollama\\models",
         kind="folder", deletable=False, blockers=[],
         desc="Локальные языковые модели. Удаляйте через `ollama rm <модель>`.",
         restore="Модели скачиваются заново командой `ollama pull`."),
]

DO_NOT_TOUCH = [
    dict(name="pagefile.sys", icon="🔒", reason="Файл подкачки Windows. Удаление ломает систему."),
    dict(name="Windows\\Installer", icon="🔒", reason="Кэш MSI-установщиков: без него не удалить и не обновить программы."),
    dict(name="ProgramData\\Package Cache", icon="🔒", reason="Нужен деинсталляторам и обновлениям Visual Studio, .NET и др."),
    dict(name="Claude vm_bundles", icon="🔒", reason="Данные виртуальной машины Claude."),
    dict(name="WSL ext4.vhdx", icon="🔒", reason="Диск Linux-дистрибутива WSL. Внутри ваши файлы."),
    dict(name="Профили браузеров", icon="🔒", reason="Пароли, закладки и сессии."),
]


SAFE += [
    {'id': 'd3d_cache', 'name': 'Кэш шейдеров DirectX', 'icon': '🎮', 'path': '%LOCALAPPDATA%\\D3DSCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Скомпилированные шейдеры игр и приложений.', 'restore': 'Пересоздаётся при запуске игр — первые минуты возможны микрофризы.'},
    {'id': 'nvidia_cache', 'name': 'Кэш шейдеров NVIDIA', 'icon': '🟩', 'path': '%LOCALAPPDATA%\\NVIDIA\\DXCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Шейдерный кэш видеодрайвера NVIDIA.', 'restore': 'Драйвер пересоздаст его сам.'},
    {'id': 'wer_reports', 'name': 'Отчёты об ошибках Windows', 'icon': '📋', 'path': '%LOCALAPPDATA%\\Microsoft\\Windows\\WER', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Архив отчётов о сбоях программ, которые Windows собирает для отправки в Microsoft.', 'restore': 'Ничего. Новые отчёты появятся только при новых сбоях.'},
    {'id': 'inet_cache', 'name': 'Кэш Internet Explorer / WebView', 'icon': '🌐', 'path': '%LOCALAPPDATA%\\Microsoft\\Windows\\INetCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Кэш страниц и картинок встроенных веб-компонентов Windows.', 'restore': 'Скачается заново при необходимости.'},
    {'id': 'vscode_vsix', 'name': 'Кэш расширений VS Code (VSIX)', 'icon': '🧩', 'path': '%APPDATA%\\Code\\CachedExtensionVSIXs', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Скачанные установщики расширений — после установки не нужны.', 'restore': 'VS Code скачает заново при переустановке расширения.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'vscode_cached', 'name': 'Кэш данных VS Code', 'icon': '🧩', 'path': '%APPDATA%\\Code\\CachedData', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Скомпилированный кэш кода редактора.', 'restore': 'VS Code пересоздаст при запуске.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'vscode_logs', 'name': 'Логи VS Code', 'icon': '🧩', 'path': '%APPDATA%\\Code\\logs', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Журналы работы редактора и расширений.', 'restore': 'Ничего.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'chrome_ai_model', 'name': 'Встроенная ИИ-модель Chrome', 'icon': '🧠', 'path': '%LOCALAPPDATA%\\Google\\Chrome\\User Data\\OptGuideOnDeviceModel', 'kind': 'folder', 'deletable': True, 'blockers': ['chrome'], 'desc': 'Локальная языковая модель Chrome (до нескольких ГБ). Не профиль и не закладки.', 'restore': 'Chrome может скачать её снова; отключается в настройках Chrome.', 'icon_src': ['%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe', '%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe']},
]

REVIEW += [
    {'id': 'npm_cache_local', 'name': 'Кэш npm (Local)', 'icon': '📦', 'path': '%LOCALAPPDATA%\\npm-cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'npm'], 'desc': 'Основной кэш npm на современных версиях: скачанные пакеты.', 'restore': 'npm скачает пакеты заново.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'pnpm_cache', 'name': 'Кэш pnpm', 'icon': '📦', 'path': '%LOCALAPPDATA%\\pnpm-cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'pnpm'], 'desc': 'Метаданные и кэш пакетов pnpm.', 'restore': 'pnpm скачает заново.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'yarn_cache', 'name': 'Кэш Yarn', 'icon': '🧶', 'path': '%LOCALAPPDATA%\\Yarn\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'yarn'], 'desc': 'Кэш скачанных пакетов Yarn.', 'restore': 'Yarn скачает заново.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'go_build', 'name': 'Кэш сборки Go', 'icon': '🐹', 'path': '%LOCALAPPDATA%\\go-build', 'kind': 'folder', 'deletable': True, 'blockers': ['go'], 'desc': 'Результаты предыдущих сборок Go.', 'restore': 'Следующая сборка будет дольше, дальше всё вернётся.', 'icon_src': ['%ProgramFiles%\\Go\\bin\\go.exe']},
    {'id': 'maven_repo', 'name': 'Репозиторий Maven', 'icon': '☕', 'path': '%USERPROFILE%\\.m2\\repository', 'kind': 'folder', 'deletable': True, 'blockers': ['java', 'mvn', 'idea64'], 'desc': 'Все скачанные Java-зависимости.', 'restore': 'Maven скачает зависимости при следующей сборке.'},
    {'id': 'uv_cache', 'name': 'Кэш uv', 'icon': '🐍', 'path': '%LOCALAPPDATA%\\uv\\cache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Кэш менеджера пакетов Python uv.', 'restore': 'uv скачает пакеты заново.'},
    {'id': 'poetry_cache', 'name': 'Кэш Poetry', 'icon': '🐍', 'path': '%LOCALAPPDATA%\\pypoetry\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['poetry'], 'desc': 'Кэш пакетов и виртуальных окружений Poetry.', 'restore': 'Poetry пересоздаст при установке.'},
    {'id': 'conda_pkgs', 'name': 'Пакеты conda', 'icon': '🐍', 'path': '%USERPROFILE%\\.conda\\pkgs', 'kind': 'folder', 'deletable': True, 'blockers': ['conda'], 'desc': 'Кэш распакованных пакетов conda.', 'restore': 'conda скачает пакеты при создании окружения.'},
    {'id': 'composer_cache', 'name': 'Кэш Composer (PHP)', 'icon': '🐘', 'path': '%LOCALAPPDATA%\\Composer', 'kind': 'folder', 'deletable': True, 'blockers': ['php', 'composer'], 'desc': 'Кэш пакетов PHP-менеджера Composer.', 'restore': 'Composer скачает заново.'},
    {'id': 'pub_cache', 'name': 'Кэш Dart/Flutter pub', 'icon': '🎯', 'path': '%LOCALAPPDATA%\\Pub\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['dart', 'flutter'], 'desc': 'Скачанные пакеты Dart и Flutter.', 'restore': '`flutter pub get` скачает заново.'},
    {'id': 'puppeteer_cache', 'name': 'Браузеры Puppeteer', 'icon': '🎭', 'path': '%USERPROFILE%\\.cache\\puppeteer', 'kind': 'folder', 'deletable': True, 'blockers': ['node'], 'desc': 'Chrome, который скачал Puppeteer для автотестов.', 'restore': 'Скачается при следующем запуске Puppeteer.'},
    {'id': 'cypress_cache', 'name': 'Бинарники Cypress', 'icon': '🌲', 'path': '%LOCALAPPDATA%\\Cypress\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['Cypress', 'node'], 'desc': 'Скачанные версии Cypress.', 'restore': '`npx cypress install` скачает заново.'},
]

from catalog_extra import REVIEW_EXTRA, SAFE_EXTRA  # noqa: E402

SAFE += SAFE_EXTRA
REVIEW += REVIEW_EXTRA


def item_patterns(item):
    """Все шаблоны путей пункта (переменные окружения и `*` раскрывает util.expand_all)."""
    return [item["path"], *item.get("also", [])]


# Вычищаем только эти id — это и есть белый список для POST /delete
ALL_ITEMS = {i["id"]: i for i in SAFE + REVIEW}
DELETABLE_IDS = {i["id"] for i in ALL_ITEMS.values() if i["deletable"]}

# id → зона риска
ZONE = {**{i["id"]: "safe" for i in SAFE}, **{i["id"]: "review" for i in REVIEW}}

# Процессы, которые нельзя трогать при чистке любых данных
GLOBAL_BLOCKERS = ["vs_installer", "devenv", "idea64", "pycharm64", "code"]

MOCK = {
    "drives": [
        {"Name": "C", "Label": "Windows", "Type": "local", "UsedGB": 362.0, "FreeGB": 103.0, "TotalGB": 465.0, "scannable": True},
        {"Name": "D", "Label": "Data", "Type": "local", "UsedGB": 420.5, "FreeGB": 340.0, "TotalGB": 760.5, "scannable": True},
        {"Name": "Z", "Label": "NAS", "Type": "network", "UsedGB": 1800.0, "FreeGB": 2200.0, "TotalGB": 4000.0, "scannable": False},
    ],
    "sizes": {"user_temp": 1.4, "local_temp": 5.3, "crash_dumps": 0.3, "windows_temp": 0.6,
              "pip_cache": 0.9, "gradle_cache": 3.1, "npm_cache": 0.3, "nuget_cache": 1.2,
              "cargo_registry": 0.8, "arduino_staging": 2.35, "huggingface_cache": 1.2,
              "playwright_browsers": 3.8, "ollama_models": 7.6,
              "go_build": 3.1, "npm_cache_local": 0.94, "pnpm_cache": 1.0, "chrome_ai_model": 4.0,
              "vscode_vsix": 0.4, "firefox_cache": 0.4, "telegram_cache": 2.1, "slack_cache": 0.5, "steam_shadercache": 3.4,
              "windows_update_dl": 2.8, "jetbrains_caches": 4.2, "adobe_media_cache": 6.5, "minidump": 0.6, "brave_cache": 0.3, "d3d_cache": 0.5, "chrome_cache": 0.7, "maven_repo": 2.2},
    "programs": [
        {"DisplayName": "Visual Studio Community 2022", "DisplayVersion": "17.9", "SizeMB": 9800},
        {"DisplayName": "Windows Software Development Kit", "DisplayVersion": "10.0.22621", "SizeMB": 2300},
        {"DisplayName": "Android Studio", "DisplayVersion": "2024.1", "SizeMB": 1900},
        {"DisplayName": "LDPlayer 9", "DisplayVersion": "9.0", "SizeMB": 3000},
    ],
}

MOCK["smart_temp"] = [
    {"name": "dtuv0qr3", "path": "C:\\Users\\demo\\AppData\\Local\\Temp\\dtuv0qr3", "size_gb": 5.3, "age_days": 41,
     "reason": "Крупная папка, к которой не прикасались больше недели — вероятно, распакованный установщик."},
    {"name": "vs_installer_9f2a", "path": "C:\\Users\\demo\\AppData\\Local\\Temp\\vs_installer_9f2a", "size_gb": 0.4,
     "age_days": 12, "reason": "Похоже на остатки установщика (по имени папки)."},
]
MOCK["python"] = [
    {"version": "3.13", "path": "C:\\Python313", "size_gb": 1.9,
     "packages": [["torch", 1200], ["numpy", 60], ["pip", 12]], "in_use": [], "mcp": False},
    {"version": "3.12", "path": "C:\\Python312", "size_gb": 0.2, "packages": [["mcp", 8], ["pip", 12]],
     "in_use": ["C:\\Python312\\python.exe -m mcp_server_fetch"], "mcp": True},
    {"version": "3.11", "path": "C:\\Python311", "size_gb": 6.9, "packages": [["torch", 4500], ["scipy", 110]],
     "in_use": [], "mcp": False},
]
MOCK["dups"] = [
    {"size_gb": 1.8, "wasted_gb": 1.8, "files": [
        {"path": "C:\\Users\\demo\\Downloads\\ubuntu-24.04.iso", "date": "2025-11-02", "original": True},
        {"path": "C:\\Users\\demo\\Downloads\\ubuntu-24.04 (1).iso", "date": "2025-11-20", "original": False}]},
    {"size_gb": 0.6, "wasted_gb": 1.2, "files": [
        {"path": "C:\\Users\\demo\\Documents\\backup.zip", "date": "2025-08-01", "original": True},
        {"path": "C:\\Users\\demo\\Downloads\\backup.zip", "date": "2025-09-14", "original": False},
        {"path": "C:\\Users\\demo\\Downloads\\backup (2).zip", "date": "2025-10-01", "original": False}]},
]

MOCK["recycle"] = {"C": 0.4, "D": 1.1}
MOCK["deep"] = {
    "D": {"partial": False,
          "top_dirs": [
              {"name": "Games", "path": "D:\\Games", "size_gb": 182.4},
              {"name": "Projects", "path": "D:\\Projects", "size_gb": 96.1},
              {"name": "VMs", "path": "D:\\VMs", "size_gb": 74.8},
              {"name": "Backup", "path": "D:\\Backup", "size_gb": 41.3},
              {"name": "Video", "path": "D:\\Video", "size_gb": 22.7}],
          "big_files": [
              {"name": "win11.vdi", "path": "D:\\VMs\\win11.vdi", "size_gb": 38.0},
              {"name": "backup-2025.zip", "path": "D:\\Backup\\backup-2025.zip", "size_gb": 12.6},
              {"name": "render_final.mov", "path": "D:\\Video\\render_final.mov", "size_gb": 8.9}],
          "junk": [
              {"name": "node_modules", "path": "D:\\Projects\\shop\\node_modules", "what": "Зависимости Node.js", "size_gb": 1.4},
              {"name": "node_modules", "path": "D:\\Projects\\blog\\node_modules", "what": "Зависимости Node.js", "size_gb": 0.9},
              {"name": ".venv", "path": "D:\\Projects\\ml\\.venv", "what": "Виртуальное окружение Python", "size_gb": 5.2}]},
}

MOCK["downloads"] = [
    {"name": "Windows11_24H2.iso", "path": "C:\\Users\\demo\\Downloads\\Windows11_24H2.iso", "size_gb": 5.4, "date": "2025-06-12", "age_days": 482, "installer": True},
    {"name": "Docker Desktop Installer.exe", "path": "C:\\Users\\demo\\Downloads\\Docker Desktop Installer.exe", "size_gb": 0.6, "date": "2025-09-03", "age_days": 399, "installer": True},
    {"name": "conference_recording.mp4", "path": "C:\\Users\\demo\\Downloads\\conference_recording.mp4", "size_gb": 3.2, "date": "2026-09-30", "age_days": 7, "installer": False},
    {"name": "dataset_v2.zip", "path": "C:\\Users\\demo\\Downloads\\dataset_v2.zip", "size_gb": 2.1, "date": "2026-03-18", "age_days": 203, "installer": True},
]
MOCK["profile"] = [
    {"title": "Профиль пользователя", "root": "C:\\Users\\demo", "entries": [
        {"name": "Downloads", "path": "C:\\Users\\demo\\Downloads", "size_gb": 31.0, "partial": False},
        {"name": "Documents", "path": "C:\\Users\\demo\\Documents", "size_gb": 7.1, "partial": False},
        {"name": ".gradle", "path": "C:\\Users\\demo\\.gradle", "size_gb": 3.1, "partial": False},
        {"name": ".minecraft", "path": "C:\\Users\\demo\\.minecraft", "size_gb": 4.3, "partial": False}]},
    {"title": "AppData\\Local", "root": "C:\\Users\\demo\\AppData\\Local", "entries": [
        {"name": "JetBrains", "path": "C:\\Users\\demo\\AppData\\Local\\JetBrains", "size_gb": 5.1, "partial": False},
        {"name": "Programs", "path": "C:\\Users\\demo\\AppData\\Local\\Programs", "size_gb": 4.4, "partial": False},
        {"name": "pnpm", "path": "C:\\Users\\demo\\AppData\\Local\\pnpm", "size_gb": 3.6, "partial": False}]},
    {"title": "AppData\\Roaming", "root": "C:\\Users\\demo\\AppData\\Roaming", "entries": [
        {"name": "Tencent", "path": "C:\\Users\\demo\\AppData\\Roaming\\Tencent", "size_gb": 5.5, "partial": False},
        {"name": "DingTalk", "path": "C:\\Users\\demo\\AppData\\Roaming\\DingTalk", "size_gb": 4.3, "partial": True}]},
]

MOCK["deep"]["C"] = {"partial": False,
    "top_dirs": [
        {"name": "Users", "path": "C:\\Users", "size_gb": 96.4},
        {"name": "Program Files", "path": "C:\\Program Files", "size_gb": 41.2},
        {"name": "llama", "path": "C:\\llama", "size_gb": 17.3},
        {"name": "ProgramData", "path": "C:\\ProgramData", "size_gb": 12.8},
        {"name": "Program Files (x86)", "path": "C:\\Program Files (x86)", "size_gb": 9.6},
        {"name": "(файлы в корне диска)", "path": "C:\\", "size_gb": 7.9}],
    "big_files": [
        {"name": "qwen3-27b-q4_k_m.gguf", "path": "C:\\llama\\models\\qwen3-27b-q4_k_m.gguf", "size_gb": 16.4, "kind": "ИИ-модель (веса)", "icon": "🧠", "date": "2026-03-02", "age_days": 219},
        {"name": "pagefile.sys", "path": "C:\\pagefile.sys", "size_gb": 7.25, "date": "2026-10-07", "age_days": 0, "kind": "Системный файл (подкачка/гибернация) — не удалять вручную", "icon": "🔒"},
        {"name": "ext4.vhdx", "path": "C:\\Users\\demo\\AppData\\Local\\Packages\\wsl\\ext4.vhdx", "size_gb": 3.2, "date": "2026-08-14", "age_days": 54, "kind": "Образ виртуального диска (ВМ/WSL/Docker)", "icon": "💽"},
        {"name": "torch_cuda.dll", "path": "C:\\Python311\\Lib\\site-packages\\torch\\lib\\torch_cuda.dll", "size_gb": 0.9, "date": "2026-08-16", "age_days": 52, "kind": "Файл", "icon": "📄"},
        {"name": "llama-server-cuda.bin", "path": "C:\\llama\\llama-server-cuda.bin", "size_gb": 0.9, "date": "2026-03-02", "age_days": 219, "kind": "Бинарный файл (часто веса модели или данные игры)", "icon": "📄"}],
    "junk": [
        {"name": "node_modules", "path": "C:\\Users\\demo\\work\\site\\node_modules", "what": "Зависимости Node.js", "size_gb": 0.8}]}
