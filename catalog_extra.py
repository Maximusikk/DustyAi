"""Catalog extension: browsers (all profiles), messengers, launchers, IDEs, Windows, video/game caches.
Only things that programs recreate themselves. Patterns: environment variables and `*` (all profiles).
Items with deletable=False cannot be deleted with the button; they explain how to clean properly."""

L = "%LOCALAPPDATA%\\"
R = "%APPDATA%\\"
U = "%USERPROFILE%\\"
PD = "%ProgramData%\\"
WIN = "%SystemRoot%\\"
EXE = {  # application icons
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
    """Pure caches of a Chromium browser across all profiles: pages, compiled JS, graphics.
    Whole profiles, passwords, cookies, history, bookmarks, extensions and site data are not touched."""
    per = ["Cache", "Code Cache", "GPUCache", "DawnCache"]
    paths = [f"{user_data}\\*\\{p}" for p in per] + [f"{user_data}\\{p}" for p in
                                                      ("ShaderCache", "GrShaderCache", "GraphiteDawnCache")]
    paths += list(extra_root)
    return item(id, f"{name} cache (all profiles)", "🌐", paths[0],
                f"Only the temporary cache of {name}: pages, compiled JS, graphics. Profiles, passwords, cookies, history, bookmarks and extensions are NOT affected.",
                "Sites will reload — the first visit is slightly slower. Logins and profiles are kept.",
                blockers, also=paths[1:], icon_src=icon_src)


def chromium_sw(id, name, user_data, blockers, icon_src=None):
    """Offline site cache (Service Worker): can be very large, stores offline data for web apps."""
    return item(id + "_sw", f"{name} offline site cache", "🌐", f"{user_data}\\*\\Service Worker\\CacheStorage",
                f"Cache of web apps (mail, messengers, PWAs) in {name}. Often the heaviest part. Logins and passwords are not affected.",
                "Web apps will reload their data; offline mode will stop working for a while.",
                blockers, also=[f"{user_data}\\*\\Service Worker\\ScriptCache"], icon_src=icon_src)


BROWSERS = [
    ("chrome_cache", "Chrome", L + "Google\\Chrome\\User Data", ["chrome"], EXE["chrome"], ()),
    ("edge_cache", "Edge", L + "Microsoft\\Edge\\User Data", ["msedge"], EXE["edge"], ()),
    ("brave_cache", "Brave", L + "BraveSoftware\\Brave-Browser\\User Data", ["brave"], EXE["brave"], ()),
    ("vivaldi_cache", "Vivaldi", L + "Vivaldi\\User Data", ["vivaldi"], None, ()),
    ("yandex_cache", "Yandex Browser", L + "Yandex\\YandexBrowser\\User Data", ["browser", "yandex"], None, ()),
    ("opera_cache", "Opera", L + "Opera Software\\Opera Stable", ["opera"], None, [
        L + "Opera Software\\Opera Stable\\Cache", L + "Opera Software\\Opera Stable\\Code Cache",
        L + "Opera Software\\Opera Stable\\GPUCache"]),
    ("operagx_cache", "Opera GX", L + "Opera Software\\Opera GX Stable", ["opera"], None, [
        L + "Opera Software\\Opera GX Stable\\Cache", L + "Opera Software\\Opera GX Stable\\Code Cache",
        L + "Opera Software\\Opera GX Stable\\GPUCache"]),
]


SAFE_EXTRA = [
    # ── browsers ──
    *[chromium(*b[:5], extra_root=b[5]) for b in BROWSERS],
    item("firefox_cache", "Firefox cache (all profiles)", "🦊", L + "Mozilla\\Firefox\\Profiles\\*\\cache2",
         "Firefox page cache. Passwords, bookmarks and history are stored in a different folder (AppData\\Roaming) and are not affected.",
         "Sites will reload.", ["firefox"], also=[L + "Mozilla\\Firefox\\Profiles\\*\\startupCache",
                                                       L + "Mozilla\\Firefox\\Profiles\\*\\jumpListCache"], icon_src=EXE["firefox"]),
    item("zen_cache", "Zen Browser cache", "🌐", L + "zen\\Profiles\\*\\cache2",
         "Zen page cache. The profile with passwords and bookmarks is not affected.", "Sites will reload.", ["zen"]),

    # ── messengers and Electron apps ──
    item("discord_cache", "Discord cache", "💬", R + "discord\\Cache", "Cache of images and attachments from chats.",
         "Will be reloaded when viewed.", ["Discord"], also=[R + "discord\\Code Cache", R + "discord\\GPUCache"],
         icon_src=["%LOCALAPPDATA%\\Discord\\app-*\\Discord.exe"]),
    item("slack_cache", "Slack cache", "💼", R + "Slack\\Cache", "Cache of images and files from work chats. Messages are stored on the server.",
         "Slack will reload it.", ["slack"], also=[R + "Slack\\Code Cache", R + "Slack\\GPUCache", R + "Slack\\Service Worker\\CacheStorage"]),
    item("teams_cache", "Microsoft Teams cache", "🟪", R + "Microsoft\\Teams\\Cache",
         "Cache of classic Teams: images, temporary data, GPU.", "Teams will recreate it on start.",
         ["teams"], also=[R + "Microsoft\\Teams\\blob_storage", R + "Microsoft\\Teams\\Code Cache", R + "Microsoft\\Teams\\GPUCache",
                          R + "Microsoft\\Teams\\tmp", R + "Microsoft\\Teams\\Service Worker\\CacheStorage"]),
    item("teams_new_cache", "New Teams cache", "🟪", L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\Cache",
         "Cache of the web part of new Teams.", "Teams will recreate it on start.", ["ms-teams", "teams"],
         also=[L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\Code Cache",
               L + "Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\EBWebView\\*\\GPUCache"]),
    item("notion_cache", "Notion cache", "📝", R + "Notion\\Cache", "Cache of pages and images. Your notes are stored in the Notion cloud.",
         "Notion will reload it.", ["Notion"], also=[R + "Notion\\Code Cache", R + "Notion\\GPUCache"]),
    item("zoom_logs", "Zoom logs", "🎥", R + "Zoom\\logs", "Zoom logs. Meeting recordings and the account are not affected.",
         "Nothing.", ["Zoom"]),
    item("steam_html", "Steam browser cache", "🎮", L + "Steam\\htmlcache", "Cache of the built-in Steam browser (store, community).",
         "Steam will recreate it itself.", ["steam", "steamwebhelper"]),
    item("epic_cache", "Epic Games Launcher cache", "🎮", L + "EpicGamesLauncher\\Saved\\webcache*",
         "Cache of the Epic launcher store and browser.", "The launcher will recreate it itself.", ["EpicGamesLauncher", "EpicWebHelper"],
         also=[L + "EpicGamesLauncher\\Saved\\Logs"]),
    item("minecraft_logs", "Minecraft logs and reports", "⛏️", R + ".minecraft\\logs", "Game and client launch logs.",
         "Nothing. Worlds and settings are not affected.", ["javaw", "Minecraft"], also=[R + ".minecraft\\crash-reports"]),

    # ── graphics cards and graphics ──
    item("nvidia_glcache", "NVIDIA OpenGL cache", "🟩", L + "NVIDIA\\GLCache", "Compiled OpenGL shaders of the driver.",
         "The driver will recreate it when games start.", []),
    item("nvidia_nvcache", "NVIDIA cache (ProgramData)", "🟩", PD + "NVIDIA Corporation\\NV_Cache", "Shader cache of the NVIDIA driver.",
         "The driver will recreate it itself.", []),
    item("nvidia_installers", "Old NVIDIA driver installers", "🟩", PD + "NVIDIA Corporation\\Downloader",
         "Extracted packages of previous driver updates (GeForce Experience).", "Will be downloaded again on the next update.", ["NVIDIA"]),
    item("amd_dxcache", "AMD shader cache", "🟥", L + "AMD\\DxCache", "Shader cache of the AMD driver.",
         "The driver will recreate it when games start.", [], also=[L + "AMD\\GLCache", L + "AMD\\VkCache"]),
    item("intel_shader", "Intel shader cache", "🟦", L + "Intel\\ShaderCache", "Shader cache of the Intel driver.",
         "The driver will recreate it itself.", []),

    # ── Windows and Office ──
    item("minidump", "Blue screen minidumps", "💥", WIN + "Minidump", "Memory snapshots after critical Windows crashes. Only needed to analyze the causes.",
         "Nothing. New ones appear only after new crashes.", kind="contents"),
    item("livekernel", "Kernel reports (LiveKernelReports)", "💥", WIN + "LiveKernelReports", "Crash dumps of drivers and hardware.",
         "Nothing.", kind="contents"),
    item("wer_system", "System error reports", "📋", PD + "Microsoft\\Windows\\WER\\ReportArchive",
         "Archive of crash reports collected at the system level.", "Nothing.", kind="contents", also=[PD + "Microsoft\\Windows\\WER\\ReportQueue"]),
    item("delivery_opt", "Windows Delivery Optimization cache", "🪟",
         WIN + "ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache",
         "Update parts that Windows keeps to share with other computers. Often takes gigabytes.",
         "Nothing. Requires administrator rights.", kind="contents"),
    item("office_cache", "Office file cache", "📄", L + "Microsoft\\Office\\16.0\\OfficeFileCache",
         "Cache for syncing Office documents with the cloud. The documents themselves are not affected.", "Office will recreate it.", ["winword", "excel", "powerpnt", "outlook"]),
    item("onedrive_logs", "OneDrive logs", "☁️", L + "Microsoft\\OneDrive\\logs", "OneDrive sync logs.", "Nothing.", ["OneDrive"]),
    item("nuget_v3", "NuGet request cache", "🟣", L + "NuGet\\v3-cache", "Cache of NuGet package server responses.",
         "NuGet will request it again.", ["devenv", "dotnet"], also=[L + "NuGet\\plugins-cache"]),

    # ── development: safe caches ──
    item("vscode_web_cache", "VS Code cache (web part)", "🧩", R + "Code\\Cache", "Cache of the editor's built-in browser.",
         "VS Code will recreate it.", ["code"], also=[R + "Code\\Code Cache", R + "Code\\GPUCache", R + "Code\\CachedProfilesData"], icon_src=EXE["vscode"]),
    item("cursor_cache", "Cursor cache", "🧩", R + "Cursor\\Cache", "Cursor editor cache (compiled code, GPU, logs).",
         "Cursor will recreate it. Settings and extensions are not affected.", ["cursor"],
         also=[R + "Cursor\\Code Cache", R + "Cursor\\GPUCache", R + "Cursor\\CachedData", R + "Cursor\\logs"]),
    item("jetbrains_logs", "JetBrains IDE logs", "🧰", L + "JetBrains\\*\\log", "Logs of PyCharm, IntelliJ, WebStorm, Rider and others.",
         "Nothing.", ["idea64", "pycharm64", "webstorm64", "rider64", "clion64", "goland64", "phpstorm64", "datagrip64"]),
    item("vs_componentcache", "Visual Studio component cache", "🟣", L + "Microsoft\\VisualStudio\\*\\ComponentModelCache",
         "MEF component cache. Visual Studio will rebuild it on start (the first start is slower).", "Recreated automatically.", ["devenv"]),
    item("gradle_daemon_logs", "Gradle daemon logs", "🐘", U + ".gradle\\daemon", "Logs of Gradle background processes.", "Nothing.", ["java", "gradle"]),
    item("android_cache", "Android SDK cache", "🤖", U + ".android\\cache", "Download cache of SDK components.", "Will be downloaded again.", ["studio64", "java"]),
    item("unity_cache", "Unity cache", "🧊", L + "Unity\\cache", "Downloaded Unity packages and assets.", "Unity will download it again.", ["Unity", "UnityHub"]),
    item("py_tool_caches", "Python tool caches", "🐍", U + ".cache\\pre-commit", "Cache of pre-commit and similar tools.",
         "The tools will recreate it.", ["python"], also=[U + ".mypy_cache", U + ".ruff_cache"]),
]

REVIEW_EXTRA = [
    *[chromium_sw(*b[:5]) for b in BROWSERS if not b[5]],
    item("jetbrains_caches", "JetBrains IDE caches and indexes", "🧰", L + "JetBrains\\*\\caches",
         "Project indexes of PyCharm, IntelliJ, WebStorm and others. Take 1–10 GB.",
         "The IDE will re-index projects — the first start will be slow.",
         ["idea64", "pycharm64", "webstorm64", "rider64", "clion64", "goland64", "phpstorm64", "datagrip64"],
         also=[L + "JetBrains\\*\\index", L + "JetBrains\\*\\tmp", L + "Google\\AndroidStudio*\\caches"]),
    item("steam_shadercache", "Steam shader cache", "🎮", "%ProgramFiles(x86)%\\Steam\\steamapps\\shadercache",
         "Compiled shaders of Steam games, one folder per game.", "Steam will rebuild it when games start — slight stutters are possible at first.",
         ["steam"], also=["%ProgramFiles(x86)%\\Steam\\steamapps\\temp", "?:\\SteamLibrary\\steamapps\\shadercache", "?:\\Steam\\steamapps\\shadercache",
                          "?:\\Games\\Steam\\steamapps\\shadercache"]),
    item("telegram_cache", "Telegram cache", "✈️", R + "Telegram Desktop\\tdata\\user_data\\cache",
         "Cached images, videos and files from chats. The conversations themselves are stored on Telegram servers.",
         "Media will be reloaded when viewed. Files in the Downloads folder are not affected.",
         ["Telegram"], also=[R + "Telegram Desktop\\tdata\\user_data\\media_cache"]),
    item("spotify_storage", "Spotify offline cache", "🎧", L + "Spotify\\Storage", "Tracks downloaded for listening without internet.",
         "Download the playlists you need for offline use again.", ["Spotify"]),
    item("adobe_media_cache", "Adobe media cache", "🎞️", R + "Adobe\\Common\\Media Cache Files",
         "Premiere Pro and After Effects cache: previews, audio, peak files. Grows to tens of GB.",
         "Adobe will recreate it when a project is opened — the first open is slower.", ["Adobe Premiere Pro", "AfterFX", "Adobe Media Encoder"],
         also=[R + "Adobe\\Common\\Media Cache", R + "Adobe\\Common\\Peak Files", R + "Adobe\\CameraRaw\\Cache"]),
    item("gradle_wrapper", "Gradle distributions (wrapper)", "🐘", U + ".gradle\\wrapper\\dists",
         "Downloaded Gradle versions for projects. Old versions are almost never needed.", "The project will download the version it needs.", ["java", "gradle", "studio64", "idea64"]),
    item("windows_update_dl", "Windows Update downloads", "🪟", WIN + "SoftwareDistribution\\Download",
         "Downloaded updates that are already installed or waiting to be installed. Requires administrator rights.",
         "Windows will download what it needs again. Do not clean during an update installation.", kind="contents"),
    item("torch_cache", "PyTorch / Whisper model cache", "🧠", U + ".cache\\torch",
         "Downloaded model weights (torch hub, checkpoints). Decide whether you need them.", "Models will be downloaded on the next code run.",
         ["python"], also=[U + ".cache\\whisper"]),
    item("unreal_ddc", "Unreal Engine data cache (DDC)", "🎮", L + "UnrealEngine\\Common\\DerivedDataCache",
         "Derived asset data. Grows to tens of GB.", "The editor will rebuild it — the first project open is slow.", ["UnrealEditor", "UE4Editor"]),
    item("windows_old", "Previous Windows version (Windows.old)", "🪟", "%SystemDrive%\\Windows.old",
         "Left after a major Windows update, usually 10–30 GB. Needed for rolling back.",
         "Delete via “Settings → System → Storage → Temporary files” or Disk Cleanup — the folder cannot be deleted by hand.",
         deletable=False),
    item("docker_wsl", "Docker Desktop data (WSL)", "🐳", L + "Docker\\wsl",
         "Docker virtual disk with images and volumes — can take tens of GB.",
         "Free it with `docker system prune -a` (removes unused images and containers) rather than by deleting the file.", deletable=False),
    item("android_sdk_images", "Android emulator images", "🤖", L + "Android\\Sdk\\system-images",
         "System images for the emulator, 1–3 GB each.", "Delete the ones you do not need in SDK Manager (Android Studio).", deletable=False),
    item("lmstudio_models", "LM Studio models", "🧠", U + ".lmstudio\\models", "Local language models. Decide which ones you still need.",
         "Delete models inside LM Studio itself (the “My Models” tab).", deletable=False),
    item("npm_logs", "npm logs", "📦", L + "npm-cache\\_logs", "npm run logs.", "Nothing.", ["node", "npm"]),
]
