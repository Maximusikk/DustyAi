"""Catalog of known places where junk accumulates. The only source of paths:
the client sends only an id, the path is always taken from here."""
import re


# kind: "contents" — delete the contents, keep the root; "folder" — delete the whole folder
# deletable: whether it can be deleted via the API
# blockers: processes that forbid deletion while running
SAFE = [
    dict(id="user_temp", name="User temp files", icon="🗑️", path="%TEMP%",
         kind="contents", deletable=True, blockers=["vs_installer", "devenv"],
         desc="Files programs created while running and did not clean up.",
         restore="Nothing — programs will recreate the files they need."),
    dict(id="local_temp", name="Local Temp", icon="🗑️", path="%LOCALAPPDATA%\\Temp",
         kind="contents", deletable=True, blockers=["vs_installer", "devenv"],
         desc="Installer leftovers (e.g. Visual Studio), extracted archives, logs.",
         restore="Nothing. Windows will simply skip files in use."),
    dict(id="crash_dumps", name="Crash dumps", icon="💥", path="%LOCALAPPDATA%\\CrashDumps",
         kind="contents", deletable=True, blockers=[],
         desc="Memory snapshots of crashed programs. Only needed for debugging.",
         restore="Nothing. New dumps appear only after new crashes."),
    dict(id="windows_temp", name="System Temp", icon="🗑️", path="%SystemRoot%\\Temp",
         kind="contents", deletable=True, blockers=["vs_installer"],
         desc="Temporary files of Windows and services. Some files may require administrator rights.",
         restore="Nothing."),
    dict(id="pip_cache", icon_src=['%LOCALAPPDATA%\\Programs\\Python\\Python3*\\python.exe', 'C:\\Python3*\\python.exe'], name="pip cache", icon="🐍", path="%LOCALAPPDATA%\\pip\\Cache",
         kind="folder", deletable=True, blockers=[],
         desc="Previously downloaded Python wheel packages.",
         restore="pip will download packages again on the next install."),
]

REVIEW = [
    dict(id="gradle_cache", icon_src=['%ProgramFiles%\\Android\\Android Studio\\bin\\studio64.exe', '%ProgramFiles%\\JetBrains\\*\\bin\\idea64.exe'], name="Gradle cache", icon="🐘", path="%USERPROFILE%\\.gradle\\caches",
         kind="folder", deletable=True, blockers=["idea64", "studio64", "java"],
         desc="Downloaded dependencies and build artifacts of Gradle/Android.",
         restore="Gradle will re-download dependencies — the next build will be slow."),
    dict(id="npm_cache", icon_src=['%ProgramFiles%\\nodejs\\node.exe'], name="npm cache", icon="📦", path="%APPDATA%\\npm-cache",
         kind="folder", deletable=True, blockers=["node", "npm"],
         desc="Cache of downloaded npm packages.",
         restore="npm will download packages again."),
    dict(id="nuget_cache", icon_src=['%ProgramFiles%\\dotnet\\dotnet.exe'], name="NuGet packages", icon="🟣", path="%USERPROFILE%\\.nuget\\packages",
         kind="folder", deletable=True, blockers=["devenv", "dotnet"],
         desc="Global .NET packages shared by all projects.",
         restore="dotnet restore will download everything again."),
    dict(id="cargo_registry", icon_src=['%USERPROFILE%\\.cargo\\bin\\cargo.exe'], name="Cargo registry", icon="🦀", path="%USERPROFILE%\\.cargo\\registry",
         kind="folder", deletable=True, blockers=["cargo", "rustc"],
         desc="Sources and index of downloaded Rust crates.",
         restore="cargo will re-download crates during a build."),
    dict(id="arduino_staging", icon_src=['%LOCALAPPDATA%\\Programs\\Arduino IDE\\Arduino IDE.exe', '%ProgramFiles%\\Arduino IDE\\Arduino IDE.exe'], name="Arduino staging", icon="🔌", path="%LOCALAPPDATA%\\Arduino15\\staging",
         kind="folder", deletable=True, blockers=["arduino", "Arduino IDE"],
         desc="Downloaded board and library archives — not needed after installation.",
         restore="Nothing — installed boards are kept."),
    dict(id="huggingface_cache", name="Hugging Face models", icon="🤗", path="%USERPROFILE%\\.cache\\huggingface",
         kind="folder", deletable=False, blockers=[],
         desc="Downloaded AI models. Decide which of them you still need.",
         restore="Models will have to be downloaded again (sometimes gigabytes)."),
    dict(id="playwright_browsers", icon_src=['%LOCALAPPDATA%\\ms-playwright\\chromium-*\\chrome-win\\chrome.exe'], name="Playwright browsers", icon="🎭", path="%LOCALAPPDATA%\\ms-playwright",
         kind="folder", deletable=False, blockers=[],
         desc="Chromium/Firefox/WebKit for e2e tests. Only needed if you run Playwright.",
         restore="Restored with the `playwright install` command."),
    dict(id="ollama_models", icon_src=['%LOCALAPPDATA%\\Programs\\Ollama\\ollama app.exe'], name="Ollama models", icon="🦙", path="%USERPROFILE%\\.ollama\\models",
         kind="folder", deletable=False, blockers=[],
         desc="Local language models. Delete them with `ollama rm <model>`.",
         restore="Models are downloaded again with `ollama pull`."),
]

