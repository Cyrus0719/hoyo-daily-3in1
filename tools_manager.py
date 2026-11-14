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
        # 优先 .7z：官方 full.7z 453MB，full.zip 686MB —— 少下 230MB，还更快
        "match": "March7thAssistant_full", "ext": [".7z", ".zip"],
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

# ---------------------------------------------------------------- 下载源
# 社区经验：GitHub 直连在国内时好时坏（SSL 断流 / 几 KB/s），所以这里给三条路，
# 下载时按顺序自动换源，界面里也能手动指定「只用哪一个」。
SOURCES = {
    "direct": {"name": "GitHub 直连", "kind": "direct", "note": "官方地址；国内经常被卡住或断流"},
    "ghproxy": {"name": "gh-proxy.com 国内镜像", "kind": "mirror",
                "prefix": "https://gh-proxy.com/", "note": "国内可直连，实测比直连快"},
    "local": {"name": "本机代理（127.0.0.1:7897）", "kind": "proxy",
              "proxy": "http://127.0.0.1:7897", "note": "需要你自己开着 Clash / v2ray 一类的代理"},
}
_DEFAULT_ORDER = ["direct", "ghproxy", "local"]
_SRC_FILE = BASE / "config" / "download_sources.json"


def _read_sources():
    try:
        data = json.loads(_SRC_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    order = [s for s in (data.get("order") or []) if s in SOURCES]
    for s in _DEFAULT_ORDER:
        if s not in order:
            order.append(s)
    extra = [str(m).strip() for m in (data.get("extra_mirrors") or []) if str(m).strip()]
    return order, extra


def sources_info():
    """给界面的下载源列表（含顺序与额外镜像）。"""
    order, extra = _read_sources()
    rows = []
    for sid in order:
        info = dict(SOURCES[sid])
        info["id"] = sid
        info["enabled"] = True
        rows.append(info)
    for i, m in enumerate(extra):
        rows.append({"id": "extra%d" % i, "name": "自定义镜像 %s" % m, "kind": "mirror",
                     "prefix": m, "note": "你自己加的镜像前缀", "enabled": True})
    return {"order": order, "extra_mirrors": extra, "sources": rows,
            "proxy_configured": any(SOURCES[s]["kind"] == "proxy" for s in order)}


def save_sources(order=None, extra_mirrors=None, proxy=""):
    cur_order, cur_extra = _read_sources()
    if order is not None:
        cur_order = [s for s in order if s in SOURCES] or list(_DEFAULT_ORDER)
        for s in _DEFAULT_ORDER:
            if s not in cur_order:
                cur_order.append(s)
    if extra_mirrors is not None:
        cur_extra = [str(m).strip() for m in extra_mirrors if str(m).strip()]
    _SRC_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"order": cur_order, "extra_mirrors": cur_extra}
    if proxy:
        data["proxy"] = proxy
    _SRC_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sources_info()


def _url_for(sid, url):
    """把官方 URL 换成某个源上的地址；返回 (url, proxy)。"""
    if sid in SOURCES:
        info = SOURCES[sid]
    else:
        _order, extra = _read_sources()
        try:
            idx = int(sid.replace("extra", ""))
            info = {"kind": "mirror", "prefix": extra[idx]}
        except Exception:  # noqa: BLE001
            info = {"kind": "direct"}
    if info.get("kind") == "mirror":
        return (info.get("prefix") or "") + url, ""
    if info.get("kind") == "proxy":
        return url, info.get("proxy") or ""
    return url, ""


def _log(msg):
    STATE["log"].append("%s %s" % (time.strftime("%H:%M:%S"), msg))
    STATE["log"] = STATE["log"][-200:]
    STATE["msg"] = msg


