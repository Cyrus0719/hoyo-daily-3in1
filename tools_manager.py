# -*- coding: utf-8 -*-
"""
社区工具下载器：从各工具官方 GitHub Releases 一键下载并解压到标准位置。
  - bettergi   -> tools/BetterGI/BetterGI/BetterGI.exe
  - march7th   -> tools/March7thAssistant/March 7th Assistant.exe
  - onedragon  -> OneDragon-ref/（自带 runtime 的官方打包版）
支持代理、断点重下（临时文件）、进度回调。仅下载官方发布物，不修改其内容。
"""
import json, os, re, shutil, subprocess, time, urllib.request, zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
DL_DIR = BASE / "downloads"

# key -> (GitHub 仓库, 资产名匹配规则, 解压目标, 说明)
TOOLS = {
    "bettergi": {
        "repo": "babalae/better-genshin-impact",
        "match": "BetterGI_v", "ext": ".7z",
        # 跟最新（0.67.0 起恢复）：BetterGI 自己也开着自动更新，这里再钉死版本就会互相打架。
        # 版本检查见 updates()，装了新版本会在配置中心「工具」页显示。
        "tag": "",
        "target": "tools/BetterGI",
        "exe": "tools/BetterGI/BetterGI/BetterGI.exe",
        "desc": "原神 · BetterGI（免安装 7z 包，可一键更新到最新）",
    },
    "march7th": {
        "repo": "moesnow/March7thAssistant",
        "match": "March7thAssistant_full", "ext": ".zip",
        "target": "tools",
        "exe": "tools/March7thAssistant/March7th Assistant.exe",
        "desc": "崩铁 · March7thAssistant（完整包）",
    },
    "onedragon": {
        "repo": "OneDragon-Anything/ZenlessZoneZero-OneDragon",
        "match": "WithRuntime-Full", "ext": ".zip",
        "target": "OneDragon-ref",
        "exe": "",
        "desc": "绝区零 · OneDragon（自带运行时的官方打包版）",
    },
}

STATE = {"running": False, "tool": "", "phase": "", "percent": 0, "msg": "", "done": [], "log": []}


def _log(msg):
    STATE["log"].append("%s %s" % (time.strftime("%H:%M:%S"), msg))
    STATE["log"] = STATE["log"][-200:]
    STATE["msg"] = msg


