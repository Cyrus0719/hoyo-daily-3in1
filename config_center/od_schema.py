# -*- coding: utf-8 -*-
"""从 OneDragon 源码里读「每个功能真正有哪些设置 + 默认值 + 可选值」。

为什么需要：OneDragon 每个功能的配置 yml 只写「改过的键」，没改的用源码里的默认值。
直接读 yml 只能看到一两行，界面上就显得「没有详细设置」。这里把源码里
@property + self.get('key', 默认值) 解析出来，界面就能像上游 GUI 一样列出全部可配项。

解析对象：OneDragon-ref/src 下所有 *_config.py（排除 .venv）。
产物：
  apps()            -> {app_id: {"label": 中文名, "path": yml 相对路径, "keys": [...]}}
  schema(app_id)    -> {key: 默认值}      （只含能解析出默认值的键）
  options(app_id)   -> {key: {"ui":..., "options":[...]}}   （枚举型字段给下拉）
"""

import ast
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OD = BASE / "OneDragon-ref"
SRC = OD / "src"

_CACHE = {}


# --------------------------------------------------------------------------- 解析枚举
_RE_ENUM = re.compile(r"^class\s+(\w+)\s*\(\s*(?:Enum|str,\s*Enum)\s*\)\s*:(.*?)(?=^class\s|\Z)", re.M | re.S)
_RE_ITEM = re.compile(r"^\s+(\w+)\s*=\s*ConfigItem\(\s*'([^']*)'\s*(?:,\s*'([^']*)')?", re.M)


def _enums(text):
    """返回 {枚举类名: [{"value":值,"label":中文}, ...]}（值 = ConfigItem 的第一个字符串）。"""
    out = {}
    for m in _RE_ENUM.finditer(text):
        name, body = m.group(1), m.group(2)
        items = []
        for im in _RE_ITEM.finditer(body):
            val, desc = im.group(2), (im.group(3) or "")
            label = val if (not desc or desc == val or desc == "跳过") else ("%s（%s）" % (val, desc))
            items.append({"value": val, "label": label})
        if items:
            out[name] = items
    return out


# --------------------------------------------------------------------------- 解析属性
_RE_PROP = re.compile(
    r"@property\s*\n\s*def\s+(\w+)\s*\(\s*self\s*\)\s*(?:->\s*([^:\n]+))?\s*:\s*\n"
    r"((?:[ \t]*(?:r?\"\"\"(?:.|\n)*?\"\"\"|#.*)\s*\n)*)"
    r"\s*return\s+self\.get\(\s*'([^']+)'\s*(?:,\s*(.+?))?\s*\)\s*\n",
    re.M,
)

_RE_CONST_APPID = re.compile(r"APP_ID\s*=\s*'([^']+)'")


def _const_app_id(py_file):
    """xxx_const.py 里的 APP_ID。"""
    try:
        text = py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _RE_CONST_APPID.search(text)
    return m.group(1) if m else ""


def _app_id_of(py_file, text):
    m = re.search(r"app_id\s*=\s*'([^']+)'", text)
    if m:
        return m.group(1)
    m = re.search(r"app_id\s*=\s*(\w+)\.APP_ID", text)
    if m:
        mod = m.group(1)          # 例如 withered_domain_const
        for cand in (py_file.parent / (mod.split(".")[-1] + ".py"),
                     py_file.parent / (mod.split(".")[-1] + ".py")):
            aid = _const_app_id(cand)
            if aid:
                return aid
        for cand in py_file.parent.glob("*.py"):
            if cand.name.endswith("_const.py"):
                aid = _const_app_id(cand)
                if aid and mod.split(".")[-1] in cand.stem:
                    return aid
    return py_file.parent.name


_LIT = ("True", "False", "None")


