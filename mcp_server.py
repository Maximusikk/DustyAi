"""MCP (Model Context Protocol) server: lets AI agents (Claude, Cursor, VS Code, ...) use Dusty Ai to look at
disk usage and clean up. It reuses the engine of the app, so every safety rule of the GUI applies here too.

Two ways to connect, same tools:
  * stdio  - the agent starts `DustyAi.exe --mcp` itself (no window, nothing to configure);
  * HTTP   - the agent talks to the running app at http://127.0.0.1:5000/mcp with a bearer token.

Agents can only look by default. Deleting needs the "Allow AI agents to clean up" switch in Settings, covers only
catalog/Temp/recycle-bin items (never Downloads, big files, duplicates or programs), takes item ids rather than paths,
defaults to a dry run, and never closes programs. The protocol is small, so it is implemented here without
dependencies (keeps the exe small)."""
import hmac
import json
import os
import secrets
import sys
import threading
import time

import settings

SERVER_NAME = "dusty-ai"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
RISK_MEANING = {
    "A": "Safe: the owning program recreates it by itself.",
    "B": "Your call: usually fine, but the user should check first (deleting costs time or offline data).",
    "C": "Manual only: Dusty Ai never deletes it automatically.",
}
LOG_FILE = os.path.join(settings.DATA_DIR, "agent_log.jsonl")
TOKEN_FILE = os.path.join(settings.DATA_DIR, "mcp_token")
_A = None  # the app module, set by bind()


def bind(app_module):
    global _A
    _A = app_module


# ───────────────────────────── authorization for the HTTP transport ─────────────────────────────

def token(regenerate=False):
    """Bearer token for the HTTP transport, stored in the data folder."""
    if not regenerate:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
        except OSError:
            pass
    t = secrets.token_urlsafe(24)
    try:
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(t)
    except OSError:
        pass
    return t


def authorized(headers, host):
    """Local host name (blocks DNS rebinding), no foreign browser origin, correct bearer token."""
    name = (host or "").rsplit(":", 1)[0].strip("[]").lower()
    if name not in ("127.0.0.1", "localhost", "::1"):
        return False
    origin = headers.get("Origin")
    if origin and origin.split("://", 1)[-1].lower() != (host or "").lower():
        return False
    auth = headers.get("Authorization") or ""
    return auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), token())


# ───────────────────────────── tools ─────────────────────────────

def _log(tool, args, summary):
    try:
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool, "args": args,
                                "result": summary}, ensure_ascii=False) + "\n")
    except OSError:
        pass


class ToolError(Exception):
    """A problem the agent can understand and fix (shown as an error result, not a protocol failure)."""


def _rows():
    with _A._lock:
        if not _A.scan_data:
            raise ToolError("No scan results yet. Call start_scan, then scan_status until it is done.")
        d = _A.with_defaults(dict(_A.scan_data))
    return _A.build_rows(d), d


def _row_view(r):
    return {"id": r["id"], "name": r["name"], "size_gb": round(r["size_gb"], 2), "risk": r["cat"],
            "drive": r["drive"], "path": r["path"], "what_it_is": r["reason"], "after_deletion": r["restore"],
            "agent_can_clean": r["deletable"] and r["kind"] in ("static", "temp", "junk", "recycle")
                               and r["cat"] in ("A", "B")}


def tool_disk_status(args):
    return {"drives": [{"letter": d["Name"], "label": d.get("Label", ""), "type": d.get("Type", "local"),
                        "free_gb": d.get("FreeGB"), "total_gb": d.get("TotalGB"), "used_percent": d.get("Pct"),
                        "can_scan": bool(d.get("scannable"))} for d in _A.get_drives()]}


def tool_start_scan(args):
    letters = args.get("drives") or []
    if not isinstance(letters, list):
        raise ToolError("drives must be a list of drive letters, e.g. [\"C\"]")
    started = _A.start_scan(letters, dups=args.get("find_duplicates", False), profile=args.get("profile_overview", False),
                            deep_system=args.get("deep_scan", False))
    return {"started": started, "note": "A scan is already running." if not started else
            "Scan started. Poll scan_status (it can wait up to 45 s per call)."}


def tool_scan_status(args):
    wait = min(max(float(args.get("wait_seconds") or 0), 0), 45)
    end = time.monotonic() + wait
    while True:
        with _A._lock:
            st = dict(_A.scan_state)
        if st["status"] != "scanning" or time.monotonic() >= end:
            break
        time.sleep(0.5)
    out = {"status": st["status"], "progress_percent": st.get("progress"), "message": st.get("message"),
           "eta_seconds": st.get("eta")}
    if st["status"] == "done":
        rows, d = _rows()
        out["summary"] = {"findings": len(rows), "can_free_gb": d.get("total_gb"), "safe_gb": d.get("safe_gb"),
                          "needs_review_gb": d.get("review_gb")}
    return out


