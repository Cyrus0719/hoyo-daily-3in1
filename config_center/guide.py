# -*- coding: utf-8 -*-
"""帮助与排查：关键路径 + 上游文档链接 + 常见问题对照表。

三件事：
1. 把「上游软件里那些指引」变成可点的路径（配置文件在哪、日志在哪、文档在哪）；
2. 常见症状 → 该看哪个文件的哪一行；
3. 本项目的 GitHub 入口（Star / Issue / Release）。
"""
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BG = BASE / "tools" / "BetterGI" / "BetterGI"
M7A = BASE / "tools" / "March7thAssistant"
OD = BASE / "OneDragon-ref"
LOCALLOW = Path(os.environ.get("USERPROFILE") or Path.home()) / "AppData" / "LocalLow" / "miHoYo"

REPO = "Cyrus0719/hoyo-daily-3in1"
HOME = "https://github.com/" + REPO

# 允许「打开」的根目录（其余一律拒绝，避免被拿来做任意文件打开）
ALLOW_ROOTS = [BASE, LOCALLOW]


def _safe(path):
    """路径必须在允许的根目录里。"""
    try:
        p = Path(path).resolve()
    except Exception:  # noqa: BLE001
        return None
    for root in ALLOW_ROOTS:
        try:
            p.relative_to(root.resolve())
            return p
        except Exception:  # noqa: BLE001
            continue
    return None