def _resolve_default(expr, enums):
    """把 self.get('k', 默认值) 里的默认值表达式解析成 Python 值。解析不出来返回 (None, False)。"""
    if expr is None:
        return None, True                      # 没有默认值（self.get('k')），当作未知
    expr = expr.strip()
    if not expr:
        return None, False
    # 枚举：LostVoidTaskEnum.BOUNTY_COMMISSION.value.value / XxxEnum.A.value
    m = re.match(r"^(\w+)\.(\w+)(?:\.value(?:\.value)?)?$", expr)
    if m and m.group(1) in enums:
        member = m.group(2)
        items = enums[m.group(1)]
        # 枚举成员名 -> 值：再看文件里 NAME = ConfigItem(...) 的对应
        return None, False                     # 成员名映射由调用方另行处理
    try:
        val = ast.literal_eval(expr)
        return val, True
    except Exception:  # noqa: BLE001
        return None, False


def _enum_member_value(text, enum_name, member):
    """从源码里取 EnumName.MEMBER 对应的 ConfigItem 值。"""
    m = re.search(r"^class\s+%s\s*\([^)]*\)\s*:(.*?)(?=^class\s|\Z)" % re.escape(enum_name),
                  text, re.M | re.S)
    if not m:
        return None
    mm = re.search(r"^\s+%s\s*=\s*ConfigItem\(\s*'([^']*)'" % re.escape(member), m.group(1), re.M)
    return mm.group(1) if mm else None


def _ann_type(ann):
    ann = (ann or "").strip().lower()
    if ann in ("int", "float"):
        return ann
    if ann in ("bool",):
        return "bool"
    if ann in ("str",):
        return "str"
    if ann.startswith(("list", "dict")):
        return "list"
    return ""


# --------------------------------------------------------------------------- 主解析
def _scan():
    if _CACHE.get("apps"):
        return _CACHE["apps"]
    apps = {}
    if not SRC.is_dir():
        _CACHE["apps"] = apps
        return apps

    for py in sorted(SRC.rglob("*_config.py")):
        s = str(py)
        if "__pycache__" in s or ".venv" in s:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        enums = _enums(text)
        app_id = _app_id_of(py, text)
        if not app_id:
            continue
        keys = []
        for m in _RE_PROP.finditer(text):
            prop, ann, doc, key, dexpr = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            doc_txt = ""
            if doc:
                for line in doc.splitlines():
                    line = line.strip().strip('"').strip("'").strip()
                    if line and not line.startswith("#"):
                        doc_txt = line
                        break
            # 默认值
            default, ok, opts = None, False, None
            if dexpr:
                dexpr2 = dexpr.strip()
                em = re.match(r"^(\w+)\.(\w+)(?:\.value(?:\.value)?)?$", dexpr2)
                if em and em.group(1) in enums:
                    default = _enum_member_value(text, em.group(1), em.group(2))
                    opts = enums[em.group(1)]
                    ok = default is not None
                else:
                    default, ok = _resolve_default(dexpr2, enums)
            if not ok:
                continue
            if isinstance(default, (dict, list)):
                continue                       # 复杂结构不加进 schema（避免空表误导）
            if isinstance(default, str) and not default:
                continue
            # 字符串默认值恰好等于某个枚举的取值 -> 该字段是下拉
            if opts is None and isinstance(default, str):
                for items in enums.values():
                    if any(it["value"] == default for it in items):
                        opts = items
                        break
            keys.append({"key": key, "prop": prop, "type": _ann_type(ann) or _type_of(default),
                         "default": default, "help": doc_txt, "options": opts})
        if not keys:
            continue
        cur = apps.get(app_id)
        if cur:
            have = {k["key"] for k in cur["keys"]}
            cur["keys"].extend(k for k in keys if k["key"] not in have)
        else:
            apps[app_id] = {"id": app_id, "src": str(py.relative_to(BASE)).replace("\\", "/"),
                            "keys": keys}
    _CACHE["apps"] = apps
    return apps