def _opener(proxy: str):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def latest_asset(repo: str, match: str, ext: str, proxy: str, token: str = "", tag: str = ""):
    """查 release（给了 tag 就查指定版本，否则查最新），返回 (名称, 下载地址, 大小)。"""
    headers = {"User-Agent": "hoyo-daily-3in1"}
    if token:
        headers["Authorization"] = "token " + token
    api = ("https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag)) if tag \
        else ("https://api.github.com/repos/%s/releases/latest" % repo)
    req = urllib.request.Request(api, headers=headers)
    with _opener(proxy).open(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    for a in data.get("assets", []):
        n = a.get("name", "")
        if match.lower() in n.lower() and n.lower().endswith(ext):
            return n, a["browser_download_url"], a.get("size", 0)
    raise RuntimeError("未找到匹配资产 %s*%s（仓库 %s）" % (match, ext, repo))


def download(url: str, dest: Path, proxy: str, token: str = ""):
    """分块下载 + 进度（支持续传：存在 .part 时从断点继续）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": "hoyo-daily-3in1"}
    if token:
        headers["Authorization"] = "token " + token
    done = part.stat().st_size if part.exists() else 0
    if done:
        headers["Range"] = "bytes=%d-" % done
    req = urllib.request.Request(url, headers=headers)
    with _opener(proxy).open(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0) + done
        mode = "ab" if done and r.status == 206 else "wb"
        if mode == "wb":
            done = 0
        with open(part, mode) as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    STATE["percent"] = int(done * 100 / total)
                    STATE["phase"] = "下载中 %d%%（%.0f/%.0f MB）" % (STATE["percent"], done/1048576, total/1048576)
    part.replace(dest)
    return dest


def extract(archive: Path, target: Path):
    """解压（zip 用内置、7z 用 py7zr），并把单一顶层目录内容上提。"""
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / "_extract_tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        # .7z：优先用 Windows 自带的 bsdtar（C:\Windows\System32\tar.exe）。
        # py7zr 解 BetterGI 的 7z 会失败（"Invalid 7z archive"），bsdtar 一直能解。
        txt = ""
        try:
            bsdtar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
            exe = str(bsdtar) if bsdtar.exists() else "tar"
            p = subprocess.run([exe, "-xf", str(archive), "-C", str(tmp)],
                               capture_output=True, text=True, timeout=3600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if p.returncode == 0:
                txt = ""
            else:
                txt = (p.stderr or p.stdout or "").strip()
        except Exception as e:  # noqa: BLE001
            txt = str(e)
        if txt.startswith("garbage") or txt.startswith("tar:") or txt.startswith("This does not look like"):
            txt = ""
        if txt:
            raise RuntimeError("解压失败（%s）：%s" % (archive.name, txt[:200]))
    entries = [p for p in tmp.iterdir()]
    src = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
    for item in src.iterdir():
        dst = target / item.name
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
            else:
                dst.unlink()
        shutil.move(str(item), str(dst))
    shutil.rmtree(tmp, ignore_errors=True)


def install_one(key: str, proxy: str = "", token: str = ""):
    info = TOOLS[key]
    name, url, size = latest_asset(info["repo"], info["match"], info["ext"], proxy, token,
                                  tag=info.get("tag", ""))
    _log("找到 %s（%.0f MB）" % (name, size / 1048576))
    archive = DL_DIR / name
    if archive.exists() and archive.stat().st_size == size:
        _log("已存在同名完整安装包，跳过下载")
    else:
        download(url, archive, proxy, token)
    _log("解压中…")
    STATE["phase"] = "解压中…"
    extract(archive, BASE / info["target"])
    try:  # 记下这次装的是哪个 release，下次好比对（上游自己不一定写版本号）
        tag = latest_tag(info["repo"], proxy, token)
        if tag:
            (BASE / info["target"] / ".installed_version").write_text(tag + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _log("完成：%s" % info["desc"])


def install(keys, proxy: str = "", token: str = ""):
    STATE.update({"running": True, "done": [], "percent": 0, "phase": "准备中", "log": []})
    try:
        for k in keys:
            if k not in TOOLS:
                continue
            STATE["tool"] = k
            _log("=== 开始安装 %s ===" % TOOLS[k]["desc"])
            install_one(k, proxy, token)
            STATE["done"].append(k)
    except Exception as e:
        _log("失败：%s" % e)
        STATE["phase"] = "失败：%s" % e
    finally:
        STATE["running"] = False
        STATE["phase"] = STATE["phase"] if STATE["phase"].startswith("失败") else "全部完成"


def status():
    return {"running": STATE["running"], "tool": STATE["tool"], "phase": STATE["phase"],
            "percent": STATE["percent"], "done": STATE["done"], "log": STATE["log"][-40:],
            "installed": {k: (BASE / v["exe"]).exists() if v["exe"] else (BASE / v["target"]).exists() for k, v in TOOLS.items()}}

# ---------------------------------------------------------------- 版本 / 检查更新
def _read(p: Path, n: int = 200) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore").strip()[:n]
    except Exception:  # noqa: BLE001
        return ""


def installed_version(key: str) -> str:
    """读本机已装版本。读不到就返回空字符串（界面上显示「未记录」，不是 0）。"""
    info = TOOLS[key]
    base = BASE / info["target"]
    if key == "bettergi":
        # BetterGI 自己把当前版本写在这里
        try:
            cfg = json.loads((base / "BetterGI" / "User" / "config.json").read_text(encoding="utf-8"))
            return str((cfg.get("commonConfig") or {}).get("runForVersion") or "").strip()
        except Exception:  # noqa: BLE001
            return ""
    if key == "march7th":
        # 它的 target 是 tools/（包里带一层 March7thAssistant），所以从 exe 反推目录
        return _read(Path(info["exe"]).parent / "assets" / "config" / "version.txt")
    # 绝区零：上游源码里 __version__ 是占位 v0.0.0，只能靠我们自己装的标记
    return _read(base / ".installed_version")


def default_token() -> str:
    """GitHub token：环境变量 GITHUB_TOKEN 优先，其次是 config/github_token.txt（已 gitignore）。
    匿名调用每小时只有 60 次，检查更新很容易撞限流。"""
    tok = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if tok:
        return tok
    return _read(BASE / "config" / "github_token.txt", 200)


def latest_tag(repo: str, proxy: str = "", token: str = "") -> str:
    headers = {"User-Agent": "hoyo-daily-3in1"}
    token = token or default_token()
    if token:
        headers["Authorization"] = "token " + token
    req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % repo, headers=headers)
    with _opener(proxy).open(req, timeout=45) as r:
        data = json.loads(r.read().decode("utf-8"))
    return str(data.get("tag_name") or "").strip()


_UPD = {"t": 0.0, "data": None}


def updates(proxy: str = "", token: str = "", force: bool = False, ttl: int = 1800):
    """检查三个上游工具是否有新版。缓存 30 分钟（GitHub 匿名 API 每小时 60 次）。"""
    now = time.time()
    if not force and _UPD["data"] is not None and now - _UPD["t"] < ttl:
        return _UPD["data"]
    out = []
    token = token or default_token()
    for key, info in TOOLS.items():
        cur = installed_version(key)
        item = {"key": key, "desc": info["desc"], "installed": cur, "latest": "",
                "has_update": None, "error": "", "installed_ok": (BASE / info["exe"]).exists() if info["exe"]
                else (BASE / info["target"]).exists()}
        try:
            tag = latest_tag(info["repo"], proxy, token)
            item["latest"] = tag
            if tag and cur:
                item["has_update"] = _norm_ver(tag) != _norm_ver(cur)
            else:
                item["has_update"] = None      # 版本未知就别瞎说"有新版"
        except Exception as e:  # noqa: BLE001
            item["error"] = "查询失败：%s" % str(e)[:120]
        out.append(item)
    _UPD.update({"t": now, "data": out})
    return out


def _norm_ver(v: str) -> str:
    v = str(v or "").strip().lower().lstrip("v")
    return re.sub(r"[^0-9a-z.]", "", v)


def summary_line(proxy: str = "", token: str = "") -> str:
    """一行摘要，给每日运行日志用。"""
    try:
        rows = updates(proxy, token)
    except Exception as e:  # noqa: BLE001
        return "检查更新失败：%s" % str(e)[:100]
    parts = []
    for r in rows:
        name = {"bettergi": "BetterGI", "march7th": "三月七", "onedragon": "OneDragon"}.get(r["key"], r["key"])
        if r["error"]:
            parts.append("%s 查询失败" % name)
        elif r["has_update"]:
            parts.append("%s %s→%s 有新版本" % (name, r["installed"] or "?", r["latest"]))
        else:
            parts.append("%s %s" % (name, r["latest"] or r["installed"] or "?"))
    return "；".join(parts)