# -*- coding: utf-8 -*-
"""配置中心 · HTTP 接口层（前端在 web/ 目录，纯静态，无需构建）。"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from config_center import registry as R  # noqa: E402
from config_center import options as OPT  # noqa: E402
import tools_manager as tm  # noqa: E402
import task_sched  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
LOG_DIR = BASE / "logs"
DAILY_LOG = LOG_DIR / "daily.log"
GAMES = [("genshin", "原神"), ("starrail", "崩坏：星穹铁道"), ("zzz", "绝区零")]
GAME_KEYS = [g[0] for g in GAMES]
TOOL_LABELS = {"bettergi": ("BetterGI", "原神"), "march7th": ("三月七助手", "崩铁"),
               "onedragon": ("OneDragon", "绝区零")}
LOG_SOURCES = {
    "daily": ("总控日志", DAILY_LOG),
    "config": ("配置修改记录", LOG_DIR / "config_changes.log"),
    "zzz": ("绝区零 CLI", LOG_DIR / "zzz_cli.log"),
}

JOB = {"running": False, "mode": "", "started": "", "code": None, "msg": "", "since": 0.0}
JOB_LOCK = threading.Lock()


# --------------------------------------------------------------------------- 小工具
def _tail(path: Path, lines=200, q="", encodings=("utf-8", "gbk")):
    if not path.is_file():
        return "", "文件不存在: %s" % path.name
    size = path.stat().st_size
    block = min(size, 700_000)
    with open(path, "rb") as fh:
        fh.seek(size - block)
        raw = fh.read()
    text = None
    for enc in encodings:
        try:
            text = raw.decode(enc, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    rows = text.splitlines()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r.lower()]
    rows = rows[-lines:]
    return "\n".join(rows), ""


def _newest(pattern_dir: Path, pattern: str):
    if not pattern_dir.is_dir():
        return None
    files = sorted(pattern_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_daily_log(limit=4000):
    """从总控日志里取三个游戏最近一次的结果 + 最近一次整体结束时间。"""
    if not DAILY_LOG.is_file():
        return {}, ""
    try:
        rows = _tail(DAILY_LOG, limit)[0].splitlines()
    except OSError:
        return {}, ""
    out = {}
    last_ts = ""
    for line in rows:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
        if m:
            last_ts = m.group(1)
        m2 = re.search(r"\[(\w+)\] 执行结束 ok=(True|False)", line)
        if m2 and m2.group(1) in GAME_KEYS:
            out[m2.group(1)] = {"ok": m2.group(2) == "True", "at": last_ts}
    return out, last_ts


def summary():
    info = task_sched.task_info()
    runs, last_ts = _parse_daily_log()
    st = tm.status()
    tools = []
    for key, (label, game) in TOOL_LABELS.items():
        tools.append({"key": key, "label": label, "game": game,
                      "installed": bool(st["installed"].get(key))})
    cfg = {}
    try:
        meta, doc, _ = R.load_doc("ours")
        cfg = doc or {}
    except Exception:  # noqa: BLE001
        pass
    sched_cfg = (cfg.get("scheduler") or {}) if isinstance(cfg, dict) else {}
    games = []
    for key, name in GAMES:
        g = ((cfg.get("games") or {}).get(key) or {}) if isinstance(cfg, dict) else {}
        run = runs.get(key)
        games.append({
            "key": key, "name": name, "enabled": bool(g.get("enabled", True)),
            "last": ({"ok": run["ok"], "at": run["at"]} if run else None),
            "auto_login": bool(g.get("auto_login", True)),
        })
    return {
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": "周" + "一二三四五六日"[max(0, min(6, time.localtime().tm_wday))],
        "task": info,
        "daily_time": sched_cfg.get("daily_time", ""),
        "run_order": sched_cfg.get("run_order", GAME_KEYS),
        "games": games,
        "tools": tools,
        "tools_state": {"running": st.get("running"), "phase": st.get("phase", ""),
                        "percent": st.get("percent", 0), "tool": st.get("tool", "")},
        "last_activity": last_ts,
        "job": dict(JOB),
    }


# --------------------------------------------------------------------------- 原神一条龙
_DAYS = [("Monday", "周一"), ("Tuesday", "周二"), ("Wednesday", "周三"),
         ("Thursday", "周四"), ("Friday", "周五"), ("Saturday", "周六"), ("Sunday", "周日")]


def genshin_tasks():
    meta, doc, _ = R.load_doc("bg_daily")
    defs = doc.get("TaskDefinitions") or {}
    en = doc.get("TaskEnabledList") or {}
    order = doc.get("TaskOrder") or []
    tasks = []
    for i, guid in enumerate(order):
        tasks.append({"guid": guid, "name": defs.get(guid, guid), "index": i,
                      "enabled": bool(en.get(guid)), "path": "TaskEnabledList." + guid})
    for guid, nm in defs.items():  # 有定义但不在顺序表里的也列出来
        if guid in order:
            continue
        tasks.append({"guid": guid, "name": nm, "index": -1,
                      "enabled": bool(en.get(guid)), "path": "TaskEnabledList." + guid})
    days = []
    for key, cn in _DAYS:
        days.append({
            "key": key, "cn": cn,
            "enabled": bool(doc.get("LeyLineRun" + key, False)),
            "type": doc.get("LeyLine" + key + "Type", "") or "",
            "country": doc.get("LeyLine" + key + "Country", "") or "",
        })
    fields = [
        ("PartyName", "打本队伍名", "str"),
        ("DomainName", "默认秘境", "str"),
        ("WeeklyDomainEnabled", "打每周秘境（周本）", "bool"),
        ("DailyRewardPartyName", "领每日奖励队伍", "str"),
        ("MinResinToKeep", "至少保留原粹树脂", "int"),
        ("LeyLineRunCount", "地脉花次数", "int"),
        ("LeyLineResinExhaustionMode", "地脉花：树脂耗尽模式", "bool"),
        ("CraftingBenchCountry", "合成台所在国家", "str"),
        ("AdventurersGuildCountry", "冒险家协会国家", "str"),
        ("SereniteaPotTpType", "尘歌壶传送方式", "str"),
        ("CompletionAction", "全部完成后做什么", "str"),
    ]
    out_fields = []
    for key, label, typ in fields:
        out_fields.append({"key": key, "label": label, "type": typ,
                           "value": doc.get(key), "path": key})
    ley_cfg = {
        "LeyLineOneDragonMode": doc.get("LeyLineOneDragonMode"),
        "LeyLineOpenModeCountMin": doc.get("LeyLineOpenModeCountMin"),
    }
    return {"name": doc.get("Name", "daily"), "tasks": tasks, "days": days,
            "fields": out_fields, "ley": ley_cfg,
            "rel": "tools/BetterGI/BetterGI/User/OneDragon/daily.json"}


def genshin_save(payload):
    ops = []
    for guid, val in (payload.get("tasks") or {}).items():
        ops.append({"op": "set", "path": "TaskEnabledList." + guid, "value": bool(val)})
    for key, val in (payload.get("fields") or {}).items():
        ops.append({"op": "set", "path": key, "value": val})
    for day, val in (payload.get("days") or {}).items():
        if "enabled" in val:
            ops.append({"op": "set", "path": "LeyLineRun" + day, "value": bool(val["enabled"])})
        if "type" in val:
            ops.append({"op": "set", "path": "LeyLine" + day + "Type", "value": val["type"]})
        if "country" in val:
            ops.append({"op": "set", "path": "LeyLine" + day + "Country", "value": val["country"]})
    return R.save_ops("bg_daily", ops, note="原神一条龙任务")


# --------------------------------------------------------------------------- 账号
def _mask(s):
    s = str(s or "")
    if not s:
        return ""
    if len(s) <= 4:
        return "*" * len(s)
    return s[:3] + "*" * max(2, len(s) - 5) + s[-2:]


def accounts_get():
    meta, doc, _ = R.load_doc("accounts")
    out = []
    for key, name in GAMES:
        sec = (doc or {}).get(key) or {}
        out.append({"game": key, "name": name,
                    "account": _mask(sec.get("account")),
                    "has_password": bool(sec.get("password")),
                    "raw_account": sec.get("account") or ""})
    return {"games": out, "path": "config/accounts.yaml"}


def accounts_save(payload):
    ops = []
    for key, vals in (payload or {}).items():
        if key not in GAME_KEYS:
            continue
        acc = vals.get("account")
        pwd = vals.get("password")
        if acc is not None and "*" not in str(acc):
            ops.append({"op": "set", "path": key + ".account", "value": str(acc)})
        if pwd is not None and pwd != "":
            ops.append({"op": "set", "path": key + ".password", "value": str(pwd)})
    if not ops:
        return {"ok": True, "changed": 0}
    return R.save_ops("accounts", ops, note="账号密码")


def _fid_of_backup(name):
    """备份文件名是 <safe_id>_<时间戳>.<ext>，反推出是哪个文件。"""
    for f in R.list_files():
        safe = f["id"].replace(":", "_").replace("/", "_")
        if name.startswith(safe + "_"):
            return f["id"]
    raise ValueError("认不出这份备份属于哪个文件: %s" % name)


# --------------------------------------------------------------------------- 计划任务
def set_schedule(payload):
    hhmm = str(payload.get("daily_time") or "").strip()
    if not re.match(r"^\d{2}:\d{2}$", hhmm):
        raise ValueError("时间格式必须是 HH:MM")
    h, m = [int(x) for x in hhmm.split(":")]
    if h > 23 or m > 59:
        raise ValueError("时间超出范围")
    R.save_ops("ours", [{"op": "set", "path": "scheduler.daily_time", "value": hhmm}],
               note="每日运行时间")
    ok, msg = task_sched.register_task(hhmm)
    return {"ok": True, "task_synced": ok,
            "msg": "已同步 Windows 计划任务" if ok else
                   ("配置已保存，但计划任务同步失败（需要管理员权限）：" + msg[:160] +
                    " —— 下次自动运行时程序会自己再同步一次")}


# --------------------------------------------------------------------------- 运行
def run_now(payload):
    mode = str(payload.get("mode") or "all")
    with JOB_LOCK:
        if JOB["running"]:
            return {"ok": False, "msg": "已经有一次运行在进行中"}
        JOB.update({"running": True, "mode": mode, "code": None, "msg": "",
                    "started": time.strftime("%H:%M:%S"), "since": time.time()})
    if mode == "all":
        r = subprocess.run(["schtasks", "/Run", "/TN", task_sched.TASK_NAME],
                           capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ok = r.returncode == 0
        with JOB_LOCK:
            JOB.update({"running": False, "code": r.returncode,
                        "msg": "已通过计划任务启动（有管理员权限，无 UAC）" if ok else
                               ("启动失败: " + (r.stdout or r.stderr or "").strip()[:200])})
        return {"ok": ok, "msg": JOB["msg"]}
    if mode not in GAME_KEYS:
        with JOB_LOCK:
            JOB["running"] = False
        raise ValueError("未知的游戏: %s" % mode)

    def _worker():
        try:
            exe = str(BASE / ".venv" / "Scripts" / "python.exe")
            proc = subprocess.Popen([exe, str(BASE / "auto_daily.py"), mode], cwd=str(BASE),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            code = proc.wait()
            with JOB_LOCK:
                JOB.update({"running": False, "code": code,
                            "msg": "结束，退出码 %s（详见总控日志）" % code})
        except Exception as e:  # noqa: BLE001
            with JOB_LOCK:
                JOB.update({"running": False, "code": -1, "msg": "启动失败: %s" % e})

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "msg": "已启动 %s，进度看『日志』页；若配置中心不是以管理员身份运行，"
                               "BetterGI 会弹一次 UAC 提权" % mode}


# --------------------------------------------------------------------------- 工具
def updates_get(force=False):
    """三个上游程序的版本对比（带 30 分钟缓存；网络不通不影响页面）。"""
    try:
        rows = tm.updates(force=force)
    except Exception as e:  # noqa: BLE001
        return {"tools": [], "error": "%s: %s" % (type(e).__name__, e)}
    out = []
    for r in rows:
        label, game = TOOL_LABELS.get(r["key"], (r["key"], ""))
        r = dict(r)
        r.update({"label": label, "game": game})
        out.append(r)
    return {"tools": out, "error": ""}


def tools_get():
    st = tm.status()
    upd = {r["key"]: r for r in updates_get().get("tools") or []}
    rows = []
    for key, meta in tm.TOOLS.items():
        label, game = TOOL_LABELS.get(key, (key, ""))
        rel = meta.get("exe") or meta.get("target") or ""
        u = upd.get(key) or {}
        rows.append({"key": key, "label": label, "game": game,
                     "installed": bool(st["installed"].get(key)),
                     "path": str(rel), "repo": meta.get("repo", ""),
                     "tag": meta.get("tag") or "最新版",
                     "version": u.get("installed") or "",
                     "latest": u.get("latest") or "",
                     "has_update": u.get("has_update"),
                     "check_error": u.get("error") or ""})
    return {"tools": rows, "state": st}


def tools_install(payload):
    key = str(payload.get("key") or "")
    if key not in tm.TOOLS:
        raise ValueError("未知工具: %s" % key)
    if tm.STATE.get("running"):
        return {"ok": False, "msg": "已有下载任务在进行: %s" % tm.STATE.get("phase")}
    threading.Thread(target=tm.install, kwargs={"keys": [key]}, daemon=True).start()
    return {"ok": True, "msg": "已开始下载 %s" % key}


def tools_launch(payload):
    key = str(payload.get("key") or "")
    meta = tm.TOOLS.get(key)
    if not meta:
        raise ValueError("未知工具: %s" % key)
    exe_rel = meta.get("exe")
    exe = (BASE / exe_rel) if exe_rel else None
    if not exe or not exe.is_file():
        return {"ok": False, "msg": "还没安装（先点『下载/更新』）"}
    subprocess.Popen([str(exe)], cwd=str(exe.parent),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return {"ok": True, "msg": "已启动 %s（它自己可能要一次 UAC）" % exe.name}


# --------------------------------------------------------------------------- 日志
def log_get(name, lines, q):
    lines = max(20, min(3000, int(lines or 200)))
    if name in LOG_SOURCES:
        title, path = LOG_SOURCES[name]
    elif name == "genshin":
        title, path = "BetterGI 今日日志", _newest(BASE / "tools" / "BetterGI" / "BetterGI" / "log",
                                                  "better-genshin-impact*.log")
    elif name == "starrail":
        title, path = "三月七最新日志", _newest(BASE / "tools" / "March7thAssistant" / "logs", "*.log")
    else:
        raise ValueError("未知日志: %s" % name)
    if path is None:
        return {"title": title, "text": "", "error": "还没有日志文件"}
    text, err = _tail(Path(path), lines, q)
    return {"title": title, "file": Path(path).name, "text": text, "error": err,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Path(path).stat().st_mtime))}


def logs_list():
    rows = []
    for key, (title, path) in LOG_SOURCES.items():
        rows.append({"key": key, "title": title, "exists": Path(path).is_file()})
    g = _newest(BASE / "tools" / "BetterGI" / "BetterGI" / "log", "better-genshin-impact*.log")
    s = _newest(BASE / "tools" / "March7thAssistant" / "logs", "*.log")
    rows.append({"key": "genshin", "title": "BetterGI 日志" + ("（" + g.name[-12:-4] + "）" if g else ""),
                 "exists": bool(g)})
    rows.append({"key": "starrail", "title": "三月七日志" + ("（" + s.name + "）" if s else ""),
                 "exists": bool(s)})
    return {"logs": rows}


# --------------------------------------------------------------------------- 程序设置（我们的）
def our_settings():
    meta, doc, _ = R.load_doc("ours")
    doc = doc or {}
    sched = doc.get("scheduler") or {}
    games = doc.get("games") or {}
    out = {
        "rel": "config/daily_config.yaml",
        "scheduler": {
            "daily_time": {"value": sched.get("daily_time", ""), "type": "str",
                           "label": "每天几点跑", "help": "HH:MM"},
            "run_order": {"value": sched.get("run_order", []), "type": "list",
                          "label": "运行顺序", "help": "依次运行"},
            "timeout_minutes": {"value": sched.get("timeout_minutes", 120), "type": "int",
                                "label": "单次总超时（分钟）", "help": ""},
            "min_uptime_minutes": {"value": sched.get("min_uptime_minutes", 10), "type": "int",
                                   "label": "开机后至少稳定（分钟）", "help": "太早跑会冷启动失败"},
            "boot_wait_max_minutes": {"value": sched.get("boot_wait_max_minutes", 20), "type": "int",
                                      "label": "最多等（分钟）", "help": ""},
        },
        "games": {},
    }
    for key, name in GAMES:
        g = games.get(key) or {}
        fields = {}
        for k, v in g.items():
            if k == "targets":
                continue
            if isinstance(v, (dict, list)):
                continue
            fields[k] = {"value": v, "type": ("bool" if isinstance(v, bool) else
                                              "int" if isinstance(v, int) else "str"),
                         "label": _our_label(key, k), "help": ""}
        targets = []
        for i, t in enumerate(g.get("targets") or []):
            if isinstance(t, dict):
                targets.append({"index": i,
                                "fields": [{"k": kk, "v": vv, "type": type(vv).__name__}
                                           for kk, vv in t.items()]})
        out["games"][key] = {"name": name, "fields": fields, "targets": targets}
    return out


_OUR_LABELS = {
    "enabled": "启用这个游戏", "name": "显示名", "region": "区服", "client_path": "游戏路径",
    "party_name": "打本队伍名", "stall_minutes": "卡死判定（分钟）", "resin_policy": "树脂策略",
    "fuel_policy": "开拓力策略", "battery_policy": "电量策略", "do_daily": "做每日",
    "claim_rewards": "领奖励", "do_commissions": "每日委托", "claim_welkin": "领月卡",
    "claim_katheryne": "凯瑟琳奖励", "mode": "客户端模式", "auto_login": "掉登录时自动登录",
    "display": "窗口设置",
}


def _our_label(game, key):
    return _OUR_LABELS.get(key, key)


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "HoyoConfigCenter/1.0"

    def log_message(self, fmt, *args):  # 安静点
        pass

    # ---- 基础输出
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _err(self, msg, code=400, detail=""):
        self._json({"ok": False, "error": str(msg), "detail": detail}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8"))

    # ---- 静态
    def _static(self, rel):
        p = (WEB / rel).resolve()
        if not str(p).startswith(str(WEB.resolve())) or not p.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}.get(
            p.suffix, "application/octet-stream")
        self._send(200, p.read_bytes(), ctype)  # _send 里已经带 no-store

    # ---- GET
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            from urllib.parse import parse_qs
            qs = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/api/"):
                return self._api_get(path, qs)
            return self._static(path.lstrip("/"))
        except KeyError as e:
            return self._err(str(e).strip("'\""), 404)
        except FileNotFoundError as e:
            return self._err("找不到文件: %s" % e, 404)
        except ValueError as e:
            return self._err(e, 400)
        except Exception as e:  # noqa: BLE001
            return self._err(e, 500, traceback.format_exc(limit=4))

    def _api_get(self, path, qs):
        if path == "/api/summary":
            return self._json(summary())
        if path == "/api/files":
            return self._json({"files": R.list_files(force=True)})
        if path == "/api/tree":
            return self._json(R.build_tree(qs.get("fid", "")))
        if path == "/api/raw":
            return self._json(R.raw_read(qs.get("fid", "")))
        if path == "/api/backups":
            return self._json({"backups": R.list_backups(qs.get("fid") or None),
                               "files": R.list_files()})
        if path == "/api/log":
            return self._json(log_get(qs.get("name", "daily"), qs.get("lines", 200), qs.get("q", "")))
        if path == "/api/logs":
            return self._json(logs_list())
        if path == "/api/tools":
            return self._json(tools_get())
        if path == "/api/updates":
            return self._json(updates_get(force=qs.get("force") in ("1", "true", "yes")))
        if path == "/api/options":
            return self._json(OPT.payload())
        if path == "/api/genshin":
            return self._json(genshin_tasks())
        if path == "/api/accounts":
            return self._json(accounts_get())
        if path == "/api/ours":
            return self._json(our_settings())
        if path == "/api/job":
            with JOB_LOCK:
                j = dict(JOB)
            if j.get("since"):
                j["elapsed"] = int(time.time() - j["since"])
            return self._json(j)
        return self._err("未知接口: " + path, 404)

    # ---- POST
    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        try:
            body = self._body()
        except Exception as e:  # noqa: BLE001
            return self._err("请求体不是合法 JSON: %s" % e)
        try:
            if path == "/api/save":
                fid = body.get("fid") or ""
                res = R.save_ops(fid, body.get("ops") or [], note=body.get("note") or "")
                return self._json(res)
            if path == "/api/raw":
                return self._json(R.raw_write(body.get("fid") or "", body.get("text")))
            if path == "/api/restore":
                name = body.get("name") or ""
                fid = body.get("fid") or _fid_of_backup(name)
                R.restore_backup(fid, name)
                return self._json({"ok": True, "msg": "已恢复"})
            if path == "/api/schedule":
                return self._json(set_schedule(body))
            if path == "/api/run":
                return self._json(run_now(body))
            if path == "/api/tools/install":
                return self._json(tools_install(body))
            if path == "/api/tools/launch":
                return self._json(tools_launch(body))
            if path == "/api/genshin":
                return self._json(genshin_save(body))
            if path == "/api/accounts":
                return self._json(accounts_save(body))
            if path == "/api/open":
                fid = body.get("fid") or ""
                meta = R.get(fid)
                os.startfile(str(meta["path"].parent))  # noqa: S606
                return self._json({"ok": True, "msg": "已打开所在文件夹"})
        except FileNotFoundError as e:
            return self._err("文件不存在: %s" % e, 404)
        except KeyError as e:
            return self._err("找不到配置: %s" % e, 404)
        except ValueError as e:
            return self._err(e, 400)
        except Exception as e:  # noqa: BLE001
            return self._err(e, 500, traceback.format_exc(limit=4))
        return self._err("未知接口: " + path, 404)


def pick_port(a=8900, b=8999):
    import socket
    for p in range(a, b + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return b


DEFAULT_PORT = 8900
PID_FILE = BASE / "logs" / "config_center.port"


def _is_ours(port: int) -> bool:
    """8900 上跑的是不是我们自己（重复点桌面快捷方式时不该再起一个）。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/summary" % port, timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return "daily_time" in data
    except Exception:  # noqa: BLE001
        return False


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    no_browser = "--no-browser" in argv
    if _is_ours(DEFAULT_PORT):
        url = "http://127.0.0.1:%d/" % DEFAULT_PORT
        print("配置中心已经在运行: %s" % url)
        if not no_browser:
            _open_browser(url)
        return 0
    port = pick_port(DEFAULT_PORT, 8999)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(port), encoding="utf-8")
    except OSError:
        pass
    print("配置中心已启动: %s" % url)
    if not no_browser:
        threading.Timer(0.6, _open_browser, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    main()