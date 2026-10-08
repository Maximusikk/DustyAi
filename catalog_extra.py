"""Расширение каталога: браузеры (все профили), мессенджеры, лаунчеры, IDE, Windows, кэши видео/игр.
Здесь только то, что программы пересоздают сами. Шаблоны: переменные окружения и `*` (все профили).
Пункты с deletable=False — не удаляются кнопкой, а объясняют, как почистить правильно."""

L = "%LOCALAPPDATA%\\"
R = "%APPDATA%\\"
U = "%USERPROFILE%\\"
PD = "%ProgramData%\\"
WIN = "%SystemRoot%\\"
EXE = {  # иконки приложений
    "chrome": ["%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe", "%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe"],
    "edge": ["%ProgramFiles(x86)%\\Microsoft\\Edge\\Application\\msedge.exe", "%ProgramFiles%\\Microsoft\\Edge\\Application\\msedge.exe"],
    "brave": ["%ProgramFiles%\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"],
    "firefox": ["%ProgramFiles%\\Mozilla Firefox\\firefox.exe"],
    "vscode": ["%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe", "%ProgramFiles%\\Microsoft VS Code\\Code.exe"],
}


def item(id, name, icon, path, desc, restore, blockers=(), also=(), kind="folder", deletable=True, icon_src=None):
    d = dict(id=id, name=name, icon=icon, path=path, kind=kind, deletable=deletable, blockers=list(blockers),
             desc=desc, restore=restore)
    if also:
        d["also"] = list(also)
    if icon_src:
        d["icon_src"] = icon_src
    return d


def chromium(id, name, user_data, blockers, icon_src=None, extra_root=()):
    """Кэши Chromium-браузера по всем профилям. Пароли, куки, историю и закладки не трогаем."""
    per = ["Cache", "Code Cache", "GPUCache", "DawnCache", "Service Worker\\CacheStorage", "Service Worker\\ScriptCache"]
    paths = [f"{user_data}\\*\\{p}" for p in per] + [f"{user_data}\\{p}" for p in
                                                      ("ShaderCache", "GrShaderCache", "GraphiteDawnCache", "component_crx_cache")]
    paths += list(extra_root)
    return item(id, f"Кэш {name} (все профили)", "🌐", paths[0],
                f"Кэш страниц, скомпилированного JS и графики {name} по всем профилям. Пароли, куки, история, закладки и расширения НЕ затрагиваются.",
                "Сайты загрузятся заново — первое открытие чуть медленнее. Входы на сайтах сохраняются.",
                blockers, also=paths[1:], icon_src=icon_src)