def _type_of(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "str"


# --------------------------------------------------------------------------- 对外
_APP_LABELS = {
    "charge_plan": "体力刷本", "daily_signin": "每日签到", "intel_board": "情报板",
    "life_on_line": "生活在线（咖啡店/刮刮卡）", "lost_void": "零号空洞·迷失之地",
    "notorious_hunt": "恶名狩猎", "withered_domain": "零号空洞·枯萎之都",
    "shiyu_defense": "式舆防卫战", "random_play": "随机游玩", "coffee": "咖啡店",
    "redemption_code": "兑换码", "city_fund": "丽都周薪", "ridu_weekly": "丽都周常",
    "engagement_reward": "活跃度奖励", "suibian_temple": "随便观", "world_patrol": "大世界巡查",
    "drive_disc_dismantle": "驱动盘分解", "hollow_zero": "零号空洞", "commission_assistant": "委托助手",
    "battle_assistant": "战斗助手", "email_app": "邮件", "trigrams_collection": "卦象收集",
    "scratch_card": "刮刮卡", "hollow_zero_challenge": "零号空洞挑战",
}


def apps():
    return _scan()


def app_label(app_id):
    a = _scan().get(app_id)
    if not a:
        return _APP_LABELS.get(app_id, app_id)
    return _APP_LABELS.get(app_id, app_id)


def schema(app_id):
    a = _scan().get(app_id)
    if not a:
        return {}
    return {k["key"]: k["default"] for k in a["keys"]}


def keys(app_id):
    a = _scan().get(app_id)
    return a["keys"] if a else []



_KEY_LABELS = {
    "after_done": "结束后执行", "artifact_priority_new": "驱动盘优先保留",
    "auto_battle": "自动战斗", "auto_battle_config": "自动战斗配置", "auto_battle_switch": "自动战斗开关",
    "auto_fetch_gh_proxy_url": "自动获取 GitHub 代理", "auto_manage_enabled": "自动管理",
    "auto_ultimate_enabled": "自动终结技", "auto_update_code": "自动更新代码",
    "background_gamepad_type": "后台手柄类型", "background_mode": "后台模式", "background_type": "后台类型",
    "boo_box_purchase_enabled": "购买邦布券", "buy_only_priority": "只买优先级",
    "buy_only_priority_1": "只买优先级 1", "buy_only_priority_2": "只买优先级 2",
    "card_num": "卡片数量", "challenge_config": "挑战配置", "challenge_way": "挑战方式",
    "chase_new_mode": "追新模式", "choose_team_by_priority": "按优先级选队", "choose_way": "选择方式",
    "copy_screenshot": "复制截图", "craft_drag_times": "制造拖动次数",
    "critical_max_node_idx": "关键节点上限", "custom_banner": "自定义横幅",
    "custom_git_branch": "自定义分支", "custom_theme_color": "自定义主题色",
    "daily_plan_times": "每日计划次数", "daily_reset_plan_times": "每日重置计划次数",
    "dialog_click_interval": "对话点击间隔", "dialog_option": "对话选项",
    "dismantle_abandon": "分解时放弃", "dismantle_level": "分解等级",
    "dodge_assistant_config": "闪避助手配置", "dodge_config": "闪避配置",
    "dodge_detect": "闪避识别", "dodge_switch": "闪避开关", "double_reward": "双倍奖励",
    "ds4_key_press_time": "手柄按键时长", "enable_notify": "开启通知", "enabled": "启用",
    "exp_grind_mode": "刷满经验模式", "extra_exit": "额外退出条件", "extra_task": "额外任务",
    "flash_classifier_gpu": "闪光分类器用 GPU", "force_update": "强制更新",
    "frequency_second": "频率（秒）", "full_screen": "全屏", "game_language": "游戏语言",
    "game_region": "区服", "gamepad_turn_speed": "手柄转向速度", "git_remote": "仓库地址",
    "good_goods_purchase_enabled": "购买好东西", "hdr": "HDR",
    "hollow_zero_event_gpu": "空洞事件识别用 GPU", "instance_run": "实例运行",
    "investigation_strategy": "调查策略", "is_debug": "调试模式", "is_first_run": "首次运行",
    "key_debug": "调试热键", "key_save": "保存热键", "key_screenshot": "截图热键",
    "key_start_running": "开始热键", "key_stop_running": "停止热键",
    "launch_argument": "启动参数", "length_second": "时长（秒）", "loop": "循环",
    "lost_void_det_gpu": "迷失之地识别用 GPU", "manually_choose_agent": "手动选代理人",
    "mini_map_angle_detect": "小地图角度识别", "mission_name": "副本/任务名称",
    "monitor": "显示器", "mouse_flash_duration": "鼠标闪光时长", "ocr_use_gpu": "OCR 用 GPU",
    "operation_template": "操作模板", "path_finding": "寻路", "pause_in_background": "后台时暂停",
    "pawnshop_crest_enabled": "当铺：徽章", "pawnshop_crest_unlimited_denny_enabled": "当铺：徽章换无限丁尼",
    "pawnshop_omnicoin_enabled": "当铺：全息币", "period_buff_no": "周期 buff 编号",
    "platform": "平台", "popup_window": "弹窗", "predefined_team_idx": "预备编队序号",
    "proxy_type": "代理类型", "repeat_enabled": "重复执行", "restore_charge": "发电站充电方式",
    "run_charge_plan_afterwards": "结束后跑体力计划", "screen_size": "分辨率",
    "screenshot_before_key": "按键前截图", "screenshot_interval": "截图间隔",
    "screenshot_method": "截图方式", "selected_sign": "签到商店", "send_image": "发送截图",
    "skip_plan": "跳过计划", "sleep_after_empty_screen": "空画面后等待",
    "store_blood": "存储电量", "store_blood_min": "存储电量下限", "store_gold": "存储金币",
    "story_mode": "剧情模式", "theme": "主题", "title": "标题", "type_input_way": "输入方式",
    "yum_cha_sin": "饮茶先（随便观）", "yum_cha_sin_period_refresh": "饮茶先按周期刷新",
    "boo_box_purchase_enabled_2": "购买邦布券（第二处）",
}
for _i in range(1, 8):
    _KEY_LABELS["day_coffee_%d" % _i] = "周%s喝的咖啡" % "一二三四五六日"[_i - 1]

def labels(app_id):
    """({key: 中文名}, {key: 中文说明})。中文名来自内置表，说明来自源码 docstring。"""
    a = _scan().get(app_id)
    if not a:
        return {}, {}
    return ({k["key"]: _KEY_LABELS[k["key"]] for k in a["keys"] if k["key"] in _KEY_LABELS},
            {k["key"]: k["help"] for k in a["keys"] if k["help"]})



def options(app_id):
    """{key: {"ui": "select"|"auto", "options": [...]}}"""
    a = _scan().get(app_id)
    if not a:
        return {}
    out = {}
    for k in a["keys"]:
        opts = k.get("options")
        if opts:
            out[k["key"]] = {"ui": "select", "options": opt_list(opts),
                             "opt_note": "来自 OneDragon 源码里的枚举"}
        elif k["key"] == "auto_battle_config":
            out[k["key"]] = {"ui": "select", "options": AUTO_BATTLE(),
                             "opt_note": "OneDragon 的自动战斗配置（config/auto_battle/*.yml）"}
    return out


def AUTO_BATTLE():
    names = set()
    for d in (OD / "config" / "auto_battle", OD / "config" / "01" / "one_dragon" / "auto_battle"):
        if not d.is_dir():
            continue
        for p in d.glob("*.yml"):
            n = p.name
            for suf in (".sample.yml", ".merged.yml", ".yml"):
                if n.endswith(suf):
                    n = n[: -len(suf)]
                    break
            if n:
                names.add(n)
    lst = sorted(names)
    if "全配队通用" in lst:
        lst.remove("全配队通用")
        lst.insert(0, "全配队通用")
    return [{"value": n, "label": n} for n in lst]


def opt_list(items):
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append({"value": it.get("value"), "label": it.get("label") or str(it.get("value"))})
        else:
            out.append({"value": it, "label": str(it)})
    return out


def yml_rel(app_id):
    return "config/01/one_dragon/%s.yml" % app_id


def summary():
    a = _scan()
    return {k: {"label": _APP_LABELS.get(k, k), "keys": len(v["keys"]),
                "selects": sum(1 for x in v["keys"] if x.get("options"))}
            for k, v in sorted(a.items())}


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), ensure_ascii=False, indent=1))
