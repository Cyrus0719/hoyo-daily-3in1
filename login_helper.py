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
import hashlib
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
                "帐号登录", "请输入账号", "请输入帐号", "请输入密码",
                # 2026-11-16 补：原神的米游社登录框没有「登录」二字，
                # 占位提示是「输入手机号/邮箱」，提交按钮写的是「进入游戏」。
                "请输入手机", "输入手机号", "手机号/邮箱", "邮箱/手机号", "进入游戏")
WEAK_HINTS = ("登录", "账号", "帐号", "密码", "验证码")
# ★ 2026-11-16：米游社登录页常驻「手机短信 / TapTap」两个切换标签，
#   原来的 SMS_WORDS 里有裸的「短信」，于是刚点完「进入游戏」、页面还在淡出时
#   就会被判成"需要手机验证码"，白丢一次登录机会。现在只认真正的验证码提示。
SMS_WORDS = ("请输入验证码", "输入验证码", "获取验证码", "发送验证码", "验证码登录", "扫码登录")
ERR_WORDS = ("密码错误", "账号或密码", "帐号或密码", "账号不存在", "帐号不存在", "格式不正确",
             "频繁", "锁定", "失败", "错误", "过期")


# ---- 登录截图的保留策略 ------------------------------------------------------
# 2026-11-20：watch() 每 3 秒截一张探测图，一周下来 logs/login 里堆了 630 张 / 1.1GB。
# 这些只是排查用的临时证据，留最近几天就够 —— 起床跑完自己就清。
SHOT_KEEP_DAYS = 3
SHOT_KEEP_MB = 150


def _prune_shots(keep_days: float = None, keep_mb: float = None) -> int:
    """清掉过期的登录截图：先按天数，再按总大小（从最老的删起）。返回删除数量。"""
    days = SHOT_KEEP_DAYS if keep_days is None else keep_days
    limit_mb = SHOT_KEEP_MB if keep_mb is None else keep_mb
    try:
        files = []
        for p in SHOT_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == ".png":
                st = p.stat()
                files.append([st.st_mtime, st.st_size, p])
    except Exception:
        return 0
    deleted = 0
    cut = time.time() - days * 86400
    keep = []
    for item in files:
        if item[0] < cut:
            try:
                item[2].unlink()
                deleted += 1
            except Exception:
                keep.append(item)
        else:
            keep.append(item)
    total = sum(i[1] for i in keep)
    if total > limit_mb * 1048576:
        keep.sort()          # 最老的先删
        for item in keep:
            if total <= limit_mb * 1048576:
                break
            try:
                item[2].unlink()
                total -= item[1]
                deleted += 1
            except Exception:
                pass
    if deleted:
        log.info("[login] 清理了 %d 张过期登录截图（保留 %g 天 / %g MB）", deleted, days, limit_mb)
    return deleted


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


# 2026-11-19 实测的原文是「189*****80，欢迎进入游戏」（不是"欢迎回来"），
# 所以除了几个"欢迎…"句式，再认一条：带打码账号 + 「进入游戏」的那一行。
_WELCOME_WORDS = ("欢迎进入游戏", "欢迎回来", "歡迎回來", "欢迎回到", "欢迎登入",
                  "点击进入游戏画面")
_WELCOME_MASKED = ("*****", "＊＊＊＊＊", "****")
def _is_welcome(boxes) -> bool:
    """「189*****80，欢迎进入游戏」这种【已经登录成功】的过场页。

    2026-11-19 事故：崩铁这一页的按钮文字就是「进入游戏」，被 STRONG_HINTS 当成了登录框
    → 每 3 秒抢一次前台、跑一次 OCR、还要去填账号密码；三月七同时在截图识别，
    07:25:35 那一轮之后它就无声退出了（日志只到「窗口已切换到前台」）。"""
    for b in boxes:
        t = _txt(b)
        if any(w in t for w in _WELCOME_WORDS):
            return True
        if "进入游戏" in t and any(m in t for m in _WELCOME_MASKED):
            return True
    return False