SAFE_EXTRA = [
    # ── браузеры ──
    chromium("chrome_cache", "Chrome", L + "Google\\Chrome\\User Data", ["chrome"], EXE["chrome"]),
    chromium("edge_cache", "Edge", L + "Microsoft\\Edge\\User Data", ["msedge"], EXE["edge"]),
    chromium("brave_cache", "Brave", L + "BraveSoftware\\Brave-Browser\\User Data", ["brave"], EXE["brave"]),
    chromium("vivaldi_cache", "Vivaldi", L + "Vivaldi\\User Data", ["vivaldi"]),
    chromium("yandex_cache", "Яндекс Браузера", L + "Yandex\\YandexBrowser\\User Data", ["browser", "yandex"]),
    chromium("opera_cache", "Opera", L + "Opera Software\\Opera Stable", ["opera"], extra_root=[
        L + "Opera Software\\Opera Stable\\Cache", L + "Opera Software\\Opera Stable\\Code Cache",
        L + "Opera Software\\Opera Stable\\GPUCache"]),
    chromium("operagx_cache", "Opera GX", L + "Opera Software\\Opera GX Stable", ["opera"], extra_root=[
        L + "Opera Software\\Opera GX Stable\\Cache", L + "Opera Software\\Opera GX Stable\\Code Cache",
        L + "Opera Software\\Opera GX Stable\\GPUCache"]),
    item("firefox_cache", "Кэш Firefox (все профили)", "🦊", L + "Mozilla\\Firefox\\Profiles\\*\\cache2",
         "Кэш страниц Firefox. Пароли, закладки и история лежат в другой папке (AppData\\Roaming) и не затрагиваются.",
         "Сайты загрузятся заново.", ["firefox"], also=[L + "Mozilla\\Firefox\\Profiles\\*\\startupCache",
                                                       L + "Mozilla\\Firefox\\Profiles\\*\\jumpListCache"], icon_src=EXE["firefox"]),
    item("zen_cache", "Кэш Zen Browser", "🌐", L + "zen\\Profiles\\*\\cache2",
         "Кэш страниц Zen. Профиль с паролями и закладками не затрагивается.", "Сайты загрузятся заново.", ["zen"]),

    # ── мессенджеры и приложения на Electron ──
    item("discord_cache", "Кэш Discord", "💬", R + "discord\\Cache", "Кэш картинок и вложений из чатов.",
         "Подгрузится заново при просмотре.", ["Discord"], also=[R + "discord\\Code Cache", R + "discord\\GPUCache"],
         icon_src=["%LOCALAPPDATA%\\Discord\\app-*\\Discord.exe"]),
    item("slack_cache", "Кэш Slack", "💼", R + "Slack\\Cache", "Кэш изображений и файлов из рабочих чатов. Сообщения хранятся на сервере.",
         "Slack подгрузит заново.", ["slack"], also=[R + "Slack\\Code Cache", R + "Slack\\GPUCache", R + "Slack\\Service Worker\\CacheStorage"]),
    item("teams_cache", "Кэш Microsoft Teams", "🟪", R + "Microsoft\\Teams\\Cache",
         "Кэш классического Teams: изображения, временные данные, GPU.", "Teams пересоздаст при запуске.",
         ["teams"], also=[R + "Microsoft\\Teams\\blob_storage", R + "Microsoft\\Teams\\Code Cache", R + "Microsoft\\Teams\\GPUCache",
                          R + "Microsoft\\Teams\\tmp", R + "Microsoft\\Teams\\Service Worker\\CacheStorage"]),
    item("teams_new_cache", "Кэш нового Teams", "🟪", L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\Cache",
         "Кэш веб-части нового Teams.", "Teams пересоздаст при запуске.", ["ms-teams", "teams"],
         also=[L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\Code Cache",
               L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\GPUCache"]),
    item("notion_cache", "Кэш Notion", "📝", R + "Notion\\Cache", "Кэш страниц и картинок. Ваши заметки лежат в облаке Notion.",
         "Notion подгрузит заново.", ["Notion"], also=[R + "Notion\\Code Cache", R + "Notion\\GPUCache"]),
    item("zoom_logs", "Логи Zoom", "🎥", R + "Zoom\\logs", "Журналы работы Zoom. Записи встреч и аккаунт не затрагиваются.",
         "Ничего.", ["Zoom"]),
    item("steam_html", "Кэш браузера Steam", "🎮", L + "Steam\\htmlcache", "Кэш встроенного браузера Steam (магазин, сообщество).",
         "Steam пересоздаст сам.", ["steam", "steamwebhelper"]),
    item("epic_cache", "Кэш Epic Games Launcher", "🎮", L + "EpicGamesLauncher\\Saved\\webcache*",
         "Кэш магазина и браузера лаунчера Epic.", "Лаунчер пересоздаст сам.", ["EpicGamesLauncher", "EpicWebHelper"],
         also=[L + "EpicGamesLauncher\\Saved\\Logs"]),
    item("minecraft_logs", "Логи и отчёты Minecraft", "⛏️", R + ".minecraft\\logs", "Журналы запуска игры и клиента.",
         "Ничего. Миры и настройки не затрагиваются.", ["javaw", "Minecraft"], also=[R + ".minecraft\\crash-reports"]),

    # ── видеокарты и графика ──
    item("nvidia_glcache", "Кэш OpenGL NVIDIA", "🟩", L + "NVIDIA\\GLCache", "Скомпилированные OpenGL-шейдеры драйвера.",
         "Драйвер пересоздаст при запуске игр.", []),
    item("nvidia_nvcache", "Кэш NVIDIA (ProgramData)", "🟩", PD + "NVIDIA Corporation\\NV_Cache", "Шейдерный кэш драйвера NVIDIA.",
         "Драйвер пересоздаст сам.", []),
    item("nvidia_installers", "Старые установщики драйвера NVIDIA", "🟩", PD + "NVIDIA Corporation\\Downloader",
         "Распакованные пакеты прошлых обновлений драйвера (GeForce Experience).", "Скачаются заново при следующем обновлении.", ["NVIDIA"]),
    item("amd_dxcache", "Кэш шейдеров AMD", "🟥", L + "AMD\\DxCache", "Шейдерный кэш драйвера AMD.",
         "Драйвер пересоздаст при запуске игр.", [], also=[L + "AMD\\GLCache", L + "AMD\\VkCache"]),
    item("intel_shader", "Кэш шейдеров Intel", "🟦", L + "Intel\\ShaderCache", "Шейдерный кэш драйвера Intel.",
         "Драйвер пересоздаст сам.", []),

    # ── Windows и офис ──
    item("minidump", "Мини-дампы синих экранов", "💥", WIN + "Minidump", "Снимки памяти после критических сбоев Windows. Нужны только для разбора причин.",
         "Ничего. Новые появятся только при новых сбоях.", kind="contents"),
    item("livekernel", "Отчёты ядра (LiveKernelReports)", "💥", WIN + "LiveKernelReports", "Дампы сбоев драйверов и оборудования.",
         "Ничего.", kind="contents"),
    item("wer_system", "Системные отчёты об ошибках", "📋", PD + "Microsoft\\Windows\\WER\\ReportArchive",
         "Архив отчётов о сбоях, собранный на уровне системы.", "Ничего.", kind="contents", also=[PD + "Microsoft\\Windows\\WER\\ReportQueue"]),
    item("delivery_opt", "Кэш оптимизации доставки Windows", "🪟",
         WIN + "ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache",
         "Части обновлений, которые Windows хранит для раздачи другим компьютерам. Часто занимает гигабайты.",
         "Ничего. Требуются права администратора.", kind="contents"),
    item("office_cache", "Кэш файлов Office", "📄", L + "Microsoft\\Office\\16.0\\OfficeFileCache",
         "Кэш синхронизации документов Office с облаком. Сами документы не затрагиваются.", "Office пересоздаст.", ["winword", "excel", "powerpnt", "outlook"]),
    item("onedrive_logs", "Логи OneDrive", "☁️", L + "Microsoft\\OneDrive\\logs", "Журналы синхронизации OneDrive.", "Ничего.", ["OneDrive"]),
    item("nuget_v3", "Кэш запросов NuGet", "🟣", L + "NuGet\\v3-cache", "Кэш ответов серверов пакетов NuGet.",
         "NuGet запросит заново.", ["devenv", "dotnet"], also=[L + "NuGet\\plugins-cache"]),

    # ── разработка: безопасные кэши ──
    item("vscode_web_cache", "Кэш VS Code (веб-часть)", "🧩", R + "Code\\Cache", "Кэш встроенного браузера редактора.",
         "VS Code пересоздаст.", ["code"], also=[R + "Code\\Code Cache", R + "Code\\GPUCache", R + "Code\\CachedProfilesData"], icon_src=EXE["vscode"]),
    item("cursor_cache", "Кэш Cursor", "🧩", R + "Cursor\\Cache", "Кэш редактора Cursor (скомпилированный код, GPU, логи).",
         "Cursor пересоздаст. Настройки и расширения не затрагиваются.", ["cursor"],
         also=[R + "Cursor\\Code Cache", R + "Cursor\\GPUCache", R + "Cursor\\CachedData", R + "Cursor\\logs"]),
    item("jetbrains_logs", "Логи JetBrains IDE", "🧰", L + "JetBrains\\*\\log", "Журналы PyCharm, IntelliJ, WebStorm, Rider и др.",
         "Ничего.", ["idea64", "pycharm64", "webstorm64", "rider64", "clion64", "goland64", "phpstorm64", "datagrip64"]),
    item("vs_componentcache", "Кэш компонентов Visual Studio", "🟣", L + "Microsoft\\VisualStudio\\*\\ComponentModelCache",
         "Кэш MEF-компонентов. Visual Studio пересоберёт его при запуске (первый старт дольше).", "Пересоздаётся автоматически.", ["devenv"]),
    item("gradle_daemon_logs", "Логи демона Gradle", "🐘", U + ".gradle\\daemon", "Журналы фоновых процессов Gradle.", "Ничего.", ["java", "gradle"]),
    item("android_cache", "Кэш Android SDK", "🤖", U + ".android\\cache", "Кэш скачивания компонентов SDK.", "Скачается заново.", ["studio64", "java"]),
    item("unity_cache", "Кэш Unity", "🧊", L + "Unity\\cache", "Скачанные пакеты и ассеты Unity.", "Unity скачает заново.", ["Unity", "UnityHub"]),
    item("py_tool_caches", "Кэш Python-инструментов", "🐍", U + ".cache\\pre-commit", "Кэш pre-commit и подобных утилит.",
         "Утилиты пересоздадут.", ["python"], also=[U + ".mypy_cache", U + ".ruff_cache"]),
]

REVIEW_EXTRA = [
    item("jetbrains_caches", "Кэши и индексы JetBrains IDE", "🧰", L + "JetBrains\\*\\caches",
         "Индексы проектов PyCharm, IntelliJ, WebStorm и др. Занимают 1–10 ГБ.",
         "IDE заново проиндексирует проекты — первый запуск будет долгим.",
         ["idea64", "pycharm64", "webstorm64", "rider64", "clion64", "goland64", "phpstorm64", "datagrip64"],
         also=[L + "JetBrains\\*\\index", L + "JetBrains\\*\\tmp", L + "Google\\AndroidStudio*\\caches"]),
    item("steam_shadercache", "Шейдерный кэш Steam", "🎮", "%ProgramFiles(x86)%\\Steam\\steamapps\\shadercache",
         "Скомпилированные шейдеры игр Steam, по папке на игру.", "Steam пересоберёт при запуске игр — первые минуты возможны подтормаживания.",
         ["steam"], also=["%ProgramFiles(x86)%\\Steam\\steamapps\\temp", "?:\\SteamLibrary\\steamapps\\shadercache", "?:\\Steam\\steamapps\\shadercache",
                          "?:\\Games\\Steam\\steamapps\\shadercache"]),
    item("telegram_cache", "Кэш Telegram", "✈️", R + "Telegram Desktop\\tdata\\user_data\\cache",
         "Закэшированные картинки, видео и файлы из чатов. Сами переписки хранятся на серверах Telegram.",
         "Медиа подгрузится заново при просмотре. Файлы из папки «Загрузки» не затрагиваются.",
         ["Telegram"], also=[R + "Telegram Desktop\\tdata\\user_data\\media_cache"]),
    item("spotify_storage", "Офлайн-кэш Spotify", "🎧", L + "Spotify\\Storage", "Скачанные для прослушивания без интернета треки.",
         "Загрузите нужные плейлисты для офлайна заново.", ["Spotify"]),
    item("adobe_media_cache", "Кэш медиа Adobe", "🎞️", R + "Adobe\\Common\\Media Cache Files",
         "Кэш Premiere Pro и After Effects: превью, звук, пиковые файлы. Растёт до десятков ГБ.",
         "Adobe пересоздаст при открытии проекта — первое открытие дольше.", ["Adobe Premiere Pro", "AfterFX", "Adobe Media Encoder"],
         also=[R + "Adobe\\Common\\Media Cache", R + "Adobe\\Common\\Peak Files", R + "Adobe\\CameraRaw\\Cache"]),
    item("gradle_wrapper", "Дистрибутивы Gradle (wrapper)", "🐘", U + ".gradle\\wrapper\\dists",
         "Скачанные версии Gradle для проектов. Старые версии почти всегда не нужны.", "Проект скачает нужную версию сам.", ["java", "gradle", "studio64", "idea64"]),
    item("windows_update_dl", "Загрузки Windows Update", "🪟", WIN + "SoftwareDistribution\\Download",
         "Скачанные обновления, которые уже установлены или ждут установки. Нужны права администратора.",
         "Windows скачает нужное заново. Не чистите во время установки обновлений.", kind="contents"),
    item("torch_cache", "Кэш моделей PyTorch / Whisper", "🧠", U + ".cache\\torch",
         "Скачанные веса моделей (torch hub, checkpoints). Решите, нужны ли они.", "Модели скачаются при следующем запуске кода.",
         ["python"], also=[U + ".cache\\whisper"]),
    item("unreal_ddc", "Кэш данных Unreal Engine (DDC)", "🎮", L + "UnrealEngine\\Common\\DerivedDataCache",
         "Производные данные ассетов. Растёт до десятков ГБ.", "Редактор пересоберёт — первое открытие проектов долгое.", ["UnrealEditor", "UE4Editor"]),
    item("windows_old", "Предыдущая версия Windows (Windows.old)", "🪟", "%SystemDrive%\\Windows.old",
         "Остаётся после крупного обновления Windows, обычно 10–30 ГБ. Нужна для отката.",
         "Удаляйте через «Параметры → Система → Память → Временные файлы» или Очистку диска — вручную папку не удалить.",
         deletable=False),
    item("docker_wsl", "Данные Docker Desktop (WSL)", "🐳", L + "Docker\\wsl",
         "Виртуальный диск Docker с образами и томами — может занимать десятки ГБ.",
         "Освобождайте командой `docker system prune -a` (удаляет неиспользуемые образы и контейнеры), а не удалением файла.", deletable=False),
    item("android_sdk_images", "Образы эмуляторов Android", "🤖", L + "Android\\Sdk\\system-images",
         "Образы систем для эмулятора, по 1–3 ГБ каждый.", "Удаляйте ненужные в SDK Manager (Android Studio).", deletable=False),
    item("lmstudio_models", "Модели LM Studio", "🧠", U + ".lmstudio\\models", "Локальные языковые модели. Решите, какие ещё нужны.",
         "Удаляйте модели в самой LM Studio (вкладка «Мои модели»).", deletable=False),
    item("npm_logs", "Логи npm", "📦", L + "npm-cache\\_logs", "Журналы запусков npm.", "Ничего.", ["node", "npm"]),
]