def _opener(proxy: str):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def _api_json(url: str, token: str = "", proxy: str = ""):
    """GitHub API 也用多源兜底：直连失败就换镜像/本机代理。"""
    headers = {"User-Agent": "hoyo-daily-3in1"}
    if token:
        headers["Authorization"] = "token " + token
    order, _extra = _read_sources()
    errs = []
    for sid in order:
        u, p = _url_for(sid, url)
        try:
            req = urllib.request.Request(u, headers=headers)
            with _opener(p or proxy).open(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            errs.append("%s：%s" % (SOURCES.get(sid, {}).get("name", sid), str(e)[:60]))
    raise RuntimeError("接口请求失败（" + "；".join(errs) + "）")


def latest_asset(repo: str, match: str, ext, proxy: str = "", token: str = "", tag: str = ""):
    """查 release（给了 tag 就查指定版本，否则查最新），返回 (名称, 下载地址, 大小)。

    ext 可以是字符串或列表：列表表示"优先顺序"（三月七的 .7z 比 .zip 小 230MB）。
    """
    api = ("https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag)) if tag \
        else ("https://api.github.com/repos/%s/releases/latest" % repo)
    data = _api_json(api, token or default_token(), proxy)
    exts = [ext] if isinstance(ext, str) else list(ext)
    exts = [e.lower() for e in exts]
    best = None
    for a in data.get("assets", []):
        n = a.get("name", "")
        low = n.lower()
        if match.lower() not in low:
            continue
        for i, e in enumerate(exts):
            if low.endswith(e):
                if best is None or i < best[0]:
                    best = (i, n, a["browser_download_url"], a.get("size", 0))
                break
    if best:
        return best[1], best[2], best[3]
    raise RuntimeError("未找到匹配资产 %s*%s（仓库 %s）" % (match, "|".join(exts), repo))


def _download_one(url: str, dest: Path, proxy: str = "", token: str = ""):
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


_PART = lambda dest: dest.with_suffix(dest.suffix + ".part")


def _drop_part(dest: Path):
    try:
        p = _PART(dest)
        if p.exists():
            p.unlink()
    except OSError:
        pass


def download(url: str, dest: Path, token: str = "", source: str = "", proxy: str = ""):
    """按指定源下载（不换源）。source 为空时用列表里第一个。"""
    order, _extra = _read_sources()
    sid = source or order[0]
    u, p = _url_for(sid, url)
    name = SOURCES.get(sid, {}).get("name", sid)
    _log("下载源：%s" % name)
    return _download_one(u, dest, p or proxy, token)


def download_any(url: str, dest: Path, token: str = "", order=None):
    """按源的顺序依次尝试，谁先用谁（每个源都失败才整体失败）。"""
    order = list(order or _read_sources()[0])
    tried = []
    for sid in order:
        u, p = _url_for(sid, url)
        name = SOURCES.get(sid, {}).get("name", sid)
        _log("尝试下载源：%s" % name)
        try:
            _download_one(u, dest, p, token)
            _log("下载完成（源：%s）" % name)
            return {"source": sid, "name": name, "tried": tried}
        except Exception as e:  # noqa: BLE001
            tried.append("%s：%s" % (name, str(e)[:80]))
            _log("该源失败（%s）：%s" % (name, str(e)[:100]))
            _drop_part(dest)  # 换源不续传，避免拼出坏包
    raise RuntimeError("所有下载源都失败：" + "；".join(tried))


def probe_sources(url: str = "", token: str = "", sample_mb: int = 2):
    """测速：对每个源各取 2MB，返回速度（KB/s）。给界面「测速」按钮用。"""
    if not url:
        try:
            info = TOOLS["march7th"]
            _n, url, _s = latest_asset(info["repo"], info["match"], ".7z", "", token)
        except Exception as e:  # noqa: BLE001
            return {"error": "拿不到测速用的文件：%s" % str(e)[:100], "rows": []}
    order, extra = _read_sources()
    ids = list(order) + ["extra%d" % i for i in range(len(extra))]
    rows = []
    nbytes = int(sample_mb * 1024 * 1024)
    for sid in ids:
        u, p = _url_for(sid, url)
        name = SOURCES.get(sid, {}).get("name", sid)
        t0 = time.time()
        got, err = 0, ""
        try:
            headers = {"User-Agent": "hoyo-daily-3in1", "Range": "bytes=0-%d" % (nbytes - 1)}
            if token:
                headers["Authorization"] = "token " + token
            with _opener(p).open(urllib.request.Request(u, headers=headers), timeout=25) as r:
                while got < nbytes:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
        except Exception as e:  # noqa: BLE001
            err = str(e)[:120]
        dt = max(time.time() - t0, 0.001)
        rows.append({"id": sid, "name": name, "ok": bool(got) and not err,
                     "kbs": int(got / 1024 / dt), "bytes": got, "error": err})
    return {"rows": rows}


def extract(archive: Path, target: Path):
    """解压（zip 用内置、7z 用 Windows 自带 bsdtar），并把单一顶层目录内容上提。"""
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
        got = download_any(url, archive, token=token)
        STATE["source"] = got.get("name", "")
        _log("下载完成，使用源：%s" % got.get("name", ""))
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
    data = _api_json("https://api.github.com/repos/%s/releases/latest" % repo,
                     token or default_token(), proxy)
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