# -*- coding: utf-8 -*-
"""登录兜底 —— 游戏掉登录时自动用【账号密码登录】（绝不走手机验证码）。

为什么需要：米哈游三款游戏的登录态都在游戏本地，缓存一坏就得重新登录；
  BetterGI / 三月七 / OneDragon 只有 OneDragon 原生支持账号密码登录，
  另外两个只能我们自己在登录界面上"看"和"点"。

做法（全部靠屏幕 OCR，不依赖任何固定坐标）：
  1) 按进程名找游戏窗口 → 截客户区
  2) 交给 ocr_helper.py（OneDragon 的 onnxocr + ppocrv6 模型）识别文字和坐标
  3) 认出是登录界面后：点「账号密码登录」→ 点账号框 → 粘贴账号 → 复核屏幕上真的出现了账号
     → 点密码框 → 粘贴密码 → 点「登录」→ 等登录界面消失
  4) 看到「手机验证码」字样立刻停手（用户明确要求只用账号密码登录）
一次运行最多提交一次账号密码，避免把账号打进风控；失败只记日志 + 存截图，绝不重试。

账号密码只存在 config/accounts.yaml（.gitignore 已排除，绝不进仓库）。
"""
import os
import sys
import json
import time
import ctypes
import logging
import subprocess
import threading
from ctypes import wintypes as wt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import win_guard  # noqa: E402

log = logging.getLogger("auto_daily")

BASE = Path(__file__).resolve().parent
ACCOUNTS_FILE = BASE / "config" / "accounts.yaml"
SHOT_DIR = BASE / "logs" / "login"
OCR_SCRIPT = BASE / "ocr_helper.py"
OCR_PY = BASE / "OneDragon-ref" / ".venv" / "Scripts" / "python.exe"

u = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# ---- 文案特征（简体中文界面） ------------------------------------------------
STRONG_HINTS = ("账号密码登录", "帐号密码登录", "手机验证码登录", "密码登录", "账号登录",
                "帐号登录", "请输入账号", "请输入帐号", "请输入密码")
WEAK_HINTS = ("登录", "账号", "帐号", "密码", "验证码")
SMS_WORDS = ("验证码", "短信", "获取验证码", "扫码")
ERR_WORDS = ("密码错误", "账号或密码", "帐号或密码", "账号不存在", "帐号不存在", "格式不正确",
             "频繁", "锁定", "失败", "错误", "过期")


# ---- 账号密码 ----------------------------------------------------------------
def load_accounts() -> dict:
    try:
        import yaml
        with open(ACCOUNTS_FILE, encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:  # noqa: BLE001
        log.warning("[login] 读取 %s 失败: %s", ACCOUNTS_FILE.name, e)
        return {}


def get_account(game: str):
    item = (load_accounts().get(game) or {})
    acc = str(item.get("account") or "").strip()
    pwd = str(item.get("password") or "").strip()
    if acc and pwd:
        return acc, pwd
    return None, None


def _mask(text: str) -> str:
    text = str(text or "")
    if len(text) <= 4:
        return "*" * len(text)
    return text[:3] + "*" * (len(text) - 5) + text[-2:]


# ---- 窗口 --------------------------------------------------------------------
def _client_rect(hwnd):
    rect = wt.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    tl = wt.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(tl))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return tl.x, tl.y, w, h


def _grab(hwnd, path: Path):
    """截客户区（先把窗口提到前台，免得截到别的窗口）。"""
    try:
        if u.GetForegroundWindow() != hwnd:
            u.SetForegroundWindow(hwnd)
            time.sleep(0.3)
    except Exception:
        pass
    rect = _client_rect(hwnd)
    if not rect:
        return None
    from PIL import ImageGrab
    x, y, w, h = rect
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    return path


def _click(x: int, y: int):
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.35)


def _paste(text: str):
    """剪贴板粘贴（比按键输入可靠，中文/特殊字符都不丢）。"""
    import pyperclip
    import pyautogui
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""
    pyperclip.copy(text)
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)
    try:
        pyperclip.copy(old)
    except Exception:
        pass