def tool_list_findings(args):
    rows, _ = _rows()
    risk = (args.get("risk") or "").upper()
    if risk and risk not in ("A", "B", "C"):
        raise ToolError("risk must be A, B or C")
    min_gb = float(args.get("min_size_gb") or 0)
    limit = min(int(args.get("limit") or 25), 100)
    sel = [r for r in rows if (not risk or r["cat"] == risk) and r["size_gb"] >= min_gb]
    return {"total_matching": len(sel), "findings": [_row_view(r) for r in sel[:limit]],
            "risk_levels": RISK_MEANING}


def tool_explain_finding(args):
    rows, _ = _rows()
    r = next((x for x in rows if x["id"] == args.get("id")), None)
    if not r:
        raise ToolError("Unknown id. Use an id from list_findings.")
    v = _row_view(r)
    v["risk_meaning"] = RISK_MEANING[r["cat"]]
    if r.get("parts"):
        v["folders_that_would_be_deleted"] = r["parts"]
    return v


def tool_clean(args):
    rows, _ = _rows()
    by_id = {r["id"]: r for r in rows}
    dry = args.get("dry_run", True) is not False
    allow_review = bool(args.get("include_review"))
    wanted = args.get("ids")
    if wanted is None and (args.get("risk") or "").upper() in ("A", "B"):
        wanted = [r["id"] for r in rows if r["cat"] == args["risk"].upper()]
    if not isinstance(wanted, list) or not wanted:
        raise ToolError("Pass ids (from list_findings) or risk: \"A\".")
    chosen, rejected = [], []
    for i in wanted[:100]:
        r = by_id.get(i)
        if not r:
            rejected.append({"id": i, "reason": "unknown id"})
        elif not _row_view(r)["agent_can_clean"]:
            rejected.append({"id": i, "reason": "this item is not cleaned by agents (manual only or not a cache)"})
        elif r["cat"] == "B" and not allow_review:
            rejected.append({"id": i, "reason": "risk B: needs include_review=true and the user's go-ahead"})
        else:
            chosen.append(r)
    ids = {r["id"] for r in chosen}
    chosen = [r for r in chosen if not (r.get("parent_id") and r["parent_id"] in ids)]  # the parent covers the child
    plan = [{"id": r["id"], "name": r["name"], "size_gb": round(r["size_gb"], 2), "risk": r["cat"]} for r in chosen]
    total = round(sum(p["size_gb"] for p in plan), 2)
    if dry:
        _log("clean(dry_run)", {"ids": [p["id"] for p in plan]}, {"would_free_gb": total})
        return {"dry_run": True, "would_delete": plan, "would_free_gb": total, "rejected": rejected,
                "next": "Show this plan to the user. To apply, call clean again with dry_run=false."}
    if not settings.load()["mcp_allow_delete"]:
        raise ToolError("Deleting by AI agents is switched off. Ask the user to enable \"Allow AI agents to clean up\" "
                        "in Dusty Ai → Settings → AI agents. You can still use dry_run=true.")
    running = _A.running_names()
    ordered = sorted(plan, key=lambda p: not p["id"].startswith("tmp_"))
    results, freed = [], 0.0
    for p in ordered:
        payload, _code = _A.perform_delete(p["id"], running)
        f = payload.get("freed_gb", 0) if payload.get("ok") else 0
        freed += f
        results.append({"id": p["id"], "name": p["name"], "ok": bool(payload.get("ok")), "freed_gb": round(f, 2),
                        "files_in_use_skipped": payload.get("skipped", 0), "error": payload.get("error")})
    before, after = _A.refresh_free(freed)
    out = {"dry_run": False, "results": results, "freed_gb": round(freed, 2), "free_space_before_gb": before,
           "free_space_after_gb": after, "rejected": rejected,
           "note": "Files that are in use are left in place; Dusty Ai never closes programs for agents."}
    _log("clean", {"ids": [p["id"] for p in plan]}, {"freed_gb": out["freed_gb"]})
    return out


