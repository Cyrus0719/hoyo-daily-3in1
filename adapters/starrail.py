# -*- coding: utf-8 -*-
# March7thAssistant（三月七小助手，崩铁）引擎适配器
# 原理：
#   1) 写 assets/config/config.yaml：清体力 power_plan、每日实训、奖励领取、游戏路径、自动分辨率
#   2) 启动 "March7th Assistant.exe main -e"（完整运行，成功后退出程序）
#   3) 轮询进程退出判定完成
import ctypes
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

BASE = Path(__file__).resolve().parent.parent          # 项目根目录
sys.path.insert(0, str(BASE))                          # 能 import 到项目根的模块
import win_guard   # noqa: E402  游戏窗口兜底（16:9 检查/纠正）
import game_proc   # noqa: E402  温和关闭游戏进程（先礼后兵，见 game_proc.py 顶部说明）
try:
    import login_helper   # noqa: E402  掉登录时自动用账号密码登录（绝不用验证码）
except Exception as _login_err:   # noqa: BLE001  依赖缺失不该拖垮整个适配器
    login_helper = None
    logging.getLogger(__name__).warning("[login] 登录兜底不可用: %s", _login_err)
# 部署后路径（下载解压 March7thAssistant_full.zip 到此）；可用 HOYO_MARCH7TH_DIR 覆盖
M7A_DIR = Path(os.environ.get("HOYO_MARCH7TH_DIR") or (BASE / "tools" / "March7thAssistant"))
CONFIG_FILE = M7A_DIR / "config.yaml"   # 运行时配置在包根目录（首次运行自动从 example 生成）
EXE = M7A_DIR / "March7th Assistant.exe"

# 副本类型 -> 默认实例名（游戏内准确名称，可与配置的 mission_name 覆盖）
DEFAULT_INSTANCE_NAMES = {
    "拟造花萼（金）": "回忆之蕾",
    "拟造花萼（赤）": "收容舱段",
    "凝滞虚影": "无",
    "侵蚀隧洞": "睿治之径",
    "饰品提取": "永恒笑剧",
    "历战余响": "毁灭的开端",
}

# 进程退出码只说明"程序退出了"，不说明"事情干完了"（2026-10-18 报告记下的已知缺口）。
# 2026-10-19 第一次真的撞上：开拓力 242→34 全被【历战余响 ×3（约 90）】+【优先合成沉浸器 ×3
#   （每个 40，共约 120）】吃掉，配置里 5 次「侵蚀隧洞-观火之径」到体力计划时只剩 34
#   （"开拓力 < 40 → 无法执行…保留该计划"，实跑 0 次），每日实训停在 400/500、奖励没领；
#   引擎照样 exit 0，daily.log 写 ok=True —— 和原神 9/19 那种"假成功"一个味道。
# 这里只做"让它显形"：扫今天的三月七日志，命中就打 WARNING/ERROR，不改退出判定
#   （燃料被"历战余响/沉浸器"先吃掉属于资源分配，不算程序坏了）。
M7A_SOFT_PATTERNS = ("保留该计划", "每日实训未完成", "合成材料失败", "战斗失败")

# 2026-11-09 事故：崩铁账号登录态过期 —— 三月七 07:18:43 报「尝试启动游戏时发生错误：账号登录过期」，
#   重试两轮后 07:19:26 彻底放弃，接着每秒一条「截图失败：没有找到游戏窗口」刷到 07:20:25，
#   然后【进程一直不退出】活到 07:47:36（29 分 17 秒），把绝区零的档期整个挤掉。
#   所以这里要两件事：① 认得出这类"必死"错误，立刻杀进程并判失败；② 日志停长 = 卡死也杀。
M7A_FATAL_PATTERNS = ("账号登录过期", "登录过期")
M7A_FATAL_HINT = "需要你【手动打开一次崩铁并登录】（登录后勾选记住我），之后自动化才能跑"