def _foreground(hwnd, force: bool = True) -> bool:
    """把窗口真的提到前台，并【确认】成功。

    force=False：只承认"它本来就是前台"，绝不抢焦点（给周期性探测用，
    2026-11-19 起探测不再每 3 秒顶掉用户正在用的窗口）。

    2026-11-16 事故：崩铁那趟的"登录界面截图"其实截的是桌面 —— 三月七的黑窗口和浏览器
    盖在游戏上面。SetForegroundWindow 在后台进程里会被 Windows 的前台锁静默拒绝，于是
    ImageGrab 截到的是【压在最上面的别人的窗口】。所以这里改成：① 先试 Alt 键解锁
    （keybd_event ALT 是官方认可的前台借用方式）；② 每次都用 GetForegroundWindow 复核；
    ③ 拿不到就返回 False，让调用方跳过这一轮，绝不把别的窗口当游戏画面去 OCR。"""
    try:
        if u.GetForegroundWindow() == hwnd:
            return True
        if not force:
            return False
        u.ShowWindow(hwnd, 9)          # SW_RESTORE
        time.sleep(0.15)
        # ① 先好好要一次（不按键）—— 大多数情况这就够了
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        for _ in range(4):
            time.sleep(0.12)
            if u.GetForegroundWindow() == hwnd:
                return True
        # ② 还不行才用 Alt 解锁前台锁。★ 这是【全局合成按键】，只在真要填表这一刻按一次：
        #    2026-11-19 那次它每 3 秒按一次 ALT，07:25:36 之后三月七就无声退出了 ——
        #    合成 ALT 会激活别人窗口的菜单栏，绝不能再周期性发。
        u.keybd_event(0x12, 0, 0, 0)      # ALT down
        u.keybd_event(0x12, 0, 2, 0)      # ALT up
        time.sleep(0.12)
        u.SetForegroundWindow(hwnd)
        u.BringWindowToTop(hwnd)
        for _ in range(6):
            time.sleep(0.15)
            if u.GetForegroundWindow() == hwnd:
                return True
        return False
    except Exception:
        return False


def _grab(hwnd, path: Path, raise_: bool = True):
    """截客户区。拿不到前台就返回 None（宁可这轮不判断，也不要截错窗口）。

    raise_=False：周期性探测【绝不抢前台】—— 用户正在别的程序里时直接跳过这一轮。
    真正要填表时才 raise_=True（那一刻必须让游戏到前台才打得了字）。"""
    if not _foreground(hwnd, force=raise_):
        return None
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
    # ★ 2026-11-19：「欢迎回来 / 进入游戏」是【登录成功之后】的过场页，不是登录框。
    #   崩铁这一页的按钮文字跟登录框的提交按钮一模一样，认错了就会一直去填表。
    if _is_welcome(boxes):
        return False
    strong = _pick(boxes, STRONG_HINTS)
    if strong:
        return True
    weak = {_txt(b) for b in _pick(boxes, WEAK_HINTS)}
    return len(weak) >= 2 and any("登录" in t for t in weak)


def _find_password_tab(boxes):
    """「账号密码登录 / 密码登录 / 账号登录」这种切换入口。"""
    # ★ 2026-11-17：崩铁的登录框默认停在【手机验证码】页，底部那个切换标签在 OCR 里
    #   就四个字「账号密码」（后面没有「登录」二字，截图 y=752 x=852 实测 score=1.00）。
    #   原来只认「账号密码登录」，于是永远匹配不到 → 报「没找到密码输入框」→ 掉登录后
    #   一次都没成功过。现在把短形式也认上。
    cands = _pick(boxes, ("账号密码登录", "帐号密码登录", "账号密码", "帐号密码",
                          "密码登录", "账号登录", "帐号登录"),
                  exclude_any=("请输入", "忘记", "验证码", "用户协议"))
    if not cands:
        return None
    cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


_ACC_WORDS = ("请输入账号", "请输入帐号", "请输入手机", "请输入邮箱", "输入手机号",
              "手机号/邮箱", "邮箱/手机号", "手机号", "邮箱", "账号", "帐号")


def _find_account_field(boxes, pwd_box=None):
    """找账号输入框。

    2026-11-16 修：米游社登录框的占位提示是浅灰的「输入手机号/邮箱」，
    OCR 置信度常常只有 0.3~0.5，原来卡在 min_score=0.5 上，于是永远"没读到账号框"，
    走固定行高兜底又把点击位置算偏了一行，最后判定"账号没输进去"。
    现在放宽到 0.3，并且只在密码框【上方】挑（同一个对话框里账号框必在密码框上面）。"""
    cands = _pick(boxes, _ACC_WORDS,
                  exclude_any=("密码", "登录", "验证码", "忘记", "注册", "切换", "扫码",
                               "用户协议", "隐私政策"),
                  min_score=0.3)
    if pwd_box is not None:
        above = [b for b in cands if b["y2"] <= pwd_box["y1"] + 12]
        if above:
            cands = above
    if not cands:
        return None
    if pwd_box is not None:
        # 离密码框最近的那一行才是账号框
        cands.sort(key=lambda b: (abs(b["y2"] - pwd_box["y1"]), b["y1"]))
    else:
        cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