TOOLS = [
    ("disk_status", "Free and total space of every drive. Start here.", {}, tool_disk_status, True),
    ("start_scan", "Start scanning drives for caches, temp files and developer junk (read-only, nothing is deleted). "
     "Returns immediately; poll scan_status.",
     {"drives": {"type": "array", "items": {"type": "string"}, "description": "Drive letters, default: the system drive."},
      "deep_scan": {"type": "boolean", "description": "Also walk the whole system drive for big folders (slower, 1-3 min)."},
      "find_duplicates": {"type": "boolean", "description": "Look for duplicate files in Downloads/Documents."},
      "profile_overview": {"type": "boolean", "description": "Overview of the largest profile/AppData folders."}},
     tool_start_scan, False),
    ("scan_status", "Progress of the scan. Waits up to wait_seconds (max 45) for it to finish. When done it includes a "
     "summary.", {"wait_seconds": {"type": "number"}}, tool_scan_status, True),
    ("list_findings", "What the scan found, largest first, with risk A (safe) / B (your call) / C (manual).",
     {"risk": {"type": "string", "enum": ["A", "B", "C"]}, "min_size_gb": {"type": "number"},
      "limit": {"type": "integer", "description": "Default 25, max 100."}}, tool_list_findings, True),
    ("explain_finding", "What a finding is and what happens if it is deleted.",
     {"id": {"type": "string"}}, tool_explain_finding, True),
    ("clean", "Delete findings by id. dry_run defaults to true: it only reports what would be deleted. A real run "
     "needs the user to enable agent cleanup in Dusty Ai Settings. Only risk A items (and B with include_review) of "
     "the cache/Temp/recycle-bin kind can be deleted; programs are never closed.",
     {"ids": {"type": "array", "items": {"type": "string"}}, "risk": {"type": "string", "enum": ["A"],
      "description": "Shortcut for every risk-A finding."}, "dry_run": {"type": "boolean"},
      "include_review": {"type": "boolean", "description": "Allow risk B items (ask the user first)."}},
     tool_clean, False),
]


def _tool_list():
    out = []
    for name, desc, props, _fn, read_only in TOOLS:
        out.append({"name": name, "description": desc,
                    "inputSchema": {"type": "object", "properties": props},
                    "annotations": {"readOnlyHint": read_only, "destructiveHint": name == "clean",
                                    "openWorldHint": False}})
    return out


# ───────────────────────────── protocol ─────────────────────────────

def _ok(i, result):
    return {"jsonrpc": "2.0", "id": i, "result": result}


def _fail(i, code, message):
    return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": message}}


def handle(msg):
    """One JSON-RPC message → response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _fail(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    i, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if "id" not in msg:  # notification: nothing to answer
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        return _ok(i, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": SERVER_NAME, "version": getattr(_A, "APP_VERSION", "1")},
                       "instructions": "Dusty Ai finds disk space taken by caches and junk and explains it. "
                                       "Workflow: disk_status → start_scan → scan_status → list_findings → "
                                       "clean (dry run first, show the plan to the user)."})
    if method == "ping":
        return _ok(i, {})
    if method == "tools/list":
        return _ok(i, {"tools": _tool_list()})
    if method == "tools/call":
        tool = next((t for t in TOOLS if t[0] == params.get("name")), None)
        if not tool:
            return _fail(i, -32602, f"Unknown tool: {params.get('name')}")
        try:
            result = tool[3](params.get("arguments") or {})
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return _ok(i, {"content": [{"type": "text", "text": text}], "structuredContent": result, "isError": False})
        except ToolError as e:
            return _ok(i, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # noqa: BLE001 — never let a tool crash the connection
            return _ok(i, {"content": [{"type": "text", "text": f"Internal error: {e}"}], "isError": True})
    return _fail(i, -32601, f"Method not found: {method}")


def handle_payload(payload):
    """HTTP body: a single message or a batch."""
    if isinstance(payload, list):
        out = [r for r in (handle(m) for m in payload) if r is not None]
        return out or None
    return handle(payload)


# ───────────────────────────── stdio transport ─────────────────────────────

def _log_file(text):
    try:
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        with open(os.path.join(settings.DATA_DIR, "mcp.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except OSError:
        pass


def _std_binary(kind):
    """Binary stdin/stdout. A windowed (no-console) PyInstaller exe has sys.stdin/stdout set to None even when the
    parent gave it pipes, so on Windows the handles are taken from the OS directly."""
    stream = sys.stdin if kind == "in" else sys.stdout
    if stream is not None and hasattr(stream, "buffer"):
        return stream.buffer
    if os.name == "nt":
        import ctypes
        import msvcrt
        h = ctypes.windll.kernel32.GetStdHandle(-10 if kind == "in" else -11)
        if h and h != -1:
            fd = msvcrt.open_osfhandle(h, os.O_RDONLY if kind == "in" else os.O_WRONLY)
            return os.fdopen(fd, "rb" if kind == "in" else "wb", buffering=0)
    return None


def run_stdio():
    """Newline-delimited JSON-RPC over stdin/stdout until the agent closes the pipe."""
    src, dst = _std_binary("in"), _std_binary("out")
    if src is None or dst is None:
        _log_file("stdio is not available: no stdin/stdout handles")
        return
    sys.stdout = sys.stderr if sys.stderr else open(os.devnull, "w")  # stray prints must not corrupt the protocol
    lock = threading.Lock()
    _log_file("mcp stdio session started")
    for raw in iter(src.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            resp = handle_payload(json.loads(line))
        except ValueError:
            resp = _fail(None, -32700, "Parse error")
        except Exception as e:  # noqa: BLE001
            _log_file(f"error: {e!r}")
            resp = _fail(None, -32603, "Internal error")
        if resp is not None:
            with lock:
                dst.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                dst.flush()
    _log_file("mcp stdio session ended")
