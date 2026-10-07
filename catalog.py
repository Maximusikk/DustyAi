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

# Вычищаем только эти id — это и есть белый список для POST /delete
ALL_ITEMS = {i["id"]: i for i in SAFE + REVIEW}
DELETABLE_IDS = {i["id"] for i in ALL_ITEMS.values() if i["deletable"]}

# id → зона риска
ZONE = {**{i["id"]: "safe" for i in SAFE}, **{i["id"]: "review" for i in REVIEW}}

# Процессы, которые нельзя трогать при чистке любых данных
GLOBAL_BLOCKERS = ["vs_installer", "devenv", "idea64", "pycharm64", "code"]

MOCK = {
    "drives": [
        {"Name": "C", "UsedGB": 362.0, "FreeGB": 103.0, "TotalGB": 465.0},
        {"Name": "D", "UsedGB": 120.5, "FreeGB": 340.0, "TotalGB": 460.5},
    ],
    "sizes": {"user_temp": 1.4, "local_temp": 5.3, "crash_dumps": 0.3, "windows_temp": 0.6,
              "pip_cache": 0.9, "gradle_cache": 3.1, "npm_cache": 0.3, "nuget_cache": 1.2,
              "cargo_registry": 0.8, "arduino_staging": 2.35, "huggingface_cache": 1.2,
              "playwright_browsers": 3.8, "ollama_models": 7.6},
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