def _guess_account_row(boxes, pwd_box):
    """推断账号框：取密码框正上方、最近的那一行文字；都没有才按实测间距推算。

    实测（原神 1920x1080 登录框）：账号框中心到密码框中心约 3 个字高，
    原来写的 1.7 个字高会把点点击落在两个框中间。"""
    h = max(20, pwd_box["y2"] - pwd_box["y1"])
    up = [b for b in boxes
          if b["y2"] <= pwd_box["y1"] + 6
          and (pwd_box["y1"] - b["y2"]) <= 3.4 * h
          and b["x2"] > pwd_box["x1"] - h and b["x1"] < pwd_box["x2"] + h]
    if up:
        return dict(min(up, key=lambda x: pwd_box["y1"] - x["y2"]))
    box = dict(pwd_box)
    box["y1"] = pwd_box["y1"] - int(h * 2.9)
    box["y2"] = pwd_box["y2"] - int(h * 2.9)
    return box


def _find_password_field(boxes):
    cands = _pick(boxes, ("请输入密码", "密码"),
                  exclude_any=("登录", "忘记", "验证码", "账号", "帐号", "注册", "修改", "重置", "找回"))
    if not cands:
        return None
    cands.sort(key=lambda b: (b["y1"], b["x1"]))
    return cands[0]


def _find_login_button(boxes, password_box=None):
    # 原神的提交按钮写的是「进入游戏」；崩铁/绝区零是「登录」/「登入」
    cands = _pick(boxes, ("进入游戏", "立即登录", "登录", "登入"),
                  exclude_any=("忘记", "验证码", "账号密码", "帐号密码", "密码登录", "账号登录",
                               "帐号登录", "注册", "切换", "其他", "退出",
                               "手机短信", "手机", "TapTap", "用户协议", "隐私政策", "扫码"))
    # 「进入游戏」优先（米游社登录框上同时有「手机短信/TapTap」，只有那一个宽按钮）
    cands.sort(key=lambda b: 0 if "进入游戏" in _txt(b) else 1)
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
        # 「进入游戏」是米游社登录框里唯一的宽按钮，排最前
        is_enter = 0 if "进入游戏" in _txt(b) else 1
        return (is_enter, -wide, dist, b["y1"])
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


def _find_typed(boxes, field_box, needle: str, pad: int = 6):
    """在指定输入框的纵向范围里找刚输入的内容。"""
    if not needle:
        return None
    needle = needle.replace(" ", "")
    for b in boxes:
        t = _txt(b)
        if needle in t and _overlaps(b, field_box, pad=pad):
            return b
    return None


def _digits_box(boxes, field_box, need: int = 4, pad: int = 6):
    for b in boxes:
        t = _txt(b)
        if sum(ch.isdigit() for ch in t) >= need and _overlaps(b, field_box, pad=pad):
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
    """填账号并复核。返回 (ok, boxes, acc_box)。

    2026-11-16 修：复核原来用 pad=6 的严格重叠。账号框如果是"推断"出来的（没有占位文字
    可读），点进去其实是对的，但输入后的数字行与推断框差了 30~40 px，于是被判"没输进去"，
    还把已经填好的内容清掉重来三次。现在：① 容差放宽到 40px；② 只清"明显跑到别的行"的内容；
    ③ 第二次改用逐字输入（有些框不吃 Ctrl+V）。"""
    needle = account[-6:]
    boxes = []
    for i in range(1, attempts + 1):
        cx, cy = _center(acc_box)
        _click(ox + cx, oy + cy)
        time.sleep(0.5)
        if i == 1:
            _paste(account)
        else:
            import pyautogui
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.15)
            pyautogui.write(account, interval=0.03)
        time.sleep(1.1)
        shot = SHOT_DIR / ("%s_%s_acc%d.png" % (game, tag, i))
        if not _grab(hwnd, shot):
            continue
        boxes = ocr.run(shot)
        hit = (_find_typed(boxes, acc_box, needle, pad=40)
               or _digits_box(boxes, acc_box, 4, pad=40))
        if hit is not None:
            return True, boxes, acc_box
        # 数字跑到明显别的行（离账号框 40px 以上）才清，避免把填对的内容删掉
        for b in _pick(boxes, (needle,), min_score=0.25):
            if not _overlaps(b, acc_box, pad=40):
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


def _gold_count(shot, box, h: int) -> int:
    """数一下协议行左侧那个圆里有多少"金色"像素。

    已勾选 = 金色实心圆 + 白勾（截图实测），未勾选 = 浅灰空心圈。
    所以"点完是不是真的勾上了"可以直接用颜色判定，不靠猜。"""
    try:
        from PIL import Image
        im = Image.open(str(shot)).convert("RGB")
    except Exception:
        return -1
    # ★ 2026-11-20：原来框取到 x1 右侧 2.2 个字高，正好把《用户协议》那条橙色链接
    #   也算进来；协议页（白底正文）在那块区域也能凑够 20 个"金色"像素 → 误判"已经勾上了"。
    #   现在只数圆圈左右一小块：已勾 213、未勾 0、协议页 9（阈值 20 能分开）。
    cy = (box["y1"] + box["y2"]) // 2
    x1 = max(0, box["x1"] - int(1.2 * h))
    x2 = min(im.width, box["x1"] + int(1.3 * h))
    y1 = max(0, cy - int(0.6 * h))
    y2 = min(im.height, cy + int(0.6 * h))
    n = 0
    for y in range(y1, y2):
        for x in range(x1, x2):
            r, g, b = im.getpixel((x, y))
            if r >= 185 and 115 <= g <= 220 and b <= 135:
                n += 1
    return n


