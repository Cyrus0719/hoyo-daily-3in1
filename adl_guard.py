# -*- coding: utf-8 -*-
r"""登录态（MIHOYOSDK_ADL*）守护 —— 2026-11-23 新增。

为什么需要它
------------
HKCU\Software\miHoYo\<游戏> 下有一组 MIHOYOSDK_ADL* 值，里面存的是
"记住的账号"列表（REG_BINARY，内容其实是 ASCII base64 的密文）。
游戏日志里的 failed to parse account list 就是在解析它。

2026-11-23 09:10 实测：
  * 09:10:52~54 游戏刷了 64 条 failed to parse account list + 49 条
    Decode exception（11-22 那次成功启动是 0 条）；
  * SDK 因此直接走 AccountPlatAccountLoginJobber（账号密码页），
    连 LoginByToken 都没试；
  * 09:10:58 游戏自己把 MIHOYOSDK_ADL_0 写成了 24 字节的空值哨兵
    wNQYrQRZlRRz8GFZip3P5w==；
  * 这个值从 2026-11-17 手动登录后的 1304 字符一路涨到 2200 字符
    （每次启动游戏 +96 字符，约一条记录），2200 那次就解析失败了。

所以它不是被谁删掉的，是长到游戏自己解析不了，游戏再把它清空。
我们每天自动登录一次，正好是让它长大的那个人 —— 这就是要修的地方。

本模块做什么
------------
1. 每次运行前：当前值健康就留一份快照（config/adl_snapshots）。
2. 当前值已被清空（<=100 字节）或长到危险（>=SAFE_MAX）时，
   把最近一份又新又小的快照写回去，让游戏静默登录，不弹账号密码页。
3. 任何写入之前，先把当前值原样备份到 config/adl_backups。
4. 只写 MIHOYOSDK_ADL* 这一组值，别的键一律不碰；只写不删。

CLI:
    python adl_guard.py status
    python adl_guard.py snapshot [game]
    python adl_guard.py repair [game]
    python adl_guard.py history [game]
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import winreg
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAP_DIR = BASE / "config" / "adl_snapshots"
BACKUP_DIR = BASE / "config" / "adl_backups"

GAMES = {
    "genshin": "Software\\miHoYo\\原神",
    "starrail": "Software\\miHoYo\\崩坏：星穹铁道",
    "zzz": "Software\\miHoYo\\绝区零",
}
GAME_CN = {"genshin": "原神", "starrail": "崩铁", "zzz": "绝区零"}

VALUE_PREFIX = "MIHOYOSDK_ADL"
MAIN_VALUE = "MIHOYOSDK_ADL_0"

SENTINEL_MAX = 100
MIN_GOOD = 800
SAFE_MAX = 2150         # >= 这个长度 = 已经逼近解析失败（实测 2104 能读、2200 读不了）
SNAP_TARGET_MAX = 1600  # 优先恢复到不超过这个长度的快照，留出「再长几天」的余地
KEEP_SNAPS = 30
SNAP_MAX_AGE_DAYS = 30


def _open(path: str, writable: bool = False):
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                          winreg.KEY_READ | (winreg.KEY_WRITE if writable else 0))


def read_all(game: str) -> dict:
    """读出该游戏所有 MIHOYOSDK_ADL* 值（bytes）。读不到就是空字典。"""
    path = GAMES.get(game)
    if not path:
        return {}
    out = {}
    try:
        with _open(path) as k:
            i = 0
            while True:
                try:
                    name, val, typ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if not name.startswith(VALUE_PREFIX):
                    continue
                if isinstance(val, str):
                    val = val.encode("utf-8", "replace")
                out[name] = bytes(val)
    except FileNotFoundError:
        return {}
    return out


def write_all(game: str, values: dict) -> list:
    """把 values（name -> bytes）写回注册表，一律 REG_BINARY。返回写成功的键名。"""
    path = GAMES.get(game)
    if not path:
        raise KeyError("未知游戏: %s" % game)
    done = []
    with _open(path, writable=True) as k:
        for name, val in values.items():
            if not name.startswith(VALUE_PREFIX):
                continue
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, bytes(val))
            done.append(name)
    return done


def classify(values: dict) -> str:
    """missing / small / empty / big / good"""
    main = values.get(MAIN_VALUE)
    if not values or main is None:
        return "missing"
    n = len(main)
    if n <= SENTINEL_MAX:
        return "empty"
    if n >= SAFE_MAX:
        return "big"
    if n < MIN_GOOD:
        return "small"
    return "good"


def main_size(values: dict) -> int:
    return len(values.get(MAIN_VALUE, b""))


def describe(game: str) -> dict:
    vals = read_all(game)
    kind = classify(vals)
    return {"game": game, "kind": kind, "size": main_size(vals),
            "values": {k: len(v) for k, v in vals.items()}}


def _snap_name(game: str, n: int, values: dict) -> Path:
    h = hashlib.sha1(b"".join(values[k] for k in sorted(values))).hexdigest()[:8]
    return SNAP_DIR / ("%s_%05d_%s.json" % (game, n, h))


def _snap_list(game: str) -> list:
    """[(path, n, mtime), ...] 按 n 升序"""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in SNAP_DIR.glob("%s_*.json" % game):
        try:
            n = int(p.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        try:
            out.append((p, n, p.stat().st_mtime))
        except OSError:
            continue
    out.sort(key=lambda x: x[1])
    return out


def save_snapshot(game: str, tag: str = ""):
    """当前值健康就留一份快照；已存在就跳过。"""
    vals = read_all(game)
    if classify(vals) not in ("good", "big", "small"):
        return None
    n = main_size(vals)
    if n < MIN_GOOD:
        return None
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    p = _snap_name(game, n, vals)
    if not p.exists():
        payload = {k: base64.b64encode(v).decode("ascii") for k, v in vals.items()}
        payload["_meta"] = {"game": game, "size": n,
                            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "tag": tag}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    snaps = _snap_list(game)
    if len(snaps) > KEEP_SNAPS:
        for old in sorted(snaps, key=lambda x: x[2])[: len(snaps) - KEEP_SNAPS]:
            try:
                old[0].unlink()
            except OSError:
                pass
    return p


def load_snapshot(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: base64.b64decode(v) for k, v in data.items() if not k.startswith("_")}


def best_snapshot(game: str):
    """挑一份又新又小的快照。

    优先在「长度 <= SNAP_TARGET_MAX」里取保存时间最晚的（够小，再长几天也到不了
    解析失败的长度）；不够再退到「长度 < SAFE_MAX」。
    """
    lim = time.time() - SNAP_MAX_AGE_DAYS * 86400
    pool = _snap_list(game)
    cands = [s for s in pool if MIN_GOOD <= s[1] <= SNAP_TARGET_MAX and s[2] >= lim]
    if not cands:
        cands = [s for s in pool if MIN_GOOD <= s[1] <= SNAP_TARGET_MAX]
    if not cands:
        cands = [s for s in pool if MIN_GOOD <= s[1] < SAFE_MAX and s[2] >= lim]
    if not cands:
        cands = [s for s in pool if MIN_GOOD <= s[1] < SAFE_MAX]
    if not cands:
        return None
    cands.sort(key=lambda x: x[2], reverse=True)
    path = cands[0][0]
    try:
        return path, load_snapshot(path)
    except (OSError, ValueError):
        return None


def backup_current(game: str, values=None):
    vals = read_all(game) if values is None else values
    if not vals:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = "%s_%s_%d.json" % (game, time.strftime("%Y%m%d-%H%M%S"), main_size(vals))
    p = BACKUP_DIR / name
    payload = {k: base64.b64encode(v).decode("ascii") for k, v in vals.items()}
    payload["_meta"] = {"game": game, "size": main_size(vals),
                        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": "修复前备份"}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    allb = sorted(BACKUP_DIR.glob("%s_*.json" % game), key=lambda x: x.stat().st_mtime)
    for old in allb[:-60]:
        try:
            old.unlink()
        except OSError:
            pass
    return p


def check_and_repair(game: str, dry: bool = False, log=None) -> dict:
    """运行前调用：留快照 -> 坏了/太长就修。返回一份可写进日志的说明。"""
    def _log(level, msg):
        if log is not None:
            getattr(log, level)(msg)

    vals = read_all(game)
    kind = classify(vals)
    info = {"game": game, "before": kind, "size": main_size(vals),
            "action": "none", "after": kind, "snapshot": "", "backup": ""}
    cn = GAME_CN.get(game, game)

    if kind in ("missing", "empty"):
        _log("warning", "[登录态] %s 的「记住的账号」已经被游戏清空（%d 字节），"
                        "准备用最近一份好快照恢复" % (cn, main_size(vals)))
    elif kind == "big":
        _log("warning", "[登录态] %s 的「记住的账号」已经长到 %d 字节"
                        "（实测 2200 就会解析失败），先恢复到一份更小的快照" % (cn, main_size(vals)))
    else:
        p = save_snapshot(game, "run-start")
        if p:
            info["snapshot"] = p.name
            _log("info", "[登录态] %s 正常（%d 字节），已留快照 %s" % (cn, main_size(vals), p.name))
        return info

    snap = best_snapshot(game)
    if snap is None:
        info["action"] = "no-snapshot"
        _log("warning", "[登录态] %s 没有可用的历史快照，这一趟只能靠登录兜底（账号密码）" % cn)
        return info
    path, values = snap
    if classify(values) != "good":
        info["action"] = "no-snapshot"
        _log("warning", "[登录态] 快照 %s 本身不可用（%s），跳过" % (path.name, classify(values)))
        return info
    if dry:
        info["action"] = "would-restore"
        info["snapshot"] = path.name
        return info

    bak = backup_current(game, vals)
    if bak:
        info["backup"] = bak.name
    write_all(game, values)
    after = read_all(game)
    info["action"] = "restored"
    info["after"] = classify(after)
    info["snapshot"] = path.name
    _log("warning", "[登录态] 已把 %s 的「记住的账号」恢复到快照 %s（%d -> %d 字节，"
                    "恢复前的值备份在 %s）"
         % (cn, path.name, main_size(values), main_size(after), bak.name if bak else "无"))
    return info


def _cli(argv):
    cmd = (argv[1] if len(argv) > 1 else "status").lower()
    which = argv[2] if len(argv) > 2 else ""
    games = [which] if which in GAMES else list(GAMES)
    if cmd == "status":
        for g in games:
            d = describe(g)
            print("%-9s %-8s %5d 字节  %s" % (g, d["kind"], d["size"], d["values"]))
            for path, n, mt in _snap_list(g)[-4:]:
                print("             快照 %s  %d 字节  %s"
                      % (path.name, n, time.strftime("%m-%d %H:%M", time.localtime(mt))))
    elif cmd == "snapshot":
        for g in games:
            p = save_snapshot(g, "manual")
            print("%s -> %s" % (g, p.name if p else "当前值不健康，没留"))
    elif cmd == "repair":
        import logging
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        for g in games:
            print(check_and_repair(g, log=logging.getLogger("adl")))
    elif cmd == "history":
        for g in games:
            for path, n, mt in _snap_list(g):
                print("%-9s %s %5d %s"
                      % (g, path.name, n, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt))))
    else:
        print("用法: python adl_guard.py [status|snapshot|repair|history] [game]")
        return 2
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv))