DO_NOT_TOUCH = [
    dict(name="pagefile.sys", icon="🔒", reason="Windows page file. Deleting it breaks the system."),
    dict(name="Windows\\Installer", icon="🔒", reason="MSI installer cache: without it programs cannot be uninstalled or updated."),
    dict(name="ProgramData\\Package Cache", icon="🔒", reason="Needed by uninstallers and updates of Visual Studio, .NET and others."),
    dict(name="Claude vm_bundles", icon="🔒", reason="Claude virtual machine data."),
    dict(name="WSL ext4.vhdx", icon="🔒", reason="Disk of a WSL Linux distribution. Your files are inside."),
    dict(name="Browser profiles", icon="🔒", reason="Passwords, bookmarks and sessions."),
]


SAFE += [
    {'id': 'd3d_cache', 'name': 'DirectX shader cache', 'icon': '🎮', 'path': '%LOCALAPPDATA%\\D3DSCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Compiled shaders of games and applications.', 'restore': 'Recreated when games start — minor stutters are possible at first.'},
    {'id': 'nvidia_cache', 'name': 'NVIDIA shader cache', 'icon': '🟩', 'path': '%LOCALAPPDATA%\\NVIDIA\\DXCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Shader cache of the NVIDIA video driver.', 'restore': 'The driver will recreate it itself.'},
    {'id': 'wer_reports', 'name': 'Windows error reports', 'icon': '📋', 'path': '%LOCALAPPDATA%\\Microsoft\\Windows\\WER', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Archive of program crash reports Windows collects to send to Microsoft.', 'restore': 'Nothing. New reports appear only after new crashes.'},
    {'id': 'inet_cache', 'name': 'Internet Explorer / WebView cache', 'icon': '🌐', 'path': '%LOCALAPPDATA%\\Microsoft\\Windows\\INetCache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Cache of pages and images of built-in Windows web components.', 'restore': 'Will be downloaded again when needed.'},
    {'id': 'vscode_vsix', 'name': 'VS Code extension cache (VSIX)', 'icon': '🧩', 'path': '%APPDATA%\\Code\\CachedExtensionVSIXs', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Downloaded extension installers — not needed after installation.', 'restore': 'VS Code will download it again when the extension is reinstalled.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'vscode_cached', 'name': 'VS Code data cache', 'icon': '🧩', 'path': '%APPDATA%\\Code\\CachedData', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Compiled code cache of the editor.', 'restore': 'VS Code will recreate it on start.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'vscode_logs', 'name': 'VS Code logs', 'icon': '🧩', 'path': '%APPDATA%\\Code\\logs', 'kind': 'folder', 'deletable': True, 'blockers': ['code'], 'desc': 'Logs of the editor and extensions.', 'restore': 'Nothing.', 'icon_src': ['%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe', '%ProgramFiles%\\Microsoft VS Code\\Code.exe']},
    {'id': 'chrome_ai_model', 'name': 'Chrome built-in AI model', 'icon': '🧠', 'path': '%LOCALAPPDATA%\\Google\\Chrome\\User Data\\OptGuideOnDeviceModel', 'kind': 'folder', 'deletable': True, 'blockers': ['chrome'], 'desc': 'The local language model of Chrome (up to several GB). Not your profile or bookmarks.', 'restore': 'Chrome may download it again; can be disabled in Chrome settings.', 'icon_src': ['%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe', '%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe']},
]

REVIEW += [
    {'id': 'npm_cache_local', 'name': 'npm cache (Local)', 'icon': '📦', 'path': '%LOCALAPPDATA%\\npm-cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'npm'], 'desc': 'Main npm cache on modern versions: downloaded packages.', 'restore': 'npm will download packages again.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'pnpm_cache', 'name': 'pnpm cache', 'icon': '📦', 'path': '%LOCALAPPDATA%\\pnpm-cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'pnpm'], 'desc': 'pnpm metadata and package cache.', 'restore': 'pnpm will download it again.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'yarn_cache', 'name': 'Yarn cache', 'icon': '🧶', 'path': '%LOCALAPPDATA%\\Yarn\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['node', 'yarn'], 'desc': 'Cache of downloaded Yarn packages.', 'restore': 'Yarn will download it again.', 'icon_src': ['%ProgramFiles%\\nodejs\\node.exe']},
    {'id': 'go_build', 'name': 'Go build cache', 'icon': '🐹', 'path': '%LOCALAPPDATA%\\go-build', 'kind': 'folder', 'deletable': True, 'blockers': ['go'], 'desc': 'Results of previous Go builds.', 'restore': 'The next build will be slower, then everything returns to normal.', 'icon_src': ['%ProgramFiles%\\Go\\bin\\go.exe']},
    {'id': 'maven_repo', 'name': 'Maven repository', 'icon': '☕', 'path': '%USERPROFILE%\\.m2\\repository', 'kind': 'folder', 'deletable': True, 'blockers': ['java', 'mvn', 'idea64'], 'desc': 'All downloaded Java dependencies.', 'restore': 'Maven will download dependencies on the next build.'},
    {'id': 'uv_cache', 'name': 'uv cache', 'icon': '🐍', 'path': '%LOCALAPPDATA%\\uv\\cache', 'kind': 'folder', 'deletable': True, 'blockers': [], 'desc': 'Cache of the Python package manager uv.', 'restore': 'uv will download packages again.'},
    {'id': 'poetry_cache', 'name': 'Poetry cache', 'icon': '🐍', 'path': '%LOCALAPPDATA%\\pypoetry\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['poetry'], 'desc': 'Cache of Poetry packages and virtual environments.', 'restore': 'Poetry will recreate it on install.'},
    {'id': 'conda_pkgs', 'name': 'conda packages', 'icon': '🐍', 'path': '%USERPROFILE%\\.conda\\pkgs', 'kind': 'folder', 'deletable': True, 'blockers': ['conda'], 'desc': 'Cache of extracted conda packages.', 'restore': 'conda will download packages when creating an environment.'},
    {'id': 'composer_cache', 'name': 'Composer cache (PHP)', 'icon': '🐘', 'path': '%LOCALAPPDATA%\\Composer', 'kind': 'folder', 'deletable': True, 'blockers': ['php', 'composer'], 'desc': 'Package cache of the PHP manager Composer.', 'restore': 'Composer will download it again.'},
    {'id': 'pub_cache', 'name': 'Dart/Flutter pub cache', 'icon': '🎯', 'path': '%LOCALAPPDATA%\\Pub\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['dart', 'flutter'], 'desc': 'Downloaded Dart and Flutter packages.', 'restore': '`flutter pub get` will download it again.'},
    {'id': 'puppeteer_cache', 'name': 'Puppeteer browsers', 'icon': '🎭', 'path': '%USERPROFILE%\\.cache\\puppeteer', 'kind': 'folder', 'deletable': True, 'blockers': ['node'], 'desc': 'Chrome downloaded by Puppeteer for automated tests.', 'restore': 'Will be downloaded on the next Puppeteer run.'},
    {'id': 'cypress_cache', 'name': 'Cypress binaries', 'icon': '🌲', 'path': '%LOCALAPPDATA%\\Cypress\\Cache', 'kind': 'folder', 'deletable': True, 'blockers': ['Cypress', 'node'], 'desc': 'Downloaded Cypress versions.', 'restore': '`npx cypress install` will download it again.'},
]

from catalog_extra import REVIEW_EXTRA, SAFE_EXTRA  # noqa: E402

SAFE += SAFE_EXTRA
REVIEW += REVIEW_EXTRA


def item_patterns(item):
    """All path patterns of an item (environment variables and `*` are expanded by util.expand_all)."""
    return [item["path"], *item.get("also", [])]


# Folder names that the catalog treats as a “data root”: deleting them whole = losing profiles and passwords
PROFILE_ROOTS = {"user data", "default", "profiles", "firefox", "chrome", "edge", "google", "mozilla", "brave-browser",
                 "opera stable", "opera gx stable", "yandexbrowser", "vivaldi", "appdata", "local", "roaming"}


def is_profile_root(path):
    name = re.split(r"[\\/]", path.rstrip("\\/"))[-1].lower()
    return name in PROFILE_ROOTS or name.startswith("profile ")


# Only these ids are cleaned — this is the whitelist for POST /delete
ALL_ITEMS = {i["id"]: i for i in SAFE + REVIEW}
DELETABLE_IDS = {i["id"] for i in ALL_ITEMS.values() if i["deletable"]}

# id → risk zone
ZONE = {**{i["id"]: "safe" for i in SAFE}, **{i["id"]: "review" for i in REVIEW}}

# Processes that must not be disturbed when cleaning any data
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
     "reason": "Large folder untouched for over a week — probably an extracted installer."},
    {"name": "vs_installer_9f2a", "path": "C:\\Users\\demo\\AppData\\Local\\Temp\\vs_installer_9f2a", "size_gb": 0.4,
     "age_days": 12, "reason": "Looks like installer leftovers (by folder name)."},
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
              {"name": "node_modules", "path": "D:\\Projects\\shop\\node_modules", "what": "Node.js dependencies", "size_gb": 1.4},
              {"name": "node_modules", "path": "D:\\Projects\\blog\\node_modules", "what": "Node.js dependencies", "size_gb": 0.9},
              {"name": ".venv", "path": "D:\\Projects\\ml\\.venv", "what": "Python virtual environment", "size_gb": 5.2}]},
}