# ---- 协议页：点了《用户协议》链接会全屏打开一个网页 ----------------------
# ★ 2026-11-20 事故：勾选协议时先点了【文字中心】，那是《用户协议》超链接 ——
#   一点就全屏打开协议网页，游戏卡在这一页两分钟，我们又把"登录框看不见了"
#   当成"登录成功"。协议页本身没有登录框，必须能识别、能退出来。
_PROTO_WORDS = ("用户协议", "隐私政策", "服务协议", "条款", "协议", "生效", "更新日期")


def _is_protocol_page(boxes, width: int = 0) -> bool:
    """认「用户协议/隐私政策」那种全屏网页。"""
    if not boxes:
        return False
    if _pick(boxes, ("进入游戏", "验证码", "输入密码", "请输入密码", "忘记密码"), min_score=0.4):
        return False
    if is_login_screen(boxes):
        return False
    joined = "".join(_txt(b) for b in boxes)
    if len(joined) < 80:
        return False
    hits = sum(1 for k in _PROTO_WORDS if k in joined)
    if hits < 2:
        return False
    if width:
        wide = [b for b in boxes if (b["x2"] - b["x1"]) > 0.5 * width]
        return len(wide) >= 3
    return len(boxes) >= 6


def _close_protocol(hwnd, ox: int, oy: int, ocr=None, uniq: str = "") -> bool:
    """把协议页退掉：先按 ESC（游戏自己提示"按ESC后重试"），不行再点左上角的 ✕。"""
    import pyautogui  # noqa: PLC0415

    rect = _client_rect(hwnd) or (0, 0, 0, 0)
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    for attempt in (1, 2):
        pyautogui.press("esc")
        time.sleep(1.0)
        shot = SHOT_DIR / ("%s_%s_proto_esc%d.png" % ("login", uniq, attempt))
        if not _grab(hwnd, shot):
            return False
        if ocr is None:
            return True
        boxes = ocr.run(shot)
        if not _is_protocol_page(boxes, w):
            log.info("[login] 协议页已用 ESC 退出")
            return True
        if w and h:
            x = ox + int(w * 0.035)
            y = oy + int(h * 0.030)
            log.info("[login] ESC 没退出协议页，改点左上角关闭（%d,%d）", x, y)
            _click(x, y)
            time.sleep(1.0)
            shot2 = SHOT_DIR / ("%s_%s_protox%d.png" % ("login", uniq, attempt))
            if _grab(hwnd, shot2):
                if not _is_protocol_page(ocr.run(shot2), w):
                    log.info("[login] 协议页已关闭")
                    return True
    log.warning("[login] 协议页关不掉（已存截图 %s）", SHOT_DIR)
    return False


# 圆圈中心相对"文字框左边 x1"的偏移（单位：字高）。
# 2026-11-20 用真实截图量过：崩铁 x1=682 圆圈中心 696（0.56h），原神 x1=684 圆圈中心 695（0.55h）。
# 全部候选都 < +1.0h：离《用户协议》链接（≥1.5h）还有距离，再怎么错也点不到链接上。
_AGREE_X_STEPS = (0.55, 0.35, 0.75, 0.15, -0.15)


