# -*- coding: utf-8 -*-
# BetterGI（原神）引擎适配器
# 原理：
#   1) 按 daily_config 目标生成一条龙配置 -> BetterGI/User/OneDragon/daily.json（固定名，常驻可编辑）
#      （任务开关：领取邮件/合成树脂/自动秘境/领取每日奖励/领取尘歌壶；自动幽境危战=关）
#   2) 启动 BetterGI.exe startOneDragon daily
#      - 若本进程已是管理员（定时任务 /RL HIGHEST 场景）→ 直接启动，【无 UAC 弹窗】
#      - 否则用 runas 提权（手动运行场景，弹一次 UAC）
#   3) 配置 CompletionAction="关闭游戏和软件"，BetterGI 跑完会自动关游戏并退出自身
import ctypes
import datetime
import json
import os
import re
import subprocess
import sys
import threading
def _run_hidden(cmd, **kw):
    """静默子进程：无控制台窗口（提权 pythonw 下反复闪终端的问题修复）。"""
    kw.setdefault("capture_output", True)
    if not kw.get("creationflags"):
        # Windows: CREATE_NO_WINDOW
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, **kw)

import time
import logging
from pathlib import Path

log = logging.getLogger("auto_daily")

BASE = Path(__file__).resolve().parent.parent          # 项目根目录（本文件在 adapters/ 下）
# 默认 <项目根>/tools/BetterGI/BetterGI；可用环境变量 HOYO_BETTERGI_DIR 覆盖
BETTERGI_DIR = Path(os.environ.get("HOYO_BETTERGI_DIR") or (BASE / "tools" / "BetterGI" / "BetterGI"))
sys.path.insert(0, str(BASE))   # 能 import 到项目根的模块
import win_guard   # noqa: E402  游戏窗口兜底（16:9 检查/纠正）
import game_proc   # noqa: E402  温和关闭游戏进程（先礼后兵，见 game_proc.py 顶部说明）
try:
    import login_helper   # noqa: E402  掉登录时自动用账号密码登录（绝不用验证码）
except Exception as _login_err:   # noqa: BLE001  依赖缺失不该拖垮整个适配器
    login_helper = None
    logging.getLogger(__name__).warning("[login] 登录兜底不可用: %s", _login_err)
BETTERGI_EXE = BETTERGI_DIR / "BetterGI.exe"
ONEDRAGON_DIR = BETTERGI_DIR / "User" / "OneDragon"
# 日志在包根目录的 log/ 下（User/log 是旧路径，实测不存在 —— 之前完成标记因此一直没生效）
LOG_DIR = BETTERGI_DIR / "log"
ONE_DRAGON_CONFIG = ONEDRAGON_DIR / "daily.json"   # 固定配置名：可编辑、不删除
COMPLETE_MARK = "一条龙和配置组任务结束"

# ── 战斗脚本自动补全（2026-11-13 定案）────────────────────────────────
# 「站在那里挨打」的根因：战斗脚本不认识队伍里的角色。
#   BetterGI 的逻辑（GameTask/AutoFight/Script/CombatScriptBag.cs::SelectCombatScript）：
#   把 User/AutoFight 下所有 .txt 逐份与队伍角色取交集，匹配人数最多的那份胜出，
#   【一个都不匹配就 throw "未匹配到任何战斗脚本"】→ AutoFight 一次按键都不发 = 站桩挨打
#   → "战斗失败，重新寻找地脉花" → 多轮后 "已达最大重试次数" → 整轮白跑、树脂没花。
#   本机 AutoFight 目录里只有一份 8 月下载的「万能战斗策略（萌新推荐）」（43 个角色），
#   队伍换成它没收录的新角色（桑多涅/薇斯纳/沃雅妮莎/尼可）就零命中。
#   我们不碰用户/群友的脚本：自己维护一份补全文件，把日志里出现过但谁都不认识的角色
#   按通用连招补一行，下一次一条龙就能匹配上（匹配人数少也不会抢走群友那份）。
AUTOFIGHT_DIR = BETTERGI_DIR / "User" / "AutoFight"
FALLBACK_SCRIPT = AUTOFIGHT_DIR / "自动补全.txt"
FALLBACK_HEADER = (
    "// 由 hoyo-daily-3in1 自动维护：把「队伍里有、但所有战斗脚本都不认识」的角色补一条通用连招。" + chr(10) +
    "// 只求别让 BetterGI 抛「未匹配到任何战斗脚本」站桩挨打；有正式策略后可整份删掉。" + chr(10)
)
_TEAM_RE = re.compile(r'识别到的队伍角色[:：]\s*"([^"]+)"')
# 本次运行里"补全脚本"新增了哪些角色（_should_retry 用它判断该不该立刻再跑一趟）
_HEAL_ADDED = []

GENERIC_COMBAT = "e, attack(0.3), check, wait(0.3), keypress(q), wait(0.1), ready, check, wait(0.3)"


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _launch(exe: Path, args: str, cwd: Path):
    """提权感知启动：已是管理员直接启动（无 UAC），否则 runas（弹一次 UAC）。

    返回 Popen（只有管理员直启才有）；调用方拿它取退出码 —— 早退时退出码能区分
    "被系统杀掉/崩掉" 和 "引擎自己决定收工"（2026-11-13 起记录，以前什么都没留下）。"""
    if _is_admin():
        proc = subprocess.Popen([str(exe), args], cwd=str(cwd))
        log.info("[BetterGI] 管理员上下文中直接启动（无 UAC）")
        return proc
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), args, str(cwd), 1)
    log.info("[BetterGI] 非提权上下文 runas 启动 rc=%s（UAC 一次，>32=成功）", rc)
    return None


def kill_bettergi_if_running():
    _run_hidden(["taskkill", "/IM", "BetterGI.exe", "/F"], capture_output=True)
    time.sleep(1)


