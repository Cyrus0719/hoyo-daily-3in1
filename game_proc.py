# -*- coding: utf-8 -*-
"""游戏进程的「温和关闭」（2026-11-14 新增）

背景（真实事故）：
  2026-11-13 12:46-12:47，我们在 30 秒内两次拉起原神、又两次结束它：
  第一次是 BetterGI 自己 `Call QuitApplication`（游戏才启动 11 秒），
  第二次是 auto_daily.kill_game() 的 `taskkill /IM YuanShen.exe /F`
  （游戏才启动 1 秒就被硬杀）。
  当晚用户登录时原神要求重新登录，游戏自己的日志里是
  `failed to parse account list` ×20 + `Decode exception has occurred.`
  = 本地「快速登录账号列表」解析失败（缓存被写坏）。

所以这里定规矩：
  1) 先礼后兵：`taskkill /IM <exe>`（不带 /F = 给窗口发 WM_CLOSE，游戏走正常退出流程，
     有时间把自己本地的设置/缓存/账号数据写完）；
  2) 优雅期 grace_s 秒内自己退出 → 成功；
  3) 还活着：只有进程已存活 >= force_after_s 秒（默认 180）才允许 /F；
     刚启动的进程【绝不强杀】，直接返回 False，由上层按「游戏还开着」处理。
     取不到进程年龄（权限/ctypes 异常）也按「年轻」处理 —— 宁可这趟不跑，
     也不要再写坏一次账号缓存。
"""
import ctypes
import logging
import subprocess
import time
from ctypes import wintypes

log = logging.getLogger("auto_daily")

_CREATE_NO_WINDOW = 0x08000000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_EPOCH_DIFF = 11644473600.0        # 1601-01-01 → 1970-01-01 的秒数


def _run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=_CREATE_NO_WINDOW)
    except Exception:
        return None


def pids(exe: str) -> list:
    """exe 对应的所有进程 PID（tasklist CSV 输出解析，避免中文系统编码问题）。"""
    if not exe:
        return []
    r = _run(["tasklist", "/FI", "IMAGENAME eq " + exe, "/FO", "CSV", "/NH"])
    if r is None or not r.stdout:
        return []
    out = r.stdout.decode("mbcs", "replace")
    want = exe.lower()
    found = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.strip().split('","')]
        if len(parts) >= 2 and parts[0].lower() == want:
            try:
                found.append(int(parts[1]))
            except ValueError:
                pass
    return found


def running(exe: str) -> bool:
    return bool(pids(exe))


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _k32():
    """kernel32 的 GetProcessTimes（只在真要取年龄时才建）。"""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.GetProcessTimes.restype = wintypes.BOOL
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(_FILETIME)] * 4
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def age_s(pid: int):
    """进程已存活多少秒；取不到返回 None（调用方按「年轻」保守处理）。"""
    try:
        k = _k32()
        h = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            c, e, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            if not k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                     ctypes.byref(kt), ctypes.byref(ut)):
                return None
            created = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - _EPOCH_DIFF
        finally:
            k.CloseHandle(h)
        age = time.time() - created
        return age if 0 <= age < 86400 * 365 else None
    except Exception:
        return None


def ages(exe: str) -> list:
    return [age_s(p) for p in pids(exe)]


def wait_gone(exe: str, timeout_s: int = 90) -> bool:
    """等进程彻底消失（不杀）。返回 True = 已经没了。"""
    end = time.time() + max(0, timeout_s)
    while time.time() < end:
        if not running(exe):
            return True
        time.sleep(1)
    return not running(exe)


def close(exe: str, grace_s: int = 45, force_after_s: int = 180) -> bool:
    """温和关闭游戏进程。True = 进程已经不在（或本来就没开）。

    详细规则见模块文档：先 WM_CLOSE 优雅退出；只有「存活 >= force_after_s 秒」
    的进程才允许 /F，刚启动的进程一律不强杀。"""
    if not exe:
        return True
    if not running(exe):
        return True
    t0 = time.time()
    young = [a for a in ages(exe) if a is not None]
    log.info("[proc] %s 正在运行（已存活 %s 秒），先发 WM_CLOSE 让它自己退",
             exe, ("%.0f" % min(young)) if young else "未知")
    _run(["taskkill", "/IM", exe])                      # 不带 /F = WM_CLOSE
    if wait_gone(exe, grace_s):
        log.info("[proc] %s 已优雅退出（%.1f 秒）", exe, time.time() - t0)
        return True
    now_ages = [a for a in ages(exe) if a is not None]
    if not now_ages or min(now_ages) < force_after_s:
        log.warning("[proc] %s 没在 %s 秒内优雅退出，但它才启动 %s 秒（< %s）——"
                    "拒绝强杀：强杀刚启动的游戏有写坏本地缓存/登录态的风险"
                    "（2026-11-13 原神要求重新登录就是这个原因）。本次按「游戏还开着」处理。",
                    exe, grace_s,
                    ("%.0f" % min(now_ages)) if now_ages else "未知（取不到）",
                    force_after_s)
        return False
    log.warning("[proc] %s 已存活 %.0f 秒仍未退出 → 强制结束", exe, min(now_ages))
    _run(["taskkill", "/IM", exe, "/F"])
    ok = wait_gone(exe, 30)
    if ok:
        log.info("[proc] %s 已强制结束（%.1f 秒）", exe, time.time() - t0)
    else:
        log.error("[proc] %s 强制结束后仍在运行，请手动检查", exe)
    return ok