def _tick_agreement(hwnd, ox: int, oy: int, boxes, shot, uniq: str = "", ocr=None):
    """勾选『同意《用户协议》和《隐私政策》』，并回头验证真的勾上了。

    ★ 2026-11-20：只点文字左边那个圆圈，【绝不点文字】—— 文字是超链接。
      点完立刻用金色像素复核；万一还是点开了，识别到协议页就退出来再继续。"""
    agree = _pick(boxes, ("同意",), exclude_any=("已同意", "不同意"), min_score=0.25)
    if not agree:
        log.warning("[login] 没找到『同意《用户协议》』那一行，跳过勾选")
        return False
    box = agree[0]
    h = max(12, box["y2"] - box["y1"])
    cy = (box["y1"] + box["y2"]) // 2
    if _gold_count(shot, box, h) >= 20:
        log.info("[login] 『%s』已经勾上了", _txt(box)[:18])
        return True
    rect = _client_rect(hwnd) or (0, 0, 0, 0)
    w = rect[2] - rect[0]
    deadline = time.time() + 12
    for i, k in enumerate(_AGREE_X_STEPS):
        if time.time() > deadline:
            break
        tx = box["x1"] + int(k * h)
        log.info("[login] 勾选『%s』（点圆圈第 %d 次，屏幕 %d,%d，不点文字）",
                 _txt(box)[:18], i + 1, ox + tx, oy + cy)
        _click(ox + tx, oy + cy)
        time.sleep(0.6)
        shot2 = SHOT_DIR / ("%s_agree%s_%d.png" % ("login", uniq, i + 1))
        if not _grab(hwnd, shot2):
            continue
        if _gold_count(shot2, box, h) >= 20:
            log.info("[login] 协议已勾上")
            return True
        if ocr is not None and _is_protocol_page(ocr.run(shot2), w):
            log.warning("[login] 点到协议链接、页面被点开了 → 退出协议页再继续")
            if _close_protocol(hwnd, ox, oy, ocr, uniq):
                continue
            return False
    log.warning("[login] 协议勾选没生效（金色像素没出现），继续试登录")
    return False


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

    width = rect[2] - rect[0]

    shot = SHOT_DIR / ("%s_%s_0.png" % (game, tag))
    if not _grab(hwnd, shot):
        return False, "截不到窗口"
    boxes = ocr.run(shot)
    if not boxes:
        return False, "OCR 没读出文字"

    # 0) 上一轮要是不小心把协议页点开了，先退出来，别在协议页上乱点
    if _is_protocol_page(boxes, width):
        log.warning("[login] 画面停在协议页，先关掉它")
        if _close_protocol(hwnd, ox, oy, ocr, tag):
            _grab(hwnd, shot)
            boxes = ocr.run(shot) or boxes

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
    acc_field = _find_account_field(boxes, pwd_field)
    if acc_field is None or not _overlaps(acc_field, pwd_field):
        acc_field = _guess_account_row(boxes, pwd_field)
        log.info("[login] 没读到账号框，按密码框上方最近一行推断位置")

    ok, boxes, acc_field = _fill_account(hwnd, ox, oy, acc_field, account, ocr, game, tag)
    if not ok:
        return False, "账号没输进去（复核失败，不输入密码）"
    log.info("[login] 账号已填入: %s", _mask(account))

    # 3) 密码框
    pwd_field = _find_password_field(boxes) or pwd_field
    ok, boxes = _fill_password(hwnd, ox, oy, pwd_field, password, ocr, game, tag)
    if not ok:
        return False, "密码没输进去（复核失败，不点登录）"

    # 3.5) 米游社登录框要先勾『同意《用户协议》』，否则「进入游戏」点了没反应
    shot_ag = SHOT_DIR / ("%s_%s_agree.png" % (game, tag))
    if _grab(hwnd, shot_ag):
        boxes_ag = ocr.run(shot_ag)
        if boxes_ag:
            boxes = boxes_ag
        _tick_agreement(hwnd, ox, oy, boxes, shot_ag, uniq=tag, ocr=ocr)
    else:
        log.warning("[login] 截不到窗口，跳过协议勾选")

    # 4) 点登录（找不到按钮就按回车）
    btn = _find_login_button(boxes, pwd_field)
    if btn is not None:
        log.info("[login] 点「%s」提交登录（账号 %s）", _txt(btn), _mask(account))
        _click(*screen(btn))
    else:
        log.warning("[login] 没找到登录按钮，改用回车提交（账号 %s）", _mask(account))
        import pyautogui
        pyautogui.press("enter")

    # 5) 等结果 —— 登录框消失 ≠ 登录成功（可能只是协议页顶在最前面）
    #    ★ 2026-11-20 实测：07:25:31 提交时画面正停在协议页，07:25:40 就"看不见登录框了"，
    #      于是被判成"登录成功"，游戏在协议页上干等了两分钟。现在要求：
    #      连续两次都不是登录框、也不是协议页，才算成功。
    deadline = time.time() + max_wait_s
    t_submit = time.time()
    clean = 0
    retried = False
    while time.time() < deadline:
        time.sleep(3)
        shot = SHOT_DIR / ("%s_%s_wait.png" % (game, tag))
        if not _grab(hwnd, shot):
            return False, "等待过程中窗口消失"
        boxes_w = ocr.run(shot)
        if _is_protocol_page(boxes_w, width):
            log.warning("[login] 提交后又冒出协议页 → 先关掉它再继续等")
            _close_protocol(hwnd, ox, oy, ocr, tag)
            clean = 0
            continue
        if _has_sms_prompt(boxes_w):
            return False, "需要手机验证码（按要求不做），请手动登录一次"
        err = _has_error(boxes_w)
        if err:
            return False, "登录失败: %s" % err
        if is_login_screen(boxes_w):
            clean = 0
            # 登录框还在：八成是「同意」没勾上，「进入游戏」点了没反应 → 补勾一次再提交（只补一次）
            if not retried and time.time() - t_submit > 20:
                retried = True
                log.warning("[login] 点了进入游戏没反应，补勾协议后再提交一次")
                _tick_agreement(hwnd, ox, oy, boxes_w, shot, uniq=tag + "r", ocr=ocr)
                btn2 = _find_login_button(boxes_w, pwd_field)
                if btn2 is not None:
                    _click(*screen(btn2))
                else:
                    import pyautogui  # noqa: PLC0415
                    pyautogui.press("enter")
                t_submit = time.time()
            continue
        clean += 1
        if clean >= 2:
            return True, "登录成功（登录界面已消失，画面不是协议页）"
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
          timeout_s: int = 900, interval_s: int = 3) -> threading.Event:
    """后台盯登录界面：发现掉登录就自动登录（最多 2 次尝试）。

    2026-11-16：间隔从 10 秒降到 3 秒 —— 三月七从"游戏到前台"到判"账号登录过期"
    只有约 16 秒，10 秒一轮根本抢不到登录窗口。"""
    done = threading.Event()

    def _loop():
        _prune_shots()
        ocr = Ocr()
        tried = 0
        max_try = 2
        t_begin = time.time()
        deadline = time.time() + timeout_s
        try:
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    return
                if tried >= max_try:
                    time.sleep(interval_s)
                    continue
                hwnd, size = win_guard.find_window(exe)
                if not hwnd:
                    time.sleep(interval_s)
                    continue
                tag = time.strftime("%Y%m%d-%H%M%S")
                shot = SHOT_DIR / ("%s_%s_probe.png" % (game, tag))
                if not _grab(hwnd, shot, raise_=False):
                    # 不是前台（游戏窗口被别的窗口盖着 / 用户在干别的）—— 这轮跳过，
                    # 绝不抢焦点、也不 OCR 别人的画面
                    time.sleep(interval_s)
                    continue
                boxes = ocr.run(shot)
                if is_login_screen(boxes):
                    # ★ 2026-11-20：登录框刚冒出来时【先别动手】。
                    #   游戏可能正在拿"记住的账号"自动登录；我们一上来就点「账号密码」
                    #   切换登录方式，等于把这次自动登录打断 —— 当天 07:25:15 我们点了
                    #   那个标签，07:25:18 注册表里的账号就被清成 24 字节空值。
                    #   所以先等它一下：等得起就等 20 秒，账号本来就已经空了的只等 6 秒。
                    grace = _login_grace(game)
                    log.warning("[login] %s 掉登录了（记住的账号 %d 字节），先等 %d 秒看它自己能不能登进去",
                                game, _adl_len(game), grace)
                    t_wait = time.time()
                    auto = False
                    while time.time() - t_wait < grace:
                        time.sleep(2)
                        if stop_event is not None and stop_event.is_set():
                            return
                        shot_g = SHOT_DIR / ("%s_%s_grace.png" % (game, tag))
                        if not _grab(hwnd, shot_g, raise_=False):
                            continue
                        if not is_login_screen(ocr.run(shot_g)):
                            auto = True
                            break
                    if auto:
                        log.info("[login] %s 登录框自己消失了（游戏自己登进去了），不动手", game)
                        continue
                    account, password = get_account(game)
                    if not account:
                        log.warning("[login] %s 需要登录，但 config/accounts.yaml 没配账号密码", game)
                        tried = max_try
                        continue
                    log.warning("[login] %s 掉登录了，自动用账号密码登录（账号 %s）", game, _mask(account))
                    tried += 1
                    ok, msg = try_login(hwnd, game, account, password, ocr, shot_tag=tag)
                    if ok:
                        log.warning("[login] %s %s", game, msg)
                        done.set()
                        return
                    log.error("[login] %s 自动登录失败(第 %d 次): %s（截图在 %s）", game, tried, msg, SHOT_DIR)
                    if tried >= max_try:
                        done.set()
                        return
                    time.sleep(5)
                    continue
                # 登录界面只会在启动后最初几分钟出现：前 5 分钟每 3 秒看一次（抢时间），
                # 之后退到 12 秒一次，别拿 OCR 一直占 CPU。
                if time.time() - t_begin < 300:
                    time.sleep(interval_s)
                else:
                    time.sleep(max(interval_s, 12))
        except Exception as e:  # noqa: BLE001
            log.warning("[login] %s 登录兜底线程异常结束: %s", game, e)
        finally:
            ocr.close()

    t = threading.Thread(target=_loop, name="login-watch-%s" % game, daemon=True)
    t.start()
    return done