def _close_game(exe: str, grace_s: int = 45) -> bool:
    """温和关闭游戏进程 —— 真正的规则在 game_proc.close（先 WM_CLOSE，等它自己退）。

    2026-11-14 改：以前是本文件里的「礼貌 8 秒 → 直接 /F」。8 秒太短，也不看进程
    刚启动多久。2026-11-13 12:47 原神就是在启动 1 秒时被 /F 硬杀，当晚游戏要求
    重新登录（本地快速登录缓存被写坏）。现在只有存活 >= 180 秒的进程才允许强杀，
    刚启动的进程返回 False，由调用方按「游戏还开着」处理。
    返回 True = 进程已经退出。"""
    return game_proc.close(exe, grace_s=grace_s, force_after_s=180)


def kill_game_if_running(client_path: str = "") -> bool:
    """关掉原神客户端并等它彻底退出（让 BetterGI 自己走"打开游戏 → 进游戏"的完整流程）。
    返回 True = 游戏已经不在运行（False 表示它刚启动、我们拒绝强杀）。"""
    exe = Path(client_path).name if client_path else "YuanShen.exe"
    return _close_game(exe)


# ── 原神本地「快速登录」缓存体检（2026-11-14 新增）────────────────────
# 游戏自己的日志（不是 BetterGI 的）在 LocalLow 下。本地账号列表解析失败时会出现
# `failed to parse account list` + `Decode exception has occurred.`，游戏就停在登录页，
# 一条龙再多跑几趟也进不去 —— 必须让用户手动登录一次。这里只做「提前说清楚」。
GENSHIN_LOCALLOW = (Path(os.environ.get("USERPROFILE", "") or ".")
                    / "AppData" / "LocalLow" / "miHoYo" / "原神")
GENSHIN_GAME_LOG = GENSHIN_LOCALLOW / "output_log.txt"
LOGIN_FAIL_MARKS = ("failed to parse account list", "Decode exception has occurred")
_LOGIN_CACHE_BROKEN = False       # 本次运行里是否发现登录缓存坏了（坏了就不重试）


def _game_log_size() -> int:
    try:
        return GENSHIN_GAME_LOG.stat().st_size
    except OSError:
        return -1


def _game_log_new(base: int, max_bytes: int = 4_000_000) -> str:
    """原神自己日志里「本次新增」的部分（文件被换/截断时退回读全量尾部）。"""
    try:
        size = GENSHIN_GAME_LOG.stat().st_size
        if size <= 0:
            return ""
        start = base if 0 <= base <= size else max(0, size - max_bytes)
        with GENSHIN_GAME_LOG.open("rb") as fp:
            fp.seek(start)
            data = fp.read(min(size - start, max_bytes))
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


LEYLINE_ASSET = BETTERGI_DIR / "GameTask" / "AutoLeyLineOutcrop" / "Assets" / "config.json"