MOCK["downloads"] = [
    {"name": "Windows11_24H2.iso", "path": "C:\\Users\\demo\\Downloads\\Windows11_24H2.iso", "size_gb": 5.4, "date": "2025-06-12", "age_days": 482, "installer": True},
    {"name": "Docker Desktop Installer.exe", "path": "C:\\Users\\demo\\Downloads\\Docker Desktop Installer.exe", "size_gb": 0.6, "date": "2025-09-03", "age_days": 399, "installer": True},
    {"name": "conference_recording.mp4", "path": "C:\\Users\\demo\\Downloads\\conference_recording.mp4", "size_gb": 3.2, "date": "2026-09-30", "age_days": 7, "installer": False},
    {"name": "dataset_v2.zip", "path": "C:\\Users\\demo\\Downloads\\dataset_v2.zip", "size_gb": 2.1, "date": "2026-03-18", "age_days": 203, "installer": True},
]
MOCK["profile"] = [
    {"title": "User profile", "root": "C:\\Users\\demo", "entries": [
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
        {"name": "(files in the drive root)", "path": "C:\\", "size_gb": 7.9}],
    "big_files": [
        {"name": "qwen3-27b-q4_k_m.gguf", "path": "C:\\llama\\models\\qwen3-27b-q4_k_m.gguf", "size_gb": 16.4, "kind": "AI model (weights)", "icon": "🧠", "date": "2026-03-02", "age_days": 219},
        {"name": "pagefile.sys", "path": "C:\\pagefile.sys", "size_gb": 7.25, "date": "2026-10-07", "age_days": 0, "kind": "System file (page file/hibernation) — do not delete manually", "icon": "🔒"},
        {"name": "ext4.vhdx", "path": "C:\\Users\\demo\\AppData\\Local\\Packages\\wsl\\ext4.vhdx", "size_gb": 3.2, "date": "2026-08-14", "age_days": 54, "kind": "Virtual disk image (VM/WSL/Docker)", "icon": "💽"},
        {"name": "torch_cuda.dll", "path": "C:\\Python311\\Lib\\site-packages\\torch\\lib\\torch_cuda.dll", "size_gb": 0.9, "date": "2026-08-16", "age_days": 52, "kind": "File", "icon": "📄"},
        {"name": "llama-server-cuda.bin", "path": "C:\\llama\\llama-server-cuda.bin", "size_gb": 0.9, "date": "2026-03-02", "age_days": 219, "kind": "Binary file (often model weights or game data)", "icon": "📄"}],
    "junk": [
        {"name": "node_modules", "path": "C:\\Users\\demo\\work\\site\\node_modules", "what": "Node.js dependencies", "size_gb": 0.8}]}