# ---- 登录态指纹：抓"到底是谁把记住的账号弄没了" --------------------------
# 三款游戏的「记住我」都存在 HKCU\Software\miHoYo\<游戏> 的 MIHOYOSDK_ADL* 值里
# （base64 密文）。每次运行前后各记一次指纹，就能回答那个吵了半个月的问题：
#   · 两次之间（机器空转/关机重启期间）指纹变了 → 是系统/其他程序在改；
#   · 指纹没变但仍然要登录        → 数据没丢，是服务器不认这个 token 了（风控/过期）。
ADL_GAMES = {"genshin": "原神", "starrail": "崩坏：星穹铁道", "zzz": "绝区零"}
ADL_LOG = Path(__file__).resolve().parent / "logs" / "adl_state.log"


def _adl_map() -> dict:
    """{ 'genshin.dl_0': '1304:ff77e0cf44', ... } —— 固定顺序，便于两两对比。"""
    import winreg  # noqa: PLC0415

    out = {}
    for key, cn in sorted(ADL_GAMES.items()):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\miHoYo\\" + cn)
        except OSError:
            out[key + ".dl_0"] = "missing"
            out[key + ".d_cn"] = "missing"
            continue
        n = winreg.QueryInfoKey(k)[1]
        vals = {}
        for i in range(n):
            try:
                name, val, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            if isinstance(val, bytes) and name.startswith("MIHOYOSDK_ADL"):
                vals[name.split("_h")[0]] = val
        winreg.CloseKey(k)
        for short in ("MIHOYOSDK_ADL_0", "MIHOYOSDK_ADL_PROD_CN"):
            v = vals.get(short)
            tag = short[-4:].lower()
            if v is None:
                out["%s.%s" % (key, tag)] = "none"
            else:
                out["%s.%s" % (key, tag)] = "%d:%s" % (len(v), hashlib.sha1(v).hexdigest()[:10])
    return out