def _leyline_supported_countries() -> list:
    """当前 BetterGI 的地脉花任务支持哪些国家（读它的资源文件，别猜）。

    键名跨版本变过：0.64 用 mapPositions，0.66 改成 leyLinePositions（并新增了"至冬"）。"""
    try:
        data = json.loads(LEYLINE_ASSET.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    for key in ("leyLinePositions", "mapPositions"):
        val = data.get(key)
        if isinstance(val, dict) and val:
            return list(val.keys())
    return []


def _check_leyline_countries(data: dict) -> None:
    """地脉花按"星期X + 国家"配置。若配的国家当前版本不支持，任务会直接失败
    （实测报 "冒险之证未找到国家: 至冬"），这里提前把话说清楚。"""
    supported = _leyline_supported_countries()
    if not supported:
        return
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    bad = []
    enabled_day = False
    for d in days:
        if data.get("LeyLineRun" + d):
            enabled_day = True
            c = (data.get("LeyLine%sCountry" % d) or "").strip()
            if c and c not in supported:
                bad.append("%s=%s" % (d, c))
    if bad:
        log.warning("[BetterGI] 地脉花配的国家当前版本不支持，会直接失败: %s（本版本支持: %s）",
                    ", ".join(bad), "/".join(supported))
    elif enabled_day:
        log.info("[BetterGI] 地脉花国家检查通过（%s）", "/".join(supported))


DAY_ALIASES = {
    "monday": 0, "mon": 0, "周一": 0, "星期一": 0, "1": 0,
    "tuesday": 1, "tue": 1, "周二": 1, "星期二": 1, "2": 1,
    "wednesday": 2, "wed": 2, "周三": 2, "星期三": 2, "3": 2,
    "thursday": 3, "thu": 3, "周四": 3, "星期四": 3, "4": 3,
    "friday": 4, "fri": 4, "周五": 4, "星期五": 4, "5": 4,
    "saturday": 5, "sat": 5, "周六": 5, "星期六": 5, "6": 5,
    "sunday": 6, "sun": 6, "周日": 6, "周天": 6, "星期日": 6, "星期天": 6, "0": 6, "7": 6,
}


def _parse_days(days) -> set:
    """把 config 里的 days 解析成 weekday 集合（0=周一 … 6=周日）。"
    支持 ["Friday","周六"] / "周五~周日" / "5-6" 这几种写法。"""
    if not days:
        return set()
    items = days if isinstance(days, (list, tuple)) else [days]
    out = set()
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        for sep in ("~", "～", "到", "-"):
            if sep in s:
                a, _, b = s.partition(sep)
                ka, kb = DAY_ALIASES.get(a.strip().lower()), DAY_ALIASES.get(b.strip().lower())
                if ka is not None and kb is not None:
                    d = ka
                    while True:
                        out.add(d)
                        if d == kb:
                            break
                        d = (d + 1) % 7
                    break
            else:
                k = DAY_ALIASES.get(s.lower())
                if k is not None:
                    out.add(k)
    return out


def _day_ok(t: dict) -> bool:
    """这个 target 配了 days 就只在那些天生效；没配 = 每天生效。"""
    days = _parse_days(t.get("days"))
    if not days:
        return True
    return datetime.date.today().weekday() in days


def _find_target(cfg: dict, *keys):
    for t in (cfg.get("targets") or []):
        name = "%s%s" % (t.get("name") or "", t.get("mission_name") or "")
        if any(k in name for k in keys):
            return t
    return None


def _task_switches(cfg: dict, target: dict) -> dict:
    """返回"我们要写进 daily.json 的任务开关"。**没提到的任务一律不写**。

    优先级规则（用户 2026-10-10 明确要求：界面里配的应该算数）：
      1) 秘境（自动秘境）：按当前 target 的 `days` 规则开/关 —— 这是你要求的按天轮换；
      2) 额外任务（幽境危战 / 地脉花 / 首领讨伐）：只有配置里**显式写了 true/false** 才由我们控制；
         写 `enabled: ui`（默认）或干脆不写这一条 → 完全听 BetterGI 界面的（你在界面里关掉就关掉）；
      3) 日常四项（邮件 / 合成树脂 / 每日奖励 / 尘歌壶）：不由我们写，界面里怎么勾就怎么跑。"""
    sw = {
        # 圣遗物本：配了 days 就按天开（例如只在周五~周日打）
        "自动秘境": bool(target.get("enabled", True)) and _day_ok(target),
    }
    for name, keys in (("自动幽境危战", ("幽境",)),
                       ("自动地脉花", ("地脉",)),
                       ("自动首领讨伐", ("首领",))):
        t = _find_target(cfg, *keys)
        if t is None:
            continue
        val = t.get("enabled", "ui")
        if isinstance(val, str):
            log.info("[BetterGI] %s 的开关听 BetterGI 界面（配置里是 enabled: %s）", name, val)
            continue
        sw[name] = bool(val) and _day_ok(t)
    return sw


def make_one_dragon_config(game_key: str, cfg: dict, target: dict, batch: str, idx: int,
                           switch_override: dict = None) -> Path:
    """生成/更新持久化一条龙配置（daily.json）。用户手动改过的非任务字段会被保留。

    switch_override：临时覆盖某些任务开关（例如"第 1 趟先别打地脉花/秘境"）。"""
    domain = target["name"]
    settings = {
        "Name": "daily",
        "CraftingBenchCountry": "枫丹",
        "AdventurersGuildCountry": "枫丹",
        "WeeklyDomainEnabled": False,
        "DailyRewardPartyName": "",
        "MinResinToKeep": 0,
        "SundayEverySelectedValue": "0",
        "SundaySelectedValue": "0",
        "SereniteaPotTpType": "地图传送",
        "SecretTreasureObjects": [],
        "CompletionAction": "关闭游戏和软件",
    }
    data = {}
    if ONE_DRAGON_CONFIG.exists():
        try:
            data = json.loads(ONE_DRAGON_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    # 用户已改过的值优先，本适配器只覆写下面这几个字段
    for k, v in settings.items():
        data.setdefault(k, v)
    data["Name"] = "daily"
    # ★ 优先级：BetterGI 界面 > 我们的配置。界面里填了就用界面的，界面空着才用配置里的值。
    if (data.get("PartyName") or "").strip():
        log.info("[BetterGI] 队伍用界面里设的: %s（配置里的 %s 本次不用）",
                 data["PartyName"], cfg.get("party_name", ""))
    else:
        data["PartyName"] = cfg.get("party_name", "")
    today = datetime.date.today().strftime("%A")   # Monday / Tuesday ...
    weekly = (data.get("%sDomainName" % today) or "").strip() if data.get("WeeklyDomainEnabled") else ""
    if weekly:
        log.info("[BetterGI] 每周秘境生效：%s = %s（默认秘境 %s 本次不用）", today, weekly, data.get("DomainName"))
    elif (data.get("DomainName") or "").strip():
        log.info("[BetterGI] 默认秘境用界面里设的: %s（配置里的 %s 本次不用）", data["DomainName"], domain)
    else:
        data["DomainName"] = domain
    # ★ 任务开关必须按 BetterGI 自己的 GUID 键写：TaskDefinitions 是 {GUID: 任务名}。
    #   写成中文名会被 BetterGI 的既有 TaskEnabledList 覆盖，开关等于没生效（实测踩坑）。
    defs = data.get("TaskDefinitions") or {}
    guid_of = {v: k for k, v in defs.items()}
    tel = data.get("TaskEnabledList") or {}
    switches = _task_switches(cfg, target)
    if switch_override:
        switches.update(switch_override)
    for name, want in switches.items():
        g = guid_of.get(name)
        if g:
            tel[g] = want   # 只写 BetterGI 认得的任务，避免留下无对应任务的野键
    data["TaskEnabledList"] = tel
    path = ONE_DRAGON_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("一条龙配置(可编辑/常驻): %s", path)
    _check_leyline_countries(data)
    return path


def _tail_text(f, max_bytes: int = 300_000) -> str:
    """只读文件尾部（避免整读大日志导致主流程卡死）。"""
    try:
        size = f.stat().st_size
        with open(f, "rb") as fp:
            if size > max_bytes:
                fp.seek(size - max_bytes)
            data = fp.read()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


# 跑完要扫的"没跑成"特征。BetterGI 内部任务失败时进程照样正常退出，
# 不扫这些就会只看到 ok=True —— 2026-09-19/20 就是这样连挂两天没人发现。
# 2026-10-14 补：内部任务失败的真实文案是 "自动地脉花执行失败" / "自动秘境执行失败"
#   （异常类型是 System.Exception，文案里是"执行失败"不是"执行异常"），
#   旧清单漏了它，于是 10-14 地脉花只打了 2 次就挂、daily.log 仍报"无失败特征"+ok=True。
# 2026-11-09 补：当天冷启动（07:00:43 开机、07:10 就跑）原神第一次启动极慢，
#   BetterGI 等不到主界面 → 自己把游戏杀掉重开 → 一条龙被取消。当天日志里【没有】任何旧特征，
#   于是 daily.log 又写了"日志检查通过"+ok=True，实际树脂 0 消耗、邮件以外一件没做。
#   新增："任务被取消"、"A task was canceled"（一条龙被中止的原文）、"请先启动BetterGI"（引擎崩掉的原味）。
FAIL_PATTERNS = ("游戏窗口分辨率不是 16:9", "识别出战角色失败", "任务启动失败",
                 "执行异常", "执行失败", "已达最大重试次数",
                 "任务被取消", "A task was canceled", "请先启动BetterGI",
                 # 2026-11-13：队伍里没有任何一个角色被任何战斗脚本认识时，AutoFight 直接抛这句，
                 # 一个键都不按 = 站在那里挨打。补全脚本（自动补全.txt）会在本次之后自动写，
                 # 但这一趟仍必须判失败，否则又变成"引擎退出就是 ok"的假成功。
                 "未匹配到任何战斗脚本")

# 非致命但值得盯的"退化"特征：命中只 WARNING，不判失败。
# "放弃此路径点" 是 至冬 地脉花寻路出问题的强信号（历史上只在 10-14 出现过 4 次，
# 那天 6 次地脉花只完成 2 次）；偶尔放弃一个点还能自己恢复，所以不直接判失败。
# 2026-10-15 补 "战斗失败，重新寻找地脉花"：当天出现 3 次 —— 识别到队伍角色后
# "未完整匹配到当前队伍" → 退化成"万能战斗策略（萌新推荐）" → 白打一轮再重新找花。
# 2026-10-16 补 "未完整匹配到当前队伍"：同一个根因在【自动秘境】路径上的签名。
#   地脉花那条已在 10-15 加上，但秘境路径不走"重新寻找地脉花"，只留这一句，
#   于是"退化成通用策略"照样打通关（挑战达成）→ 既不判失败、也不出任何 WARNING，
#   汇总日志里完全隐形（10-16 当天 4 次、日志却写"检查通过：无失败特征"）。
#   10-07 起连续 10 天出现（4~9 次/天），加进这里只为让它在 daily.log 里显形，不改判定。
# 2026-10-18 补 "存在角色死亡"：当天第 4 趟秘境战斗中途阵亡，引擎自动传去七天神像
#   复活后重跑一次才领到奖励（多花约 2 分钟，树脂没损失）。进程正常退出、日志里也
#   没有任何 FAIL 特征，于是又一次变成"检查通过"完全隐形 —— 这趟其实重跑过。
#   加进软告警只为让"重跑过"在 daily.log 里留痕，不判失败（引擎自己救回来了）。
SOFT_WARN_PATTERNS = ("放弃此路径点", "距离过远", "战斗失败，重新寻找地脉花",
                      "未完整匹配到当前队伍", "存在角色死亡")

# 树脂不够时"卡在领奖页"的特征（2026-10-15 首次出现，21 天日志里零先例）。
# 固定次数模式(LeyLineResinExhaustionMode=false)不会自己停：树脂花光后照样去打第 N 次，
# 到领奖页找不到能点的树脂选项 → 重试 2 次 → "自动地脉花执行失败:无法领取奖励"。
# 当天 5 次 × 40 = 200（正好是树脂上限），第 6 次没钱付 —— 属于"次数配得比树脂多"，
# 不是寻路/脚本坏了，所以单独把 OCR 原文记下来，方便一眼分辨。
RESIN_BLOCKED_PATTERNS = ("奖励页面树脂识别结果未匹配成功", "无法领取奖励")

# "幽境危战真的打了"的痕迹（只有活动开着并进战斗才会出现）
STYGIAN_RAN_MARKS = ("自动幽境危战：执行战斗策略", "自动幽境危战：挑战成功",
                     "自动幽境危战：选择Boss并开始挑战")
# "活动没开"的痕迹
STYGIAN_CLOSED_MARKS = ("活动已结束", "紊乱爆发期已结束", "未开启")


def _stygian_ran(text: str) -> bool:
    """本次日志里幽境危战是否真的开打了（= 活动在奖励周期内）。"""
    return any(m in text for m in STYGIAN_RAN_MARKS)


_LOG_BASE = {"name": "", "size": 0}


def _log_size() -> int:
    """当前最新日志文件的字节数（给"卡死看门狗"判断引擎还有没有在动）。"""
    try:
        f = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[0]
        return f.stat().st_size
    except Exception:
        return 0


def _log_baseline() -> None:
    """记下"本次启动前"日志写到哪了。只看之后新增的内容，
    否则会把上一次运行留下的完成标记/失败特征误当成这次的。"""
    try:
        f = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[0]
        _LOG_BASE["name"], _LOG_BASE["size"] = f.name, f.stat().st_size
        log.info("[BetterGI] 日志基线: %s @ %d 字节", f.name, _LOG_BASE["size"])
    except Exception:
        _LOG_BASE["name"], _LOG_BASE["size"] = "", 0


def _new_log_text(max_bytes: int = 300_000) -> str:
    """本次运行以来新增的日志文本（跨天换文件时退化为读尾部）。"""
    try:
        files = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return ""
    if not files:
        return ""
    newest = files[0]
    if _LOG_BASE["name"] and newest.name == _LOG_BASE["name"]:
        try:
            with open(newest, "rb") as fp:
                fp.seek(min(_LOG_BASE["size"], newest.stat().st_size))
                return fp.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return _tail_text(newest, max_bytes)


def _report_log_failures() -> bool:
    """扫本次运行日志里的失败特征，命中就在主日志里报 WARNING，并返回 True（=本次失败）。

    返回 True 时调用方会把本次运行判为失败，这样 daily.log 里不会再出现
    "引擎已退出 + ok=True" 的假成功。"""
    text = _new_log_text()
    if not text:
        return False
    failed = False
    hits = {p: text.count(p) for p in FAIL_PATTERNS if p in text}
    amounts = [int(m) for m in re.findall(
        r"使用\s*[“\"”]?(?:原粹|浓缩|脆弱|须臾)树脂[”\"’]?\s*[,，]?\s*数量[：:]\s*(\d+)", text)]
    # 2026-10-19：树脂花光导致的“执行失败”不是故障 —— 固定次数模式(LeyLineResinExhaustionMode=false)
    #   不会自己停：当天至冬地脉花领了 4 次（40+40+40+20=140 树脂），第 5 次到领奖页已经一粒树脂都没有
    #   （OCR 原文：“使用20个原粹树脂补充…今日还可使用6次”），引擎重试 2 次后报
    #   “自动地脉花执行失败:无法领取奖励”，被 FAIL_PATTERNS 里的“执行失败”整轮判成失败。
    #   10-18 报告早已预警：至冬 6 次 × 40 = 240 > 树脂上限(200)，周一~周四几乎必然触发。
    #   降级条件刻意收窄：必须“领奖页明确说树脂不够 + 本次确实花过树脂 + 失败特征只有执行失败”，
    #   这样“领奖页认不出新弹窗”“寻路卡死”之类的真故障仍然照旧判失败。
    resin_short = ("无法领取奖励" in text) and bool(amounts) and \
                  ("原粹树脂补充" in text or "今日还可使用" in text)
    expected = resin_short and set(hits) <= {"执行失败"}
    if hits and not expected:
        log.error("[BetterGI] 日志有失败特征（本次没跑完）: %s", hits)
        failed = True
    elif hits:
        log.warning("[BetterGI] 树脂已花光，固定次数打不满（预期，不判失败）: %s；"
                    "本次已花 %d 树脂（%s）—— 想打满请到 BetterGI 界面把地脉花次数调低",
                    hits, sum(amounts), "+".join(str(a) for a in amounts))
    else:
        log.info("[BetterGI] 日志检查通过：无失败特征")
    soft = {p: text.count(p) for p in SOFT_WARN_PATTERNS if p in text}
    if soft:
        log.warning("[BetterGI] 日志有寻路/重试退化特征（可能少刷了）: %s", soft)
    # 树脂不够导致"卡在领奖页"的诊断：把领奖页 OCR 原文也写进 daily.log，
    # 这样"无法领取奖励"到底是树脂花光了、还是引擎认不出新弹窗，一眼能分辨。
    blocked = {p: text.count(p) for p in RESIN_BLOCKED_PATTERNS if p in text}
    if blocked:
        _lvl = log.warning if expected else log.error
        _lvl("[BetterGI] ⚠ 领奖页选不出树脂（%s）—— 固定次数模式下树脂花光就会这样："
             "任务不会自己停，会一直重试到失败。对照下面『本次树脂消耗』，"
             "若已把树脂花光，就是树脂不够（不是寻路/脚本坏了）", blocked)
        m = re.search(r'奖励页面树脂识别结果未匹配成功，ocr="([^"]*)"', text)
        if m:
            _lvl("[BetterGI] 领奖页 OCR 原文: %s", m.group(1))
    # 树脂账：把"这次花掉多少树脂"直接写进 daily.log，省得每天翻引擎日志。
    # （10-13 是 0 树脂静静地失败，10-14 是只花了 80/120）
    spent = bool(amounts) or re.search(r"使用\s*[“\"”]?(原粹|浓缩|脆弱|须臾)树脂", text) is not None
    if amounts:
        log.info("[BetterGI] 本次树脂消耗: %d（%d 次领取: %s）", sum(amounts), len(amounts),
                 "+".join(str(a) for a in amounts))
    # 兜底：启用了"要花树脂"的任务，日志里却一点树脂都没花 → 大声报警
    #（10/10 就是这么静悄悄失败的：秘境进了、F 按了、然后没了，树脂 0 消耗）
    wanted = ("自动秘境任务：执行" in text) or ("自动地脉花" in text) or ("自动幽境危战" in text)
    if wanted and not spent:
        log.error("[BetterGI] ⚠ 本次启用了要花树脂的任务，但日志里没有任何树脂消耗 —— "
                  "大概率没跑成（去看 BetterGI 日志的最后一屏）")
        failed = True
    return failed


def _log_has_mark() -> bool:
    """本次运行以来的日志里有没有完成标记。"""
    return COMPLETE_MARK in _new_log_text()


def _should_retry() -> bool:
    """第一趟没跑完时，值不值得再跑一趟？

    只在"确实早死"的形态下重试，避免正常跑完但日志里没找到标记时白跑第二趟（还可能多花树脂）：
      · 本次日志一个字都没写  → 引擎压根没起来
      · 出现"任务被取消/A task was canceled/游戏已退出/请先启动BetterGI" → 早死（11-09 的形态）
      · 日志里没有任何"任务启动"记录 → 空转
    """
    if _LOGIN_CACHE_BROKEN:
        # 2026-11-14：本地快速登录缓存坏了，重开游戏也只会又停在登录页 ——
        # 而且多开一次游戏就多一次写坏别的本地数据的风险，直接放弃重试。
        log.warning("[BetterGI] 原神本地快速登录缓存异常，跳过重试（需要用户手动登录一次）")
        return False
    text = _new_log_text()
    if not text.strip():
        return True
    # 注意顺序：BetterGI 即使某个任务失败，也照样会写「一条龙和配置组任务结束」，
    # 所以这两个判断必须在 COMPLETE_MARK 之前。
    if "未匹配到任何战斗脚本" in text and _HEAL_ADDED:
        # 2026-11-13：「未匹配到任何战斗脚本」= 站桩挨打的根因
        # （AutoFight 找不到脚本，一次按键都不发）。这次已经补好脚本，
        # 立刻再跑一趟才可能真的打起来，否则这轮树脂还是白花。
        log.info("[BetterGI] 这次缺的战斗脚本已补好，重新跑一趟")
        return True
    if COMPLETE_MARK in text:
        return False
    for p in ("任务被取消", "A task was canceled", "游戏已退出", "请先启动BetterGI"):
        if p in text:
            return True
    return ("任务启动" not in text) and ("开始执行" not in text)



def _script_avatar_names(path: Path) -> set:
    """一份战斗脚本里出现过的角色名（每行第一个空格前的内容，跳过注释）。"""
    names = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("//") or s.startswith("#"):
                continue
            head = re.split(r"[ (]", s, maxsplit=1)[0].strip()
            if head:
                names.add(head)
    except Exception:
        pass
    return names


def _known_script_names() -> set:
    """User/AutoFight 下【别人写的】脚本认识哪些角色（不含我们自己的补全文件）。"""
    names = set()
    if AUTOFIGHT_DIR.is_dir():
        for p in AUTOFIGHT_DIR.rglob("*.txt"):
            try:
                if p.resolve() == FALLBACK_SCRIPT.resolve():
                    continue
            except Exception:
                pass
            names |= _script_avatar_names(p)
    return names


def _team_names_from_log(text: str) -> list:
    """日志里引擎自己报的「识别到的队伍角色」，按出现顺序去重。"""
    out = []
    for m in _TEAM_RE.finditer(text or ""):
        for n in re.split(r"[,，]", m.group(1)):
            n = n.strip()
            if n and n not in out:
                out.append(n)
    return out


def _append_fallback(names: list) -> list:
    """把不认识的角色按通用连招补一行进我们自己的补全脚本，返回真正补进去的名字。"""
    if not names:
        return []
    try:
        AUTOFIGHT_DIR.mkdir(parents=True, exist_ok=True)
        existed = FALLBACK_SCRIPT.exists()
        known = _script_avatar_names(FALLBACK_SCRIPT) if existed else set()
        todo = [n for n in names if n and n not in known]
        if not todo:
            return []
        with open(FALLBACK_SCRIPT, "a", encoding="utf-8") as fp:
            if not existed:
                fp.write(FALLBACK_HEADER)
            for n in todo:
                fp.write("%s %s\n" % (n, GENERIC_COMBAT))
        return todo
    except Exception as e:
        log.warning("[BetterGI] 写战斗脚本补全文件失败: %s", e)
        return []


def _heal_combat_script(text: str = "") -> None:
    """日志里出现了「脚本不认识的角色」就自动补全 —— 下次一条龙就能匹配上。

    只在真有人不认识时才写文件；用户/群友那份脚本一个字都不动。"""
    text = text or _new_log_text()
    if not text:
        return
    teams = _team_names_from_log(text)
    if not teams:
        return
    known = _known_script_names()
    missing = [n for n in teams if n not in known]
    if not missing:
        return
    added = _append_fallback(missing)
    if added:
        global _HEAL_ADDED
        _HEAL_ADDED = list(added)
        log.warning("[BetterGI] 战斗脚本不认识这些角色 → 已把通用连招补进 %s: %s"
                    "（打完这一趟就能一直匹配；「站在那里挨打」就是缺这个）",
                    FALLBACK_SCRIPT.name, "/".join(added))


class BetterGIAdapter:
    """原神适配器：多个目标按顺序各自跑一条龙（共享常驻配置 daily.json，逐目标改任务）。"""

    def __init__(self, cfg, targets):
        self.cfg = cfg
        # switch_only 的条目（幽境危战 / 地脉花 / 首领讨伐）只是"开哪个任务"的开关，
        # 不是秘境：不能拿它们去起一条龙（否则会多跑几趟、还把 DomainName 写成"地脉花"）。
        self.targets = [t for t in targets if t.get("enabled", True) and not t.get("switch_only")]
        if not self.targets:
            log.warning("[BetterGI] 配置里没有可跑的秘境 target（只剩 switch_only 条目）；"
                        "一条龙至少要有一个秘境才能触发整轮任务")
        self.batch = "daily_" + time.strftime("%Y%m%d_%H%M%S")
        self.proc = None
        self.finished = False
        self.failed = False
        self._guard = None
        self._login_stop = None   # 登录兜底线程的停止信号（见 start()）
        self._last_elapsed = 0.0   # 上一趟跑了多少秒（用来识别"10 秒就收工"的早退）
        self._game_log_base = -1   # 原神自己 output_log.txt 的基线（查本地登录缓存有没有坏）
        self._run_started_at = time.time()   # 本次开跑时刻（判断游戏日志是不是这次写的）

    def _run_one_dragon(self, target: dict, timeout_s: int, idx: int, override: dict = None) -> None:
        """起一趟一条龙并等它跑完。"""
        cfg_path = make_one_dragon_config("genshin", self.cfg, target, self.batch, idx,
                                          switch_override=override)
        name = cfg_path.stem
        log.info("[BetterGI] 启动一条龙配置 %s（秘境=%s）", name, target["name"])
        t0 = time.time()
        self.proc = _launch(BETTERGI_EXE, f"startOneDragon {name}", BETTERGI_DIR)
        # 窗口兜底：整场盯着游戏窗口（只起一次，多趟复用同一个监视线程）
        if self._guard is None:
            self._guard = win_guard.watch_async("genshin")
        ok = self._wait_exit(timeout_s=timeout_s)
        self._last_elapsed = time.time() - t0
        code = self.proc.poll() if self.proc is not None else None
        if code is not None:
            log.info("[BetterGI] 引擎退出码 %s（本趟耗时 %.1f 秒）", code, self._last_elapsed)
        if not ok:
            log.error("[BetterGI] 配置 %s 超时（本次视为失败，别再报 ok=True）", name)
            self.failed = True
        elif self._last_elapsed < 120 and not _log_has_mark():
            # 2026-11-13：正常一轮 4 个任务要 8 分钟以上。两分钟内就退出、又没完成标记，
            #   只能是「启动游戏」阶段自己收工（冷启动进主界面太慢 / 上一轮游戏没退干净）。
            log.error("[BetterGI] 这一趟只跑了 %.0f 秒就退出、也没有完成标记 —— 引擎在"
                      "「启动游戏」阶段就收工了，本次按没跑完处理（随后会重试一趟）",
                      self._last_elapsed)
            self.failed = True

    def start(self):
        # 每次运行都重置「这次补全过哪些角色」，别让上一次的残留影响这次的重试判断
        global _HEAL_ADDED, _LOGIN_CACHE_BROKEN
        _HEAL_ADDED = []
        _LOGIN_CACHE_BROKEN = False
        kill_bettergi_if_running()   # 保证单实例（startOneDragon 参数走激活流程）
        if not kill_game_if_running(self.cfg.get("client_path", "")):
            log.warning("[BetterGI] 游戏进程还开着，而且是刚启动的（拒绝强杀）；"
                        "BetterGI 会接管这个已在运行的游戏，通常也能正常进世界")
                                     # 先关游戏：让它自己从登录界面进游戏，
                                     # 否则用户把游戏停在某个界面时 BetterGI 会一直等（实测 10/3-10/5 空等一小时）
        # ※ 2026-11-17 已【删除】"预登录"（自己把游戏拉起来登录、再关掉）：
        #   它会先让游戏启动十几秒、然后 WM_CLOSE，紧接着上游又启动一次 —— 实测这正是
        #   "记住的账号被清掉"的元凶（崩铁 12:44 的登录数据还是好的，13:00 就变成空值、
        #   弹手机验证码页）。登录兜底改由下面的后台 watch 线程做：游戏已经开着时填表。
        _log_baseline()              # 记日志基线：只看本次新增的内容
        self._run_started_at = time.time()
        self._game_log_base = _game_log_size()   # 原神自己日志的基线（查本地快速登录缓存）
        if not self.targets:
            self.finished = True
            return
        t = self.targets[0]                      # 秘境 target（switch_only 的条目已在 __init__ 过滤掉）
        timeout_s = int(t.get("timeout_minutes", 60) * 60)

        # 一趟跑完就好：一条龙里"幽境危战"排在 地脉花/秘境 之前（BetterGI 自带 TaskOrder），
        # 危战开着时它先吃树脂；没开时 BetterGI 自己跳过，接着按当天规则打地脉花/秘境。
        # ※ 曾为了"树脂全给危战"拆成两趟（第二趟重开游戏），10/10 实测第二趟进至冬秘境按 F 之后
        #   BetterGI 直接没了、树脂一点没花 —— 换新游戏会话风险太大，回退单趟。
        # 【登录兜底】BetterGI 自己没有登录能力：游戏停在登录界面时它只会干等，
        #   等不到就自己杀游戏重开（2026-11-09 就是这样白跑一趟）。所以起一个后台线程
        #   盯着游戏窗口，一旦认出登录界面就用【账号密码登录】把账号密码填进去
        #   （看到「手机验证码」立即停手，一次运行最多提交一次，见 login_helper.py）。
        self._login_stop = threading.Event()
        if login_helper is not None and self.cfg.get("auto_login", True):
            try:
                # 间隔 3 秒（2026-11-16）：BetterGI 从"游戏到前台"到自己放弃只有几十秒，
                # 10 秒一轮经常一整轮都没看到登录界面，于是它把游戏杀掉重开。
                login_helper.watch("YuanShen.exe", "genshin", stop_event=self._login_stop,
                                   timeout_s=timeout_s + 600, interval_s=3)
            except Exception as e:   # noqa: BLE001
                log.warning("[BetterGI] 登录兜底线程没起来（不影响主流程）: %s", e)
        self._run_one_dragon(t, timeout_s, 0, None)
        # 【重试一次】第一趟没跑完（没有完成标记）通常发生在"开机后第一次启动游戏特别慢"
        #   或者引擎自己把游戏杀掉重开的时候。2026-11-09 就是：07:00 开机、07:10 就跑，
        #   第一次启动原神花了 6 分钟才到登录页 → BetterGI 等不到主界面、主动杀游戏 ->
        #   一条龙被取消、树脂 0 消耗。第二趟游戏已经在系统缓存里"热"了（当天实测 40 秒进世界）。
        #   只重试一次，避免无限循环。
        # 早退（< 3 分钟就自己收工）也算"值得重试"：2026-11-13 那两趟分别只活了 10 秒和 1.4 秒，
        #   日志里一个失败特征都没留下，_should_retry() 看不出来，于是只跑一趟就放弃了。
        if self.failed and not _LOGIN_CACHE_BROKEN and (_should_retry() or self._last_elapsed < 180):
            log.warning("[BetterGI] 第一趟没有跑完（耗时 %.0f 秒），准备重试一次"
                        "（先杀干净引擎和游戏，等它彻底退出，重置日志基线）", self._last_elapsed)
            kill_bettergi_if_running()
            game_exe = Path(self.cfg.get("client_path", "") or "YuanShen.exe").name
            closed = kill_game_if_running(self.cfg.get("client_path", ""))
            # 2026-11-14 改：原来只等 15 秒就重开游戏（两次启动只隔 24 秒）。2026-11-13 那晚
            # 就是这样把原神的本地快速登录缓存弄坏的（游戏要求重新登录）。现在必须：
            # 游戏真的退了 + 再多等 45 秒让它把本地缓存/设置写完，才允许跑第二趟。
            if closed:
                closed = game_proc.wait_gone(game_exe, 90)
            if not closed:
                log.error("[BetterGI] 游戏进程没退干净 → 放弃第二趟（不再连环快开快关游戏，"
                          "那正是写坏原神登录缓存的原因）")
            else:
                time.sleep(45)
                _log_baseline()
                self._game_log_base = _game_log_size()
                self.failed = False
                self._run_one_dragon(t, timeout_s, 1, None)
        if self._login_stop is not None:
            self._login_stop.set()
        # 【不删除】daily.json 常驻，用户可在 BetterGI UI 中直接编辑
        self.finished = True

    def wait(self, timeout_s: int) -> bool:
        """auto_daily 契约接口：等待引擎完成。
        注意：start() 内部已按 target 顺序等待完毕（self.finished），此处不得再等一次，
        否则会第二次看到"进程早已退出"而误报启动失败。"""
        if self.finished:
            return not self.failed      # 超时过就报失败（以前一律 True，把空跑一小时报成成功）
        return self._wait_exit(timeout_s)

    def stop(self):
        """auto_daily 契约接口：清理。"""
        if self._guard is not None:
            self._guard.set()
        if self._login_stop is not None:
            self._login_stop.set()
        kill_bettergi_if_running()

    def _finish_check(self) -> None:
        """引擎退出后的收尾判定：日志里有失败特征就把本次判为失败（不再是 ok=True）。

        2026-11-09 补：光看"失败特征"会漏判 —— 当天一条龙被取消、树脂 0 消耗，
        日志里一条旧特征都没有，于是被报成 ok=True。反过来验：整轮跑完必然会打
        完成标记『一条龙和配置组任务结束』，没有它 = 这轮根本没跑完。"""
        global _LOGIN_CACHE_BROKEN
        if _report_log_failures():
            self.failed = True
        # 顺手补全战斗脚本：日志里出现「脚本不认识的角色」时把通用连招写进去，
        # 下一次一条龙就能匹配上（「站在那里挨打」的根治点，见文件顶部说明）。
        try:
            _heal_combat_script()
        except Exception as e:
            log.warning("[BetterGI] 战斗脚本自动补全出错: %s", e)
        if not _log_has_mark():
            log.error("[BetterGI] 本次日志里没有完成标记『%s』—— 整轮任务没有跑完"
                      "（多半是游戏/引擎中途退出或被取消）", COMPLETE_MARK)
            self.failed = True
        # 原神自己的日志：本地「快速登录」账号列表解析失败 → 这一趟必然停在登录页，
        # 重开游戏也没用，只能让用户手动登录一次（2026-11-13 那次事故的症状）。
        try:
            # 只在「这趟真的启动过游戏」时才看：Unity 每次启动会重写 output_log.txt，
            # 游戏没起来时文件里留的还是上一趟的内容，直接读会把旧账算到这次头上。
            try:
                fresh = GENSHIN_GAME_LOG.stat().st_mtime >= self._run_started_at - 5
            except OSError:
                fresh = False
            game_new = _game_log_new(self._game_log_base) if fresh else ""
            if any(m in game_new for m in LOGIN_FAIL_MARKS):
                _LOGIN_CACHE_BROKEN = True
                self.failed = True
                log.error("[BetterGI] 原神本地快速登录数据读取失败（游戏日志里有 failed to parse "
                          "account list / Decode exception）—— 这一趟停在登录页，判定失败且不重试。"
                          "请【手动打开一次原神并登录】（勾选记住我），之后自动化才能继续")
        except Exception as e:
            log.warning("[BetterGI] 检查原神登录缓存失败: %s", e)

    def _wait_exit(self, timeout_s: int) -> bool:
        """等待引擎完成。修复：runas 是异步的，若进程还未出现就判'完成'会误杀刚拉起的引擎。
        逻辑：启动宽限期内等待进程出现(seen=True)；只有 seen=True 后进程消失(或出现完成标记)才算完成。"""
        def _running() -> bool:
            r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq BetterGI.exe"],
                               capture_output=True, text=True)
            return "BetterGI.exe" in r.stdout

        end = time.time() + timeout_s
        start = time.time()
        seen = False
        last_report = 0.0
        # 卡死看门狗：引擎进程还在，但日志 10 分钟没有新字节 = 已经卡死（正常跑时日志几乎每秒都在写）。
        # 11-09 崩铁就是这种形态：引擎不退出、活活挂了 27 分钟，把后面的绝区零挤掉。
        stall_s = float(self.cfg.get("stall_minutes", 10)) * 60
        last_size = _log_size()
        last_progress = time.time()
        while time.time() < end:
            running = _running()
            if running:
                seen = True
            elif seen:
                self._finish_check()              # 出现过又消失 = 完成（顺手检查内部有没有失败）
                return True
            elif time.time() - start > 60:
                log.warning("[BetterGI] 60 秒内未见引擎进程，判定启动失败")
                return False
            if seen and _log_has_mark():
                for _ in range(30):
                    time.sleep(2)
                    if not _running():
                        self._finish_check()
                        return True
                self._finish_check()
                return True
            now = time.time()
            size = _log_size()
            if size != last_size:
                last_size = size
                last_progress = now
            elif seen and now - last_progress > stall_s:
                log.error("[BetterGI] 引擎进程还在，但日志已经 %.0f 分钟没有增长 —— 判定卡死，"
                          "杀掉引擎结束本次（不再白等超时）", (now - last_progress) / 60)
                self.failed = True
                kill_bettergi_if_running()
                return False
            if now - last_report > 30:
                last_report = now
                log.info("[BetterGI] 等待引擎完成中… seen=%s", seen)
            time.sleep(3)
        return False