def _p(label, path, hint=""):
    p = Path(path)
    try:
        rel = str(p.relative_to(BASE))
    except ValueError:
        rel = str(p)
    if p.is_dir():
        kind = "dir"
    elif p.is_file():
        kind = "file"
    else:
        kind = "missing"
    row = {"label": label, "path": str(p), "rel": rel, "kind": kind,
           "exists": kind != "missing", "hint": hint}
    try:
        if kind == "file":
            row["mtime"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            row["size"] = p.stat().st_size
        elif kind == "dir":
            row["mtime"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            row["size"] = len(list(p.iterdir())) if p.is_dir() else 0
    except Exception:  # noqa: BLE001
        pass
    return row


def _l(label, url):
    return {"label": label, "url": url}


def _game_log_dir(name):
    return LOCALLOW / name


GROUPS = [
    {
        "key": "genshin",
        "title": "原神 · BetterGI",
        "sub": "一条龙的开关、秘境、地脉花都在 daily.json；失败了先看 log 目录当天的日志。",
        "paths": [
            _p("一条龙每日任务（开关/顺序/秘境/地脉花/首领）", BG / "User" / "OneDragon" / "daily.json",
               "配置中心『原神』页改的就是它；BetterGI 界面里改过的话以界面为准"),
            _p("BetterGI 主设置", BG / "User" / "config.json",
               "遮罩窗口、分辨率、快捷键、自动更新开关"),
            _p("战斗策略脚本目录", BG / "User" / "AutoFight",
               "自动战斗按角色名匹配策略，缺角色就站着不动；我们兜底的『自动补全.txt』也在这里"),
            _p("BetterGI 日志目录", BG / "log",
               "每跑一次一个 better-genshin-impactYYYYMMDD.log，失败特征全在里面"),
            _p("游戏自己的日志（掉登录时最有用）", _game_log_dir("原神") / "output_log.txt",
               "出现 failed to parse account list 说明本地登录缓存坏了，需要你手动登一次"),
        ],
        "links": [
            _l("BetterGI 文档", "https://bettergi.com/docs/"),
            _l("常见问题 FAQ", "https://bettergi.com/faq.html"),
            _l("快速上手", "https://bettergi.com/quickstart.html"),
            _l("自动战斗策略说明", "https://bettergi.com/feats/task/domain.html"),
            _l("GitHub 仓库", "https://github.com/babalae/better-genshin-impact"),
            _l("已有 issue（先搜再提）", "https://github.com/babalae/better-genshin-impact/issues"),
        ],
    },
    {
        "key": "starrail",
        "title": "崩坏：星穹铁道 · 三月七助手",
        "sub": "清体力计划、每日实训、周常都在 config.yaml；它自己也有大量带注释的默认配置。",
        "paths": [
            _p("三月七配置", M7A / "config.yaml",
               "配置中心『崩铁』页都写这里；config.yaml 是稀疏文件，没写的就是用默认值"),
            _p("完整默认配置（每个键都有中文注释）", M7A / "assets" / "config" / "config.example.yaml",
               "想知道某个键是什么意思、能填什么，直接搜这个文件"),
            _p("三月七日志目录", M7A / "logs",
               "每天一个 YYYY-MM-DD.log；『账号登录过期』『没有找到游戏窗口』都在里面"),
            _p("游戏自己的日志", _game_log_dir("崩坏：星穹铁道") / "Player.log",
               "登录态、崩溃信息；游戏没起来时这里通常是空的"),
        ],
        "links": [
            _l("三月七文档站", "https://march7th.xyz/"),
            _l("GitHub Wiki", "https://github.com/moesnow/March7thAssistant/wiki"),
            _l("GitHub 仓库", "https://github.com/moesnow/March7thAssistant"),
            _l("已有 issue（先搜再提）", "https://github.com/moesnow/March7thAssistant/issues"),
        ],
    },
    {
        "key": "zzz",
        "title": "绝区零 · OneDragon",
        "sub": "每个功能一份配置（config/01/one_dragon/*.yml）；出问题先看 .log/log.txt。",
        "paths": [
            _p("实例配置目录（游戏路径、账号、通知）", OD / "config" / "01",
               "game.yml 游戏路径 / game_account.yml 账号 / notify.yml 通知"),
            _p("一条龙各功能配置", OD / "config" / "01" / "one_dragon",
               "daily_signin.yml、lost_void.yml、charge_plan.yml… 配置中心『绝区零』页逐项改的就是它们"),
            _p("自动战斗配置", OD / "config" / "auto_battle",
               "『全配队通用』等样板；换战斗策略时改这里"),
            _p("OneDragon 运行日志", OD / ".log",
               "log.txt 是当前这次；历史按日期留档。窗口/截图/账号问题都在这"),
            _p("日志（旧版路径，可能不存在）", OD / "logs", "老版本放这里，新版在 .log"),
            _p("自带的运维指南", OD / "docs" / "运维指南", "上游自己写的排障手册，本机就有"),
        ],
        "links": [
            _l("快速开始", "https://one-dragon.com/zzz/zh/quickstart.html"),
            _l("必要设置（分辨率/窗口）", "https://one-dragon.com/zzz/zh/config.html"),
            _l("常见问题 FAQ", "https://one-dragon.com/zzz/zh/faq.html"),
            _l("功能说明 · 一条龙", "https://one-dragon.com/zzz/zh/feat/feat_one_dragon/onedragon.html"),
            _l("自动战斗教程", "https://one-dragon.com/zzz/zh/auto_battle_guide/basic/basic_00_intro.html"),
            _l("装不上/下载不动？Github 访问指南", "https://one-dragon.com/other/zh/visit_github.html"),
            _l("GitHub 仓库", "https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon"),
            _l("已有 issue（先搜再提）", "https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/issues"),
        ],
    },
    {
        "key": "ours",
        "title": "本项目（胶水层）",
        "sub": "每天跑一轮的总控、日志、备份都在这儿。提 issue 请带上 logs/daily.log 的对应那一段。",
        "paths": [
            _p("总控日志（先看这个）", BASE / "logs" / "daily.log",
               "每次运行一行『执行结束 ok=True/False』，失败原因也写在这里"),
            _p("绝区零 CLI 日志", BASE / "logs" / "zzz_cli.log", "OneDragon 这条命令的完整输出"),
            _p("配置修改记录", BASE / "logs" / "config_changes.log", "谁在什么时候改了哪个文件"),
            _p("登录失败截图", BASE / "logs" / "login", "自动登录失手时的截图，方便看卡在验证码还是别的"),
            _p("配置自动备份", BASE / "config" / "backup", "每保存一次留一份，可在『备份与恢复』页回滚"),
            _p("总控配置", BASE / "config" / "daily_config.yaml", "时间、顺序、各游戏开关与目标"),
            _p("账号密码", BASE / "config" / "accounts.yaml", "明文保存，已加入 .gitignore，不会进仓库"),
        ],
        "links": [
            _l("项目主页（Star 一下）", HOME),
            _l("提 issue / 看别人怎么解决的", HOME + "/issues"),
            _l("发布页（下载最新版）", HOME + "/releases"),
            _l("README 完整说明", HOME + "#readme"),
        ],
    },
]

TROUBLES = [
    {
        "title": "今天没跑 / 跑的时间不对",
        "why": "计划任务没触发、开机太早（开机不满 10 分钟会等），或者上一次卡住没结束。",
        "items": [
            _p("总控日志（搜『执行结束』或『开机』）", BASE / "logs" / "daily.log", "每次运行一行『执行结束 ok=True/False』，失败原因、树脂消耗、开机判断都写在这里"),
            {"label": "打开『定时与运行』页", "page": "schedule"},
        ],
    },
    {
        "title": "原神站着挨打、战斗失败、一点树脂没花",
        "why": "多数是自动战斗没匹配到角色脚本（队伍里有人没写策略），或地脉花寻路失败。",
        "items": [
            _p("BetterGI 今日日志", BG / "log", "搜『未匹配到任何战斗脚本』『战斗失败，重新寻找地脉花』"),
            _p("战斗策略脚本目录", BG / "User" / "AutoFight", "看有没有覆盖你队伍里的角色"),
            {"label": "自动战斗策略怎么写（官方文档）", "url": "https://bettergi.com/feats/task/domain.html"},
            {"label": "BetterGI 常见问题", "url": "https://bettergi.com/faq.html"},
        ],
    },
    {
        "title": "要重新登录 / 掉登录",
        "why": "游戏自己的登录态过期或本地登录缓存损坏；上游工具都不保存账号密码，只能靠我们兜底自动登录。",
        "items": [
            _p("登录失败截图", BASE / "logs" / "login", "看看是卡在验证码、滑块，还是根本没弹出登录框"),
            _p("原神游戏日志", _game_log_dir("原神") / "output_log.txt", "搜 failed to parse account list"),
            {"label": "打开『账号与登录』页", "page": "accounts"},
            {"label": "OneDragon 常见问题", "url": "https://one-dragon.com/zzz/zh/faq.html"},
        ],
    },
    {
        "title": "崩铁跑完了不退出 / 一直『没有找到游戏窗口』",
        "why": "三月七遇到登录过期会一直空转截图；我们会在命中『账号登录过期』时强制收尾。",
        "items": [
            _p("三月七今日日志", M7A / "logs", "搜『账号登录过期』『没有找到游戏窗口』"),
            _p("三月七完整默认配置", M7A / "assets" / "config" / "config.example.yaml", ""),
            {"label": "三月七 Wiki", "url": "https://github.com/moesnow/March7thAssistant/wiki"},
        ],
    },
    {
        "title": "绝区零没画面 / 窗口未找到 / 一启动就退出",
        "why": "绝区零窗口受保护，必须前台模式；分辨率、HDR、显示档不对都会读不到图。",
        "items": [
            _p("绝区零 CLI 日志", BASE / "logs" / "zzz_cli.log", "搜『未获取到游戏截图』『执行出错』"),
            _p("OneDragon 日志", OD / ".log", "看它卡在哪个节点"),
            _p("本机运维指南", OD / "docs" / "运维指南", "上游自己写的排障手册"),
            {"label": "必要设置（分辨率/窗口）", "url": "https://one-dragon.com/zzz/zh/config.html"},
            {"label": "常见问题 FAQ", "url": "https://one-dragon.com/zzz/zh/faq.html"},
        ],
    },
    {
        "title": "下载 / 更新失败（连不上 GitHub）",
        "why": "国内直连 GitHub 经常断，换个下载源或者走本机代理。",
        "items": [
            {"label": "打开『工具』页（换下载源、测速）", "page": "tools"},
            {"label": "OneDragon 的 Github 访问指南", "url": "https://one-dragon.com/other/zh/visit_github.html"},
            {"label": "本项目发布页（直接下 zip）", "url": HOME + "/releases"},
        ],
    },
    {
        "title": "窗口被拉成别的比例 / 提示分辨率不是 16:9",
        "why": "上游只认 16:9 的窗口（常见 1920x1080）；我们跑的时候会临时切窗口化再拉回来。",
        "items": [
            _p("显示模式设置", BASE / "config" / "display_user.json", "你自己平时的全屏/窗口设置，跑完会恢复成这个"),
            _p("总控日志", BASE / "logs" / "daily.log", "搜『窗口』『期间修正』"),
            {"label": "BetterGI FAQ", "url": "https://bettergi.com/faq.html"},
        ],
    },
    {
        "title": "改了配置没生效",
        "why": "优先级是：上游软件界面 > config/daily_config.yaml。界面上有值的话，我们只会照界面的跑。",
        "items": [
            {"label": "打开『全部配置』看原文", "page": "advanced"},
            _p("总控配置", BASE / "config" / "daily_config.yaml", ""),
            _p("本次到底写了什么（每次运行前都会重写一次）", BG / "User" / "OneDragon" / "daily.json", ""),
        ],
    },
]


# ---------------------------------------------------------------- GitHub 信息
_REPO_CACHE = {"at": 0.0, "data": None}
_REPO_LOCK = threading.Lock()


def _token():
    try:
        import tools_manager as tm
        return tm.default_token()
    except Exception:  # noqa: BLE001
        return ""


def _api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + _token(), "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "hoyo-daily-config-center"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode() or "{}")


def repo_info(force=False):
    """星标数、issue 数、最新 release —— 拿不到就返回空，不影响页面。"""
    with _REPO_LOCK:
        if not force and _REPO_CACHE["data"] and time.time() - _REPO_CACHE["at"] < 1800:
            return _REPO_CACHE["data"]
    data = {"repo": REPO, "home": HOME, "stars": None, "forks": None, "issues": None,
            "pushed_at": "", "release": "", "release_url": "", "error": ""}
    try:
        r = _api("/repos/" + REPO)
        data.update({"stars": r.get("stargazers_count"), "forks": r.get("forks_count"),
                     "issues": r.get("open_issues_count"), "pushed_at": r.get("pushed_at", ""),
                     "description": r.get("description") or ""})
        try:
            rel = _api("/repos/" + REPO + "/releases/latest")
            data.update({"release": rel.get("tag_name") or "", "release_url": rel.get("html_url") or "",
                         "release_at": rel.get("published_at") or ""})
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        data["error"] = "%s: %s" % (type(e).__name__, e)
    with _REPO_LOCK:
        _REPO_CACHE["data"] = data
        _REPO_CACHE["at"] = time.time()
    return data


def guide_payload(force=False):
    return {"repo": repo_info(force=force), "groups": GROUPS, "troubles": TROUBLES,
            "base": str(BASE)}


# ---------------------------------------------------------------- 打开路径
def reveal(path):
    """在资源管理器里打开目录 / 定位到文件。"""
    p = _safe(path)
    if p is None:
        raise ValueError("只能打开本项目目录或游戏日志目录里的路径: %s" % path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_dir():
        os.startfile(str(p))  # noqa: S606
    else:
        args = ['explorer', '/select,%s' % str(p)]
        try:
            subprocess.Popen(args)  # noqa: S603,S607
        except Exception:  # noqa: BLE001
            os.startfile(str(p.parent))  # noqa: S606
    return p