def _log_files():
    try:
        return sorted((M7A_DIR / "logs").glob("*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []


def _log_baseline() -> dict:
    """记下"本次启动时"最新日志的名字与大小，后面只看新增的部分（昨天/上一次的报错不能算今天）。"""
    files = _log_files()
    if not files:
        return {"name": "", "size": 0}
    try:
        return {"name": files[0].name, "size": files[0].stat().st_size}
    except Exception:
        return {"name": "", "size": 0}


def _log_size() -> int:
    files = _log_files()
    if not files:
        return 0
    try:
        return files[0].stat().st_size
    except Exception:
        return 0


def _log_text_after(base: dict) -> str:
    """取最新日志里"基线之后"的新增文本（跨文件就整份读）。"""
    files = _log_files()
    if not files:
        return ""
    f = files[0]
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if base and base.get("name") == f.name:
        return text[int(base.get("size") or 0):]
    return text


def _fatal_hit(text: str) -> str:
    """本次新增日志里有没有"必死"特征（有就立刻收工，别干等超时）。"""
    for pat in M7A_FATAL_PATTERNS:
        if pat in text:
            return pat
    # 找不到游戏窗口 = 只会无限截图失败，短时间内反复出现就是死局（今天刷了 58 条）
    if text.count("没有找到游戏窗口") >= 5:
        return "连续找不到游戏窗口"
    return ""


def _scan_today_log() -> None:
    """把"本次没干完"的痕迹写进 daily.log：开拓力起止 + 未完成/跳过特征。"""
    try:
        files = sorted((M7A_DIR / "logs").glob("*.log"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return
    if not files:
        return
    f = files[0]
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    nums = re.findall(r"开拓力[:：]\s*(\d+)/300", text)
    if nums:
        log.info("[March7th] 开拓力: %s → %s/300（日志 %s，%d 处读数）",
                 nums[0], nums[-1], f.name, len(nums))
    hits = {p: text.count(p) for p in M7A_SOFT_PATTERNS if p in text}
    if not hits:
        log.info("[March7th] 日志检查通过：无未完成/跳过特征")
        return
    log.warning("[March7th] 日志有未完成/跳过特征（可能少刷了）: %s —— 日志 %s", hits, f.name)
    if "每日实训未完成" in hits:
        log.error("[March7th] 每日实训没满 500 分，今天的实训奖励领不到（看日志『今日实训』明细）")


def write_config(cfg: dict, targets: list, game_path: str) -> None:
    """写 March7th 配置（关键项），不动其他用户设置。"""
    import yaml
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
            data = {k: v for k, v in data.items() if k is not None}
        except Exception:
            data = {}

    # 游戏路径（用户 F 盘桌面客户端）
    data["game_path"] = game_path
    data["game_process_name"] = "StarRail"
    data["game_title_name"] = "崩坏：星穹铁道"
    data["auto_set_game_path_enable"] = True
    data["auto_set_resolution_enable"] = True   # 启动时自动切 1920x1080 + 关 HDR

    # 清体力（用户自由入口 -> power_plan [[类型, 名称, 次数]]）
    plan = []
    for t in targets:
        typ = t["name"]
        name = t.get("mission_name") or DEFAULT_INSTANCE_NAMES.get(typ, "无")
        runs = int(t.get("runs", 0))  # 0 = 自动按开拓力计算直至清空
        plan.append([typ, name, runs])
    data["power_enable"] = True
    data["power_plan"] = plan
    data["power_plan_keep"] = False
    if plan:
        data["instance_type"] = plan[0][0]
        names = data.setdefault("instance_names", {})
        names[plan[0][0]] = plan[0][1]
    data["use_fuel"] = True          # 用燃料清体力（用户要求"清燃料"）
    data["echo_of_war_enable"] = True

    # 每日实训 + 奖励
    data["daily_enable"] = True
    data["daily_material_enable"] = True
    data["reward_enable"] = True
    data["reward_dispatch_enable"] = True   # 委托奖励
    data["reward_mail_enable"] = True
    data["reward_quest_enable"] = True      # 每日实训奖励
    data["reward_srpass_enable"] = True     # 无名勋礼奖励
    data["activity_dailycheckin_enable"] = True

    # 完成后动作：Exit=任务完成后退出程序（配合总控轮询进程退出）
    data["after_finish"] = "Exit"
    # 防回写崩溃：scheduled_time 必须为字符串（"4:00"），否则 timepickersettingcard 启动即崩
    if not isinstance(data.get("scheduled_time"), str):
        data["scheduled_time"] = "4:00"
    # 首次运行检查：CLI 要求先打开 GUI 同意免责声明（写入 auto_update）；由我们代为写入
    data["auto_update"] = True
    data["check_update"] = False
    data["pause_after_success"] = False

    CONFIG_FILE.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")


def kill_game_if_running(game_path: str = "") -> bool:
    """关掉已经在跑的崩铁客户端并等它彻底退出（True = 已经不在运行）。

    三月七自己的 auto_set_resolution 只对"它自己启动的游戏"有效；对用户手动开着、
    已经全屏的实例，它只会反复提示"请在游戏设置内手动切换为 1920x1080 窗口"，
    最后一怒之下 terminate + 重启游戏（2026-11-13 现场）。先关掉，让它从零启动。

    2026-11-14 改：统一走 game_proc.close —— 先 WM_CLOSE 让游戏自己退（它要回写本地
    账号/设置数据），只有存活 >= 180 秒的进程才允许强杀。刚启动的游戏宁可不关。"""
    exe = Path(game_path).name if game_path else "StarRail.exe"
    try:
        if not game_proc.running(exe):
            return True
        ok = game_proc.close(exe, grace_s=45, force_after_s=180)
        if ok:
            log.info("[March7th] 已在跑的 %s 已关闭（让它自己以 1920x1080 窗口启动）", exe)
        else:
            log.warning("[March7th] %s 还开着且刚启动（拒绝强杀），可能影响分辨率设置", exe)
        return ok
    except Exception as e:
        log.warning("[March7th] 关闭游戏失败: %s", e)
        return False


class StarRailAdapter:
    """崩铁适配器（三月七）。"""

    def __init__(self, cfg, targets):
        self.cfg = cfg
        self.targets = [t for t in targets if t.get("enabled", True)]
        self.proc = None
        self._guard = None
        self._login_stop = None   # 登录兜底线程的停止信号（见 start()）
        self._base = {"name": "", "size": 0}

    def _is_admin(self) -> bool:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def start(self):
        if not EXE.exists():
            raise FileNotFoundError(f"未找到三月七主程序: {EXE}（请先下载 March7thAssistant_full.zip 并解压）")
        write_config(self.cfg, self.targets, self.cfg.get("client_path", ""))
        self._base = _log_baseline()   # 只看本次新增的日志（昨天的报错不能算今天）
        # 先关掉已经在跑的崩铁再交给三月七启动（同原神适配器的做法）。
        # 2026-11-13 事故：跑的时候用户正开着全屏 2560x1600 的崩铁 —— 三月七连试 5 次
        #   「请在游戏设置内手动切换为 1920x1080 窗口」都没成功（win_guard 的 SetWindowPos
        #   对已运行的全屏游戏同样拉不动）→「游戏分辨率不正确」→ 它自己 terminate+重启 →
        #   12:49:46 起「截图失败：没有找到游戏窗口」×10 → 我们判必死杀进程，整轮 ok=False。
        kill_game_if_running(self.cfg.get("client_path", ""))
        # ※ 2026-11-17 已【删除】"预登录"（自己把游戏开起来、登录、再关掉）：
        #   11-17 12:59:40 它把 StarRail.exe 拉起来，13 秒后 WM_CLOSE，紧接着三月七又启动
        #   一次 —— 13:00 游戏 SDK 直接判"没有记住的账号"，HKCU 里 MIHOYOSDK_ADL_0 从
        #   1304 字节掉成 24 字节空值（logs/adl_state.log 有前后指纹）。
        #   即：启动头一分钟里被关掉会把登录数据写坏。现在一道预登录都不做，
        #   兜底只交给下面那个后台 watch 线程（游戏已经开着时填表，绝不关它）。
        log.info("[March7th] 启动完整运行 main ...")
        # 提权感知启动：定时任务(/RL HIGHEST)已是管理员 -> 直接启动【无 UAC】；
        # 手动运行时非提权 -> runas（弹一次 UAC）。程序自带 pyuac，双保险一致。
        if self._is_admin():
            # CREATE_NO_WINDOW：别弹黑窗口（GUI 程序本来也不该有控制台，
            # 但 2026-11-09 的绝区零就是被"冒出来的控制台被关掉"以 0xC000013A 打死的，统一处理）
            subprocess.Popen([str(EXE), "main"], cwd=str(M7A_DIR),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            log.info("[March7th] 管理员上下文中直接启动（无 UAC）")
        else:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", str(EXE), "main", str(M7A_DIR), 1)
            log.info("[March7th] 非提权上下文 runas 启动（UAC 一次）")
        # 【登录兜底】三月七自己没有账号密码登录能力：一遇到「账号登录过期」就原地卡死
        #   （2026-11-09 白挂 29 分钟，把绝区零挤掉）。这里起后台线程盯游戏窗口，
        #   认出登录界面就用账号密码登录一次（绝不用手机验证码）。
        self._login_stop = threading.Event()
        if login_helper is not None and self.cfg.get("auto_login", True):
            try:
                login_helper.watch("StarRail.exe", "starrail", stop_event=self._login_stop,
                                   timeout_s=3600, interval_s=3)
            except Exception as e:   # noqa: BLE001
                log.warning("[March7th] 登录兜底线程没起来（不影响主流程）: %s", e)
        # 窗口兜底：整场盯着游戏窗口，任何时候不是 16:9 就拉回 1920x1080
        self._guard = win_guard.watch_async("starrail")

    def _running(self) -> bool:
        r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq March7th Assistant.exe"],
                           capture_output=True, text=True)
        return "March7th Assistant.exe" in r.stdout

    def wait(self, timeout_s: int = 3600):
        """等三月七跑完：进程退出=完成；但"必死错误"和"日志停长"要立刻收工。

        2026-11-09 之前这里只会死等进程退出，于是登录过期的那次白挂了 29 分钟。"""
        end = time.time() + timeout_s
        t_begin = time.time()
        stall_s = float(self.cfg.get("stall_minutes", 15)) * 60
        last_size = _log_size()
        last_progress = time.time()
        while time.time() < end:
            if not self._running():
                _scan_today_log()   # 进程退出 ≠ 干完了：把"没干完"的痕迹写进 daily.log
                return True   # 进程退出 = 完成（after_finish=Exit）
            hit = _fatal_hit(_log_text_after(self._base))
            if hit:
                log.error("[March7th] 引擎报致命错误『%s』—— 判定失败并立即结束进程"
                          "（不再干等超时，免得把后面的游戏挤掉）", hit)
                if "登录过期" in hit:
                    log.error("[March7th] %s", M7A_FATAL_HINT)
                _scan_today_log()
                self.stop()
                return False
            size = _log_size()
            if size != last_size:
                last_size = size
                last_progress = time.time()
            elif time.time() - last_progress > stall_s:
                log.error("[March7th] 日志已 %.0f 分钟没有增长，引擎卡死 —— 结束它并判失败",
                          (time.time() - last_progress) / 60)
                _scan_today_log()
                self.stop()
                return False
            # 前 5 分钟 3 秒看一次：三月七从"游戏切前台"到判「账号登录过期」只有 16 秒左右，
            # 10 秒一轮经常等它已经重启过一轮才发现（2026-11-16 用户看到的就是"反复退出又启动"）。
            time.sleep(3 if (time.time() - t_begin) < 300 else 10)
        log.error("[March7th] 等待超时（%d 分钟），判定失败", timeout_s // 60)
        return False

    def stop(self):
        if self._guard is not None:
            self._guard.set()
        if self._login_stop is not None:
            self._login_stop.set()
        _run_hidden(["taskkill", "/IM", "March7th Assistant.exe", "/F"], capture_output=True)
        _run_hidden(["taskkill", "/IM", "March7thAssistant.exe", "/F"], capture_output=True)