_ADL_SENTINEL_LEN = 100   # ≤100 字节 = "没有记住的账号"的空值哨兵（实测 24 字节）


def _adl_len(game: str) -> int:
    """某个游戏当前"记住的账号"有多少字节（-1 = 没有这个值）。"""
    v = _adl_map().get("%s.dl_0" % game, "none")
    if v in ("none", "missing"):
        return -1
    try:
        return int(v.split(":")[0])
    except ValueError:
        return -1


def _login_grace(game: str) -> int:
    """看到登录框后先等几秒再动手。

    账号还在（>100 字节）→ 等 20 秒，给它自己用记住的账号登进去的机会；
    账号已经被清成空值 → 只等 6 秒，别白白拖着三月七。"""
    return 20 if _adl_len(game) > _ADL_SENTINEL_LEN else 6


def adl_fingerprint() -> str:
    """三个游戏记住的账号数据的指纹（不落原文，只落长度+哈希）。"""
    m = _adl_map()
    return " ".join("%s=%s" % (k, m[k]) for k in m)


def snapshot_adl(tag: str) -> None:
    """把当前的登录态指纹追加写进 logs/adl_state.log（一行一次，便于对比）。"""
    try:
        fp = adl_fingerprint()
        ADL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ADL_LOG, "a", encoding="utf-8") as fp_out:
            fp_out.write("%s\t%s\t%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), tag, fp))
    except Exception as e:  # noqa: BLE001
        log.warning("[login] 记录登录态指纹失败: %s", e)


class AdlWatch(threading.Thread):
    """运行期间盯着登录态数据：一变就记一行（分清是哪一款、从多少字节变成多少字节）。

    2026-11-17 就是靠前后指纹才发现「预登录把崩铁的 1304 字节清成 24 字节」的。
    常驻这个线程后，下次再掉登录，日志里会直接写明是哪一秒、哪一款被动过。
    """

    def __init__(self, game: str = "", interval_s: int = 10):
        super().__init__(name="adl-watch", daemon=True)
        self.game = game
        self.interval_s = interval_s
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        try:
            last = _adl_map()
        except Exception:   # noqa: BLE001
            return
        while not self._stop_evt.wait(self.interval_s):
            try:
                cur = _adl_map()
            except Exception:   # noqa: BLE001
                continue
            if cur == last:
                continue
            diff = ["%s %s → %s" % (k, last.get(k, "?"), cur.get(k, "?"))
                    for k in cur if cur.get(k) != last.get(k)]
            log.warning("[login] ⚠ 登录态数据在运行中被改：%s", "；".join(diff))
            snapshot_adl("changed-%s" % (self.game or "run"))
            last = cur


def start_adl_watch(game: str = "", interval_s: int = 10):
    """启动登录态监视线程；失败返回 None（不影响主流程）。"""
    try:
        w = AdlWatch(game, interval_s)
        w.start()
        return w
    except Exception as e:   # noqa: BLE001
        log.warning("[login] 登录态监视线程没起来（不影响主流程）: %s", e)
        return None


# ---- 上游"登录已过期"的提前判断 + 预登录 ------------------------------------
LOCALLOW = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow"

# 游戏本体的 SDK 日志：成功自动登录会写 "into LoginByToken."，
# 掉登录时会写 "into AccountPlatPhoneLoginJobber."（= 弹账号密码登录页）。
SDK_LOGS = {
    "starrail": LOCALLOW / "miHoYo" / "崩坏：星穹铁道" / "logs" / "MiHoYoSDK.log",
    "genshin": LOCALLOW / "miHoYo" / "原神" / "logs" / "NativeSDK.log",
}


def sdk_needs_password(game: str) -> bool:
    """读游戏自己的 SDK 日志，判断"下一次启动会不会弹登录页"。

    只看最后 4MB：成功登录的关键行是 `into LoginByToken.`，
    要输密码的关键行是 `into AccountPlatPhoneLoginJobber.`；
    谁在最后面，谁代表当前状态。读不到日志时返回 False（不折腾）。"""
    path = SDK_LOGS.get(game)
    if path is None:
        return False
    try:
        size = path.stat().st_size
        with open(path, "rb") as fp:
            fp.seek(max(0, size - 4_000_000))
            text = fp.read().decode("utf-8", "ignore")
    except Exception:
        return False
    tok = text.rfind("into LoginByToken")
    # 两个游戏用的类名不一样：崩铁是 PhoneLoginJobber，原神是 AccountLoginJobber。
    pwd = max(text.rfind("into AccountPlatPhoneLoginJobber"),
              text.rfind("into AccountPlatAccountLoginJobber"))
    if pwd < 0:
        return False
    return pwd > tok


def preflight_login(game: str, exe: str, launch_cmd=None, cwd=None,
                    wait_window_s: int = 240, max_wait_s: int = 120,
                    close_after: bool = True):
    """自己先把游戏开到登录界面 → 用账号密码登录 → 关掉游戏（让它把 token 写回本地）。

    为什么需要（2026-11-16）：三月七从"游戏切到前台"到判死「账号登录过期」只有约 16 秒，
    然后 terminate + 重启游戏，最多 3 次（用户看到的"游戏一直退出又启动"）。
    后台 watch() 线程再快也抢不过它的看门狗。所以先把登录这一关自己过掉：
    登录成功后游戏会把 token 落盘，上游就能像平常一样自动登录。
    返回 (ok, message)；ok=False 只是"没登上"，调用方自己决定要不要继续。"""
    account, password = get_account(game)
    if not account:
        return False, "config/accounts.yaml 没配 %s 的账号密码" % game
    if launch_cmd:
        try:
            subprocess.Popen(launch_cmd, cwd=str(cwd) if cwd else None,
                             creationflags=0x08000000,  # CREATE_NO_WINDOW
                             stdin=subprocess.DEVNULL)
            log.info("[login] 预登录：启动游戏 %s", Path(str(launch_cmd[0])).name)
        except Exception as e:  # noqa: BLE001
            return False, "启动游戏失败: %s" % e
    # 等窗口
    t0 = time.time()
    hwnd = None
    while time.time() - t0 < wait_window_s:
        hwnd, _size = win_guard.find_window(exe)
        if hwnd:
            break
        time.sleep(3)
    if not hwnd:
        return False, "等了 %d 秒没等到 %s 窗口" % (wait_window_s, exe)

    ocr = Ocr()
    try:
        t_start = time.time()
        while time.time() - t_start < max_wait_s:
            tag = time.strftime("%Y%m%d-%H%M%S")
            shot = SHOT_DIR / ("%s_%s_preflight.png" % (game, tag))
            if not _grab(hwnd, shot):
                time.sleep(3)
                continue
            boxes = ocr.run(shot)
            if is_login_screen(boxes):
                log.warning("[login] 预登录：%s 在登录界面，用账号密码登录（账号 %s）",
                            game, _mask(account))
                ok, msg = try_login(hwnd, game, account, password, ocr, shot_tag=tag,
                                    max_wait_s=max_wait_s)
            else:
                # 已经不是登录界面（多半是 token 还好 / 已经在进游戏）——不用我们管
                ok, msg = True, "没看到登录界面（不需要登录）"
            break
        else:
            ok, msg = False, "%d 秒内没截到可用画面" % max_wait_s
    finally:
        ocr.close()

    if ok and close_after:
        try:
            import game_proc
            game_proc.close(exe, grace_s=45, force_after_s=180)
            game_proc.wait_gone(exe, 90)
            log.info("[login] 预登录完成，已把游戏关掉（token 已写回本地）")
        except Exception as e:  # noqa: BLE001
            log.warning("[login] 预登录后关游戏失败: %s", e)
    return ok, msg


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