# ---- OCR ---------------------------------------------------------------------
class Ocr:
    """常驻 ocr_helper 子进程（模型只加载一次，约 1~2 秒/次）。"""

    def __init__(self):
        self.proc = None
        self._lock = threading.Lock()

    def _ensure(self) -> bool:
        if self.proc is not None and self.proc.poll() is None:
            return True
        if not OCR_PY.exists():
            log.warning("[login] 找不到 OCR 解释器: %s", OCR_PY)
            return False
        try:
            self.proc = subprocess.Popen(
                [str(OCR_PY), str(OCR_SCRIPT)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                cwd=str(BASE),
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("[login] 启动 OCR 失败: %s", e)
            self.proc = None
            return False

    def run(self, img_path) -> list:
        with self._lock:
            if not self._ensure():
                return []
            try:
                self.proc.stdin.write(json.dumps({"img": str(img_path)}) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
                data = json.loads(line) if line.strip() else {}
            except Exception as e:  # noqa: BLE001
                log.warning("[login] OCR 调用失败: %s", e)
                self.close()
                return []
            if not data.get("ok"):
                log.warning("[login] OCR 返回失败: %s", data.get("error"))
                return []
            return data.get("boxes") or []

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None


# ---- 文字匹配 ----------------------------------------------------------------
def _txt(box) -> str:
    return str(box.get("text") or "").replace(" ", "")


def _pick(boxes, include_any, exclude_any=(), min_score=0.5):
    out = []
    for b in boxes:
        if b.get("score", 0) < min_score:
            continue
        t = _txt(b)
        if not t:
            continue
        if include_any and not any(k in t for k in include_any):
            continue
        if exclude_any and any(k in t for k in exclude_any):
            continue
        out.append(b)
    return out


def _center(box):
    return (box["x1"] + box["x2"]) // 2, (box["y1"] + box["y2"]) // 2


def is_login_screen(boxes) -> bool:
    strong = _pick(boxes, STRONG_HINTS)
    if strong:
        return True
    weak = {_txt(b) for b in _pick(boxes, WEAK_HINTS)}
    return len(weak) >= 2 and any("登录" in t for t in weak)


def _find_password_tab(boxes):
    """「账号密码登录 / 密码登录 / 账号登录」这种切换入口。"""
    cands = _pick(boxes, ("账号密码登录", "帐号密码登录", "密码登录", "账号登录", "帐号登录"),
                  exclude_any=("请输入", "忘记", "验证码"))
    if not cands:
        return None
    cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


def _find_account_field(boxes):
    cands = _pick(boxes, ("请输入账号", "请输入帐号", "请输入手机", "请输入邮箱", "账号", "帐号", "手机号"),
                  exclude_any=("密码", "登录", "验证码", "忘记", "注册", "切换", "扫码", "输入密码"))
    if not cands:
        return None
    cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


def _find_password_field(boxes):
    cands = _pick(boxes, ("请输入密码", "密码"),
                  exclude_any=("登录", "忘记", "验证码", "账号", "帐号", "注册", "修改", "重置", "找回"))
    if not cands:
        return None
    cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


def _find_login_button(boxes, password_box=None):
    cands = _pick(boxes, ("登录",),
                  exclude_any=("忘记", "验证码", "账号密码", "帐号密码", "密码登录", "账号登录",
                               "帐号登录", "注册", "切换", "其他", "退出"))
    if not cands:
        return None
    # 按钮通常比标签更宽；再按离密码框近的优先
    def score(b):
        w = b["x2"] - b["x1"]
        h = max(1, b["y2"] - b["y1"])
        wide = 1 if w >= 2 * h else 0
        dist = 0
        if password_box is not None:
            _, cy = _center(b)
            _, py = _center(password_box)
            dist = abs(cy - py)
        return (-wide, dist, b["y1"])
    cands.sort(key=score)
    return cands[0]


def _has_sms_prompt(boxes) -> bool:
    return bool(_pick(boxes, SMS_WORDS, exclude_any=("账号密码登录", "密码登录")))


def _has_error(boxes) -> str:
    hits = _pick(boxes, ERR_WORDS)
    if hits:
        return _txt(hits[0])
    return ""


# ---- 主流程 ------------------------------------------------------------------
def _overlaps(a, b, pad: int = 6) -> bool:
    return not (a["y2"] + pad < b["y1"] or a["y1"] - pad > b["y2"])


def _find_typed(boxes, field_box, needle: str):
    """在指定输入框的纵向范围里找刚输入的内容。"""
    if not needle:
        return None
    needle = needle.replace(" ", "")
    for b in boxes:
        t = _txt(b)
        if needle in t and _overlaps(b, field_box):
            return b
    return None


def _digits_box(boxes, field_box, need: int = 4):
    for b in boxes:
        t = _txt(b)
        if sum(ch.isdigit() for ch in t) >= need and _overlaps(b, field_box):
            return b
    return None


def _placeholder_in(boxes, field_box, words):
    for b in boxes:
        t = _txt(b)
        if _overlaps(b, field_box) and any(w in t for w in words):
            return b
    return None


def _clear_field(ox: int, oy: int, box):
    """点进某个框、全选删除（清理落错框的内容）。"""
    import pyautogui
    cx, cy = _center(box)
    _click(ox + cx, oy + cy)
    time.sleep(0.25)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.25)


def _fill_account(hwnd, ox, oy, acc_box, account, ocr, game, tag, attempts: int = 3):
    """填账号并复核（屏幕上必须真的出现这串数字，否则不往下走）。返回 (ok, boxes)。"""
    needle = account[-6:]
    boxes = []
    for i in range(1, attempts + 1):
        cx, cy = _center(acc_box)
        _click(ox + cx, oy + cy)
        time.sleep(0.5)
        _paste(account)
        time.sleep(1.1)
        shot = SHOT_DIR / ("%s_%s_acc%d.png" % (game, tag, i))
        _grab(hwnd, shot)
        boxes = ocr.run(shot)
        hit = _find_typed(boxes, acc_box, needle) or _digits_box(boxes, acc_box, 4)
        if hit is not None:
            return True, boxes, acc_box
        # 落错框了？先清掉再重试
        stray = _pick(boxes, (needle,), min_score=0.3)
        for b in stray:
            if not _overlaps(b, acc_box):
                log.warning("[login] 账号落到别的输入框了，清掉重来")
                _clear_field(ox, oy, b)
                break
    return False, boxes, acc_box


def _fill_password(hwnd, ox, oy, pwd_box, password, ocr, game, tag, attempts: int = 3):
    """填密码：密码框的占位提示消失就算填进去了（密码是圆点，OCR 读不出来）。"""
    words = ("请输入密码", "密码")
    boxes = []
    for i in range(1, attempts + 1):
        cx, cy = _center(pwd_box)
        _click(ox + cx, oy + cy)
        time.sleep(0.4)
        _paste(password)
        time.sleep(1.0)
        shot = SHOT_DIR / ("%s_%s_pwd%d.png" % (game, tag, i))
        _grab(hwnd, shot)
        boxes = ocr.run(shot)
        if _placeholder_in(boxes, pwd_box, words) is None:
            return True, boxes
    return False, boxes


def try_login(hwnd, game: str, account: str, password: str, ocr: "Ocr",
              shot_tag: str = "", max_wait_s: int = 150):
    """在已经确认是登录界面的窗口上，走一遍账号密码登录。返回 (ok, message)。

    每一步都回读屏幕确认，任何一步对不上就停手：宁可不登录，也不乱输密码。
    """
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    tag = shot_tag or time.strftime("%Y%m%d-%H%M%S")
    rect = _client_rect(hwnd)
    if not rect:
        return False, "窗口尺寸异常"
    ox, oy = rect[0], rect[1]

    def screen(box):
        x, y = _center(box)
        return ox + x, oy + y

    shot = SHOT_DIR / ("%s_%s_0.png" % (game, tag))
    if not _grab(hwnd, shot):
        return False, "截不到窗口"
    boxes = ocr.run(shot)
    if not boxes:
        return False, "OCR 没读出文字"

    # 1) 验证码登录页 → 先切到「账号密码登录」
    pwd_field = _find_password_field(boxes)
    if pwd_field is None:
        tab = _find_password_tab(boxes)
        if tab is not None:
            log.info("[login] 点「%s」切到账号密码登录", _txt(tab))
            _click(*screen(tab))
            time.sleep(1.5)
            shot = SHOT_DIR / ("%s_%s_1.png" % (game, tag))
            _grab(hwnd, shot)
            boxes = ocr.run(shot)
            pwd_field = _find_password_field(boxes)
    if pwd_field is None:
        return False, "没找到密码输入框（画面可能不是登录界面）"

    # 2) 账号框（找不到就按密码框的相对位置推断）
    acc_field = _find_account_field(boxes)
    if acc_field is None or not _overlaps(acc_field, pwd_field):
        h = max(30, pwd_field["y2"] - pwd_field["y1"])
        acc_field = dict(pwd_field)
        acc_field["y1"] = pwd_field["y1"] - int(h * 1.7)
        acc_field["y2"] = pwd_field["y2"] - int(h * 1.7)
        log.info("[login] 没读到账号框，按密码框上方 1.7 行高处点")

    ok, boxes, acc_field = _fill_account(hwnd, ox, oy, acc_field, account, ocr, game, tag)
    if not ok:
        return False, "账号没输进去（复核失败，不输入密码）"
    log.info("[login] 账号已填入: %s", _mask(account))

    # 3) 密码框
    pwd_field = _find_password_field(boxes) or pwd_field
    ok, boxes = _fill_password(hwnd, ox, oy, pwd_field, password, ocr, game, tag)
    if not ok:
        return False, "密码没输进去（复核失败，不点登录）"

    # 4) 点登录（找不到按钮就按回车）
    btn = _find_login_button(boxes, pwd_field)
    if btn is not None:
        log.info("[login] 点「%s」提交登录（账号 %s）", _txt(btn), _mask(account))
        _click(*screen(btn))
    else:
        log.warning("[login] 没找到登录按钮，改用回车提交（账号 %s）", _mask(account))
        import pyautogui
        pyautogui.press("enter")

    # 5) 等结果
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        time.sleep(6)
        shot = SHOT_DIR / ("%s_%s_wait.png" % (game, tag))
        if not _grab(hwnd, shot):
            return False, "等待过程中窗口消失"
        boxes_w = ocr.run(shot)
        if _has_sms_prompt(boxes_w):
            return False, "需要手机验证码（按要求不做），请手动登录一次"
        err = _has_error(boxes_w)
        if err:
            return False, "登录失败: %s" % err
        if not is_login_screen(boxes_w):
            return True, "登录成功（登录界面已消失）"
    return False, "等了 %d 秒登录界面还在" % max_wait_s


def login_once(game: str, exe: str, tag: str = "", max_wait_s: int = 150):
    """找窗口 → 确认是登录界面 → 登录一次。返回 (ok, message)。"""
    hwnd, size = win_guard.find_window(exe)
    if not hwnd:
        return False, "没有 %s 窗口" % exe
    ocr = Ocr()
    try:
        shot = SHOT_DIR / ("%s_%s_probe.png" % (game, tag or time.strftime("%Y%m%d-%H%M%S")))
        if not _grab(hwnd, shot):
            return False, "截不到窗口"
        boxes = ocr.run(shot)
        if not is_login_screen(boxes):
            return False, "不是登录界面"
        account, password = get_account(game)
        if not account:
            return False, "config/accounts.yaml 里没有 %s 的账号密码" % game
        return try_login(hwnd, game, account, password, ocr, shot_tag=tag, max_wait_s=max_wait_s)
    finally:
        ocr.close()


def watch(exe: str, game: str, stop_event: threading.Event = None,
          timeout_s: int = 900, interval_s: int = 10) -> threading.Event:
    """后台盯登录界面：发现掉登录就自动登录一次（每次运行最多一次）。"""
    done = threading.Event()

    def _loop():
        ocr = Ocr()
        tried = False
        deadline = time.time() + timeout_s
        try:
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    return
                if tried:
                    time.sleep(interval_s)
                    continue
                hwnd, size = win_guard.find_window(exe)
                if not hwnd:
                    time.sleep(interval_s)
                    continue
                tag = time.strftime("%Y%m%d-%H%M%S")
                shot = SHOT_DIR / ("%s_%s_probe.png" % (game, tag))
                if not _grab(hwnd, shot):
                    time.sleep(interval_s)
                    continue
                boxes = ocr.run(shot)
                if is_login_screen(boxes):
                    account, password = get_account(game)
                    if not account:
                        log.warning("[login] %s 需要登录，但 config/accounts.yaml 没配账号密码", game)
                        tried = True
                        continue
                    log.warning("[login] %s 掉登录了，自动用账号密码登录（账号 %s）", game, _mask(account))
                    ok, msg = try_login(hwnd, game, account, password, ocr, shot_tag=tag)
                    tried = True
                    if ok:
                        log.warning("[login] %s %s", game, msg)
                    else:
                        log.error("[login] %s 自动登录失败: %s（截图在 %s）", game, msg, SHOT_DIR)
                    done.set()
                    return
                time.sleep(interval_s)
        except Exception as e:  # noqa: BLE001
            log.warning("[login] %s 登录兜底线程异常结束: %s", game, e)
        finally:
            ocr.close()

    t = threading.Thread(target=_loop, name="login-watch-%s" % game, daemon=True)
    t.start()
    return done


# ---- 绝区零：OneDragon 原生账号密码登录 ---------------------------------------
def ensure_zzz_account(one_dragon_dir: Path, instance: str = "1") -> bool:
    """把绝区零的账号密码写进 OneDragon 的 game_account.yml（原生「国服-账号密码登录」）。"""
    account, password = get_account("zzz")
    if not account:
        return False
    # 目录名是两位零填充的实例号（OneDragon 的 YamlConfig：'%02d' % instance_idx），
    # 写成 config/1 它根本不读 —— 实测只有 config/01/game_account.yml 生效。
    try:
        ins_dir = "%02d" % int(str(instance).strip())
    except Exception:   # noqa: BLE001
        ins_dir = str(instance).strip()
    path = Path(one_dragon_dir) / "config" / ins_dir / "game_account.yml"
    try:
        import yaml
        data = {}
        if path.exists():
            with open(path, encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
        if not isinstance(data, dict):
            data = {}
        changed = False
        for key, val in (("account", account), ("password", password)):
            if data.get(key) != val:
                data[key] = val
                changed = True
        if data.get("game_region") in (None, ""):
            data["game_region"] = "cn"
            changed = True
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fp:
                yaml.safe_dump(data, fp, allow_unicode=True, sort_keys=False)
            log.info("[login] 已把绝区零账号写进 OneDragon: %s", path)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("[login] 写 OneDragon 账号配置失败: %s", e)
        return False
