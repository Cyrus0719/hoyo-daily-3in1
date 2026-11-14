# -*- coding: utf-8 -*-
"""配置中心 · 下拉选项数据源。

原则：**所有选项都从本机已装的上游程序里现读**，不硬编码猜（上游加新副本、换新策略，这里自动跟着变）。
读不到就返回 None，前端退化成自由输入 —— 永远不让界面因为缺数据而崩。

数据源
  原神   秘境/国家/地区 <- tools/BetterGI/BetterGI/GameTask/AutoTrackPath/Assets/tp.json
         战斗策略名     <- tools/BetterGI/BetterGI/User/AutoFight/**/*.txt 的文件名
         首领名         <- tools/BetterGI/BetterGI/GameTask/AutoBoss/Assets/Pathing/*.json 的文件名
         队伍名         <- daily.json + config.json 里出现过的队伍名
  崩铁   枚举           <- tools/March7thAssistant/config.yaml 行内注释「可选值：…」
         副本名         <- tools/March7thAssistant/assets/config/instance_names.json
  绝区零 体力计划分类   <- OneDragon-ref/assets/game_data/compendium_data.yml
         枚举           <- OneDragon 源码里的 ConfigItem 常量

结果缓存 30 秒（配置文件改了不用重启服务）。
"""
import json
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BG = BASE / "tools" / "BetterGI" / "BetterGI"
M7A = BASE / "tools" / "March7thAssistant"
OD = BASE / "OneDragon-ref"

_DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_CACHE = {}


def _cached(key, fn, ttl=30):
    import time
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:  # noqa: BLE001  上游没装/文件不在，都不要影响界面
        val = None
    _CACHE[key] = (now, val)
    return val


def clear_cache():
    _CACHE.clear()


# --------------------------------------------------------------------------- 崩铁字段中文名
# March7th 的 assets/config/config.example.yaml 每个键后面都写了中文注释（上游自己写的），
# 直接拿它当字段名和说明 —— 323 个键全部有中文，不用手写白名单。
_M7A_EXAMPLE = M7A / "assets" / "config" / "config.example.yaml"
_RE_YAML_KV = re.compile(r"^(\s*)([A-Za-z_][\w]*):(.*)$")


def _m7a_comment_meta():
    """({key: 中文名}, {key: 说明})，从 config.example.yaml 的行内注释里取。"""
    labels, helps = {}, {}
    try:
        text = _M7A_EXAMPLE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return labels, helps
    for line in text.splitlines():
        m = _RE_YAML_KV.match(line)
        if not m:
            continue
        key, rest = m.group(2), m.group(3)
        if "#" not in rest:
            continue
        cmt = rest.split("#", 1)[1].strip()
        if not cmt:
            continue
        helps[key] = cmt
        lab = re.split(r"[。；;]|，?可选值|，?取值范围|，?默认", cmt)[0].strip(" ，,。")
        if not lab:
            lab = cmt
        if len(lab) > 26:
            lab = re.split(r"[，,]", lab)[0][:26]
        labels[key] = lab
    return labels, helps


def m7a_key_meta():
    """带缓存的 ({key: 中文名}, {key: 说明})。"""
    return _cached("m7a_key_meta", _m7a_comment_meta, ttl=300) or ({}, {})


# --------------------------------------------------------------------------- 原神
_DOMAIN_GROUPS = [
    ("BlessDomain", "圣遗物秘境"),
    ("MasteryDomain", "天赋秘境"),
    ("ForgeryDomain", "武器秘境"),
    ("OneTimeDomain", "一次性秘境"),
    ("TrounceDomain", "周本"),
]


def _load_tp():
    p = BG / "GameTask" / "AutoTrackPath" / "Assets" / "tp.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def genshin_points():
    """{type: [{name, country, area}]}，只取副本类点位（去重保序）。"""
    data = _load_tp()
    out = {}
    for scene in data.get("data") or []:
        for pt in scene.get("points") or []:
            t = pt.get("type")
            name = (pt.get("name") or "").strip()
            if not t or not name:
                continue
            bucket = out.setdefault(t, [])
            if any(x["name"] == name for x in bucket):
                continue
            areas = [str(a).strip() for a in (pt.get("areas") or []) if str(a).strip()]
            bucket.append({"name": name, "country": (pt.get("country") or "").strip(),
                           "area": "·".join(areas[:2])})
    return out


def genshin_domains():
    """分组下拉：按秘境类型分组，项是 {value: 名字, label: 名字（国家·地区）}。"""
    pts = genshin_points()
    groups = []
    for type_key, label in _DOMAIN_GROUPS:
        items = pts.get(type_key) or []
        if not items:
            continue
        groups.append({"group": label, "items": [
            {"value": x["name"], "label": x["name"] + ("（%s·%s）" % (x["country"], x["area"]) if x["country"] else "")}
            for x in items]})
    return groups or None


def genshin_domain_names():
    pts = genshin_points()
    names = []
    for type_key, _label in _DOMAIN_GROUPS:
        for x in pts.get(type_key) or []:
            if x["name"] not in names:
                names.append(x["name"])
    return names or None


def genshin_countries():
    pts = genshin_points()
    seen = []
    for bucket in pts.values():
        for x in bucket:
            c = x["country"]
            if c and c not in seen:
                seen.append(c)
    return seen or None


def genshin_strategies():
    """战斗策略 = User/AutoFight 下的脚本文件名（BetterGI 就是这么认的）。"""
    names = ["根据队伍自动选择"]
    root = BG / "User" / "AutoFight"
    if root.is_dir():
        for p in sorted(root.rglob("*.txt")):
            stem = p.stem.strip()
            if stem and stem not in names:
                names.append(stem)
    return names


# 首领寻路资源里有同一只怪的多个变体文件（"歌裴莉娅的葬送战斗后快速"、"蕴光月守宫键鼠"…），
# 下拉里只该出现一只怪一次，所以去掉这些后缀再按顺序去重。
_BOSS_SUFFIXES = ("战斗后快速", "战斗后", "强制传送", "快速传送", "键鼠", "手柄", "前往路线", "前往", "_pathing")


def genshin_bosses():
    root = BG / "GameTask" / "AutoBoss" / "Assets" / "Pathing"
    if not root.is_dir():
        return None
    names = []
    for p in sorted(root.glob("*.json")):
        stem = p.stem.strip()
        changed = True
        while changed:
            changed = False
            for suffix in _BOSS_SUFFIXES:
                if stem.endswith(suffix) and len(stem) > len(suffix):
                    stem = stem[: -len(suffix)].strip()
                    changed = True
        if stem and stem not in names:
            names.append(stem)
    return names or None


def genshin_teams():
    """收集 daily.json / config.json 里出现过的队伍名（BetterGI 没有队伍清单文件）。"""
    names = []

    def add(v):
        if isinstance(v, str):
            v = v.strip()
            if v and v not in names:
                names.append(v)
        elif isinstance(v, list):
            for x in v:
                add(x)

    try:
        d = json.load(open(BG / "User" / "OneDragon" / "daily.json", encoding="utf-8"))
        # PartyName / DailyRewardPartyName / AutoBossTeamName / Monday~Sunday PartyName 全都收
        for k, v in d.items():
            if k.endswith(("PartyName", "TeamName")) or k in ("team", "friendshipTeam"):
                add(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        c = json.load(open(BG / "User" / "config.json", encoding="utf-8"))
        for sec, keys in (("autoDomainConfig", ("partyName",)),
                          ("autoLeyLineOutcropConfig", ("team", "friendshipTeam")),
                          ("autoStygianOnslaughtConfig", ("fightTeamName",)),
                          ("autoBossConfig", ("teamName",)),
                          ("autoFightConfig", ("teamNames", "kazuhaPartyName"))):
            blk = c.get(sec) or {}
            for k in keys:
                add(blk.get(k))
    except Exception:  # noqa: BLE001
        pass
    try:
        import yaml
        cfg = yaml.safe_load(open(BASE / "config" / "daily_config.yaml", encoding="utf-8")) or {}
        add(((cfg.get("games") or {}).get("genshin") or {}).get("party_name"))
    except Exception:  # noqa: BLE001
        pass
    return names or None


GENSHIN_LEYLINES = ["启示之花", "藏金之花"]
GENSHIN_POT_TP = ["地图传送", "尘歌壶道具"]
GENSHIN_COMPLETION = ["关闭游戏和软件", "关闭游戏", "关闭软件", "什么都不做"]


# --------------------------------------------------------------------------- 崩铁
def _parse_comment_options(comment):
    """从 March7th 的行内注释里抽出可选值，例如
       '# 可选值：拟造花萼（金）、拟造花萼（赤）、凝滞虚影。'  -> ['拟造花萼（金）', ...]
       只认「可选值 / 可选范围 + 冒号」这种明确写法，注释里顺口提一句『可选』不算。"""
    if not comment:
        return None
    m = re.search(r"(?:可选值|可选范围|可选参数)\s*(?:/\s*[^:：]*)?[:：]", comment)
    if not m:
        # 有的注释写成「可选 "源码"（source）或 "集成"（exe）」，没有冒号
        if re.search(r'可选\s*[\"“]', comment):
            body0 = comment[re.search(r'可选\s*[\"“]', comment).start():]
            paren_en0 = re.findall(r"[（(]([A-Za-z][A-Za-z0-9_\-]*)[）)]", body0)
            if len(paren_en0) >= 2:
                return paren_en0
        return None
    body = comment[m.end():]
    body = re.split(r"[。\n]", body)[0].strip(" 　")
    if not body:
        return None
    # 1) 括号里是全英文的（如 （Jarilo-VI））→ 用括号内容（配置里存的是英文码）
    paren_en = re.findall(r"[（(]([A-Za-z][A-Za-z0-9_\-]*)[）)]", body)
    if len(paren_en) >= 2:
        return paren_en
    # 2) 引号里的
    quoted = re.findall(r'"([^"]+)"', body) + re.findall(r"“([^”]+)”", body)
    if len(quoted) >= 2:
        tokens = quoted
    elif "、" in body:                      # 顿号优先，逗号常出现在括号注解里
        tokens = body.split("、")
    elif "/" in body:
        tokens = body.split("/")
    elif "," in body or "，" in body:
        tokens = re.split(r"[,，]", body)
    else:
        return None                          # 没有分隔符，不是枚举
    out = []
    for t in tokens:
        t = t.strip().strip("[]\"'“”，,。 ")
        for part in re.split(r"或", t):
            part = part.strip().strip("[]\"'“”，,。 ")
            if not part:
                continue
            # 结尾括号是注解（"default（默认，疾跑）"）才去掉；是名字（"拟造花萼（金）"）就留着
            if re.search(r"[A-Za-z]", part):
                part = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", part).strip()
            if part and part not in out and len(part) <= 30:
                out.append(part)
    return out if len(out) >= 2 else None


def m7a_enums():
    """{键名: [可选值]} —— 直接从 config.yaml 的注释里解析。"""
    path = M7A / "config.yaml"
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#") or "#" not in s or ":" not in s:
            continue
        head, _, comment = s.partition("#")
        if ":" not in head:
            continue
        key = head.split(":", 1)[0].strip()
        if not key or " " in key:
            continue
        opts = _parse_comment_options(comment)
        if opts:
            out[key] = opts
    return out


def m7a_instance_names():
    p = M7A / "assets" / "config" / "instance_names.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def m7a_drops():
    """{副本类型: {副本名: [掉落物名]}} —— 三月七自带的掉落表，用来在副本后面提示奖励。"""
    p = M7A / "assets" / "config" / "instance_drops.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# 崩铁副本的开放规则（按类型，不猜具体副本）
_M7A_INSTANCE_RULES = {
    "拟造花萼（金）": "常驻开放 · 每次 10 开拓力（或 1 次双倍）",
    "拟造花萼（赤）": "常驻开放 · 每次 10 开拓力",
    "凝滞虚影": "常驻开放 · 每次 30 开拓力",
    "侵蚀隧洞": "常驻开放 · 每次 40 开拓力",
    "饰品提取": "常驻开放 · 每次 40 开拓力",
    "历战余响": "每周 1 次免费奖励 · 每次 30 开拓力 · 周一 04:00 重置",
}


def m7a_instance_detail(type_name, inst_name):
    """给某个副本拼一句详情：奖励 + 开放规则。"""
    type_name = str(type_name or "")
    inst_name = str(inst_name or "")
    drops = (_cached("m7a_drops", m7a_drops) or {}).get(type_name) or {}
    items = drops.get(inst_name) or []
    parts = []
    if items:
        parts.append("奖励：" + "、".join(items[:6]))
    rule = _M7A_INSTANCE_RULES.get(type_name)
    if rule:
        parts.append(rule)
    return " · ".join(parts)


# 崩铁：三月七的 config.yaml 是「功能前缀」命名的，这里把前缀翻成中文并排好顺序，
# 前端按这个顺序给每个功能一张卡（开关 + 这项的全部细节项），不再手写白名单。
_M7A_FEATURES = (
    ("power", "清体力：体力与燃料", "后备开拓力、燃料、沉浸器合成都在这一组。"),
    ("build_target", "培养目标", "打开后三月七按你选的培养方案自动决定刷哪个副本。"),
    ("instance", "副本与队伍", "打哪些副本、每次打几次、用第几队、打之前是否先传送。"),
    ("daily", "每日实训", "实训任务、姬子试用、记忆一。"),
    ("reward", "奖励领取", "邮件、支援、委托、通行证、兑换码、成就、短信。"),
    ("universe", "模拟宇宙", "启动方式（源码/集成）、差分宇宙还是模拟宇宙、次数、超时、GPU 加速。"),
    ("divergent", "差分宇宙", "差分宇宙的类型、队伍，以及每日/每周完成记录。"),
    ("weekly", "差分宇宙（周常）", "每周的差分宇宙奖励、关卡、稳定模式。"),
    ("currencywars", "货币战争", "模式（标准/超频）、职级难度、策略、速通、遇到特殊词条是否重开。"),
    ("echo_of_war", "历战余响", "每周一次的历战余响，以及从周几开始算。"),
    ("forgottenhall", "忘却之庭（混沌回忆）", "关卡与两队配置。"),
    ("purefiction", "虚构叙事", "关卡与两队配置。"),
    ("apocalyptic", "末日幻影", "关卡与两队配置。"),
    ("fight", "战斗细节", "战斗中买药、买零食、切队伍、地图版本。"),
    ("activity", "活动", "巡星之礼、磐岩之隙、异界 realm、每日签到。"),
    ("asset", "养成材料", "自塑尘脂、星轨专票/通票、光锥叠影、余烬兑换。"),
    ("borrow", "借用支援", "借用好友的支援角色，以及借用次数。"),
    ("merge", "沉浸器合成", "合成沉浸器与合成上限。"),
    ("autoplot", "自动剧情", "跳过、点击、战斗检测、手机检测。"),
    ("cloud_game", "云游戏", "云游戏开关、全屏、付费时长、排队上限。"),
    ("browser", "浏览器（网页活动）", "用哪个浏览器、无头模式、缩放、下载镜像。"),
    ("launcher", "启动器", "启动器路径与进程名。"),
    ("game", "游戏进程", "游戏路径、窗口标题、进程名、启动超时。"),
    ("update", "游戏更新", "更新方式、预下载、全量更新、下载代理。"),
    ("auto", "自动化开关", "自动战斗检测、自动改分辨率、自动找游戏路径、自动更新。"),
    ("use", "体力使用", "用后备开拓力、用燃料、后台截图。"),
    ("hotkey", "快捷键", "秘技、地图、传送、自动战斗、停止任务的按键。"),
    ("window", "窗口", "窗口位置、大小、是否记忆。"),
    ("log", "日志", "日志级别、保留天数、悬浮窗。"),
    ("scheduled", "定时运行", "任务链、冲突处理、失败是否继续。"),
    ("notify", "通知", "邮件、Telegram、Matrix、Bark、Webhook 等全部通知渠道。"),
    ("telemetry", "遥测上报", "匿名统计（可以关）。"),
    ("genshin", "帧率解锁", "原神/星铁的帧率解锁程序路径。"),
)

# 名字前缀和功能对不上的几个键，显式归到对应功能里
_M7A_FEATURE_EXTRA = {
    "build_target": ("break_down_level_four_relicset",),
    "instance": ("tp_before_instance", "calyx_golden_preference"),
    "game": ("start_game_timeout",),
    "auto": ("auto_update",),
    "reward": ("home_cards",),
}


def m7a_features():
    """[{prefix, name, desc, keys:[...]}] —— 每个功能一项，keys 是它名下的全部键（按 config 顺序）。
    前端拿它给崩铁页生成「每个功能一张卡」，所以没被白名单写死的项也不会再漏。"""
    keys_in_file = []
    path = M7A / "config.yaml"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            k = s.split(":", 1)[0].strip()
            if k and " " not in k and k not in keys_in_file:
                keys_in_file.append(k)
    taken = {}
    for prefix, _nm, _ds in _M7A_FEATURES:
        for k in _M7A_FEATURE_EXTRA.get(prefix, ()):
            taken[k] = prefix
    out = []
    for prefix, name, desc in _M7A_FEATURES:
        keys = []
        for k in keys_in_file:
            if taken.get(k, prefix) == prefix and (k == prefix or k.startswith(prefix + "_")):
                keys.append(k)
        for k in _M7A_FEATURE_EXTRA.get(prefix, ()):
            if k not in keys:
                keys.append(k)
        if keys:
            out.append({"prefix": prefix, "name": name, "desc": desc, "keys": keys})
    return out

# --------------------------------------------------------------------------- 绝区零
def zzz_compendium():
    """[{tab, category, mission_types:[{name, missions:[{value,label}]}]}]"""
    p = OD / "assets" / "game_data" / "compendium_data.yml"
    if not p.is_file():
        return None
    import yaml
    data = yaml.safe_load(open(p, encoding="utf-8")) or []
    tabs = {}
    for tab in data:
        tn = tab.get("tab_name")
        cats = []
        for cat in tab.get("category_list") or []:
            mts = []
            for mt in cat.get("mission_type_list") or []:
                missions = []
                for m in mt.get("mission_list") or []:
                    name = m.get("mission_name")
                    disp = m.get("mission_name_display") or name
                    missions.append({"value": name, "label": "%s（%s）" % (name, disp) if disp != name else name})
                mts.append({"name": mt.get("mission_type_name"), "missions": missions})
            cats.append({"name": cat.get("category_name"), "mission_types": mts})
        tabs[tn] = cats
    return tabs


ZZZ_RESTORE = ["不使用", "使用储蓄电量", "使用以太电池", "同时使用储蓄电量和以太电池"]
ZZZ_CARD_NUM = ["默认数量", "1张卡片", "2张卡片", "3张卡片", "4张卡片", "5张卡片"]
ZZZ_LEVELS = ["默认等级", "等级Lv.65", "等级Lv.60", "等级Lv.50", "等级Lv.40", "等级Lv.30"]


def zzz_apps():
    """一条龙里每个 app 的中文名（从上游 *_const.py 的 APP_ID/APP_NAME 现读）。"""
    root = OD / "src" / "zzz_od" / "application"
    out = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*_const.py"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        aid = re.search(r"APP_ID\s*=\s*[\'\"]([^\'\"]+)", txt)
        anm = re.search(r"APP_NAME\s*=\s*[\'\"]([^\'\"]+)", txt)
        if aid and anm:
            out[aid.group(1)] = anm.group(1)
    return out


def zzz_all_categories():
    """所有 tab 下的分类名（去重、保持上游顺序）。"""
    names = []
    for tab in (_cached("zzz_comp", zzz_compendium) or {}).values():
        for cat in tab:
            n = cat.get("name")
            if n and n not in names:
                names.append(n)
    return names


def zzz_all_mission_types():
    names = []
    for tab in (_cached("zzz_comp", zzz_compendium) or {}).values():
        for cat in tab:
            for mt in cat.get("mission_types") or []:
                n = mt.get("name")
                if n and n not in names:
                    names.append(n)
    return names


def zzz_auto_battle_configs():
    """绝区零自动战斗配置：上游内置的在 config/auto_battle/*.sample.yml，
    用户自己新增/覆盖的在 config/01/one_dragon/auto_battle/*.yml。"""
    names = []
    for d, pat in ((OD / "config" / "auto_battle", "*.sample.yml"),
                   (OD / "config" / "auto_battle", "*.yml"),
                   (OD / "config" / "01" / "one_dragon" / "auto_battle", "*.yml")):
        if not d.is_dir():
            continue
        for p in sorted(d.glob(pat)):
            stem = p.name
            for suf in (".sample.yml", ".merged.yml", ".yml"):
                if stem.endswith(suf):
                    stem = stem[:-len(suf)]
                    break
            if stem and stem not in names:
                names.append(stem)
    if "全配队通用" in names:
        names.remove("全配队通用")
        names.insert(0, "全配队通用")
    return names or ["全配队通用"]


_OD_SKIP_APPS = {"config", "envs", "push", "operation_debug", "screenshot_helper", "model",
                "basic_game", "basic_model", "custom", "game_account", "notify", "one_dragon",
                "standalone_app", "pip", "charge_plan"}


def zzz_app_configs():
    """{app_id: 配置文件的 fid} —— OneDragon 每个 app 的自有配置就是 config/01/one_dragon/<app_id>.yml。
    文件还没生成的（上游第一次改这项才写）也列出来，界面照样能改。"""
    d = OD / "config" / "01" / "one_dragon"
    out = {}
    for p in sorted(d.glob("*.yml")) if d.is_dir() else []:
        if p.stem.startswith("_") or p.stem in _OD_SKIP_APPS:
            continue
        try:
            rel = p.relative_to(BASE).as_posix()
        except ValueError:
            continue
        out[p.stem] = "auto:" + rel
    try:
        try:
            from . import od_schema as ODS
        except ImportError:  # noqa: BLE001
            import od_schema as ODS
        for aid in ODS.apps():
            if aid in _OD_SKIP_APPS or aid in out:
                continue
            out[aid] = "auto:OneDragon-ref/" + ODS.yml_rel(aid)
    except Exception:  # noqa: BLE001
        pass
    return out


def zzz_app_labels():
    """{app_id: 中文名}，给「每项功能的详细设置」当标题。"""
    try:
        try:
            from . import od_schema as ODS
        except ImportError:  # noqa: BLE001
            import od_schema as ODS
        return {aid: ODS.app_label(aid) for aid in ODS.apps()}
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------- 给某个配置字段找选项
def _opt(kind, options, note=""):
    # 注意：键名用 ui 而不是 kind —— registry 的节点本来有 kind（field/group），不能被覆盖。
    return {"ui": kind, "options": options, "opt_note": note}


def for_node(fid, path, name, value):
    """给 registry 的树节点挂 options：返回 {kind, options} 或 None。"""
    path = str(path or "")
    name = str(name or "")

    if fid in ("bg_daily", "bg_main"):
        if name in ("PartyName", "DailyRewardPartyName", "AutoBossTeamName") or "teamName" in name \
                or name in ("team", "friendshipTeam", "fightTeamName", "kazuhaPartyName"):
            teams = _cached("gs_teams", genshin_teams)
            return _opt("combo", teams, "填游戏里队伍页显示的名字") if teams else None
        if name in ("DomainName", "domainName"):
            names = _cached("gs_domains", genshin_domain_names)
            return _opt("combo", names, "必须是秘境全名") if names else None
        if name.endswith("Country") or name == "country":
            cs = _cached("gs_countries", genshin_countries)
            return _opt("select", cs, "地脉花/合成台/冒险家协会所在国家") if cs else None
        if name in ("LeyLineMondayType",) or re.match(r"^LeyLine\w+Type$", name) or name == "leyLineOutcropType":
            return _opt("select", GENSHIN_LEYLINES)
        if name == "SereniteaPotTpType":
            return _opt("select", GENSHIN_POT_TP)
        if name == "CompletionAction":
            return _opt("select", GENSHIN_COMPLETION)
        if name == "AutoBossName" or name == "bossName":
            bs = _cached("gs_bosses", genshin_bosses)
            return _opt("select", bs, "BetterGI 里已收录的周本/首领") if bs else None
        if name in ("strategyName", "AutoBossStrategyName") or name.endswith("StrategyName"):
            return _opt("select", _cached("gs_strat", genshin_strategies))
        if name == "onlyPickEliteDropsMode":
            return _opt("select", ["Closed", "Open"])
        return None

    if fid == "m7a":
        enums = _cached("m7a_enums", m7a_enums) or {}
        if name in enums:
            return _opt("select", enums[name])
        if name == "instance_type":
            names = _cached("m7a_instance_names", m7a_instance_names) or {}
            return _opt("select", list(names.keys()))
        # instance_names.<副本类型> = 具体副本名
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        parent_name = parent.rsplit(".", 1)[-1] if parent else ""
        names = _cached("m7a_instance_names", m7a_instance_names) or {}
        # 只认 instance_names.<副本类型> 这一层（name 就是类型）。
        # instance_names_challenge_count.<类型> 是次数，不能当副本名。
        key = ""
        if path.startswith("instance_names.") and "." not in path[len("instance_names."):]:
            key = name if name in names else ""
        if key:
            # instance_names.json 是 {副本名: 提示（奖励类型/角色）}，可选的副本名在键上
            opts = []
            for k, hint in (names[key] or {}).items():
                if not k or k == "无":
                    continue
                opts.append({"value": k, "label": ("%s（%s）" % (k, hint)) if hint and hint != "跳过" else k})
            return _opt("select", opts) if opts else None
        return None

    if str(fid).startswith("auto:OneDragon-ref/config/01/one_dragon/"):
        aid = str(fid).rsplit("/", 1)[-1].rsplit(".", 1)[0]
        try:
            from . import od_schema as ODS
        except ImportError:  # noqa: BLE001
            import od_schema as ODS
        o = ODS.options(aid).get(name)
        if o:
            return o
        return None

    if fid == "od_charge":
        if name == "restore_charge":
            return _opt("select", ZZZ_RESTORE)
        if name == "card_num":
            return _opt("select", ZZZ_CARD_NUM)
        if name == "level":
            return _opt("select", ZZZ_LEVELS)
        if name == "auto_battle_config":
            return _opt("select", _cached("zzz_ab", zzz_auto_battle_configs))
        if name == "tab_name":
            tabs = _cached("zzz_comp", zzz_compendium) or {}
            return _opt("select", list(tabs.keys())) if tabs else None
        if name == "category_name":
            return _opt("select", zzz_all_categories() or None)
        if name == "mission_type_name":
            return _opt("combo", zzz_all_mission_types() or None)
        return None

    return None


# 原神秘境的类型 → 开放规则 / 树脂消耗（tp.json 只有类型和位置，没有奖励数据，别编套装名）
_GS_DOMAIN_RULES = {
    "BlessDomain": ("圣遗物秘境", "每天开放 · 每次 20 树脂（浓缩树脂 40）"),
    "MasteryDomain": ("天赋培养素材", "按周几轮换（周一/周四、周二/周五、周三/周六，周日全开）· 每次 20 树脂"),
    "ForgeryDomain": ("武器突破素材", "按周几轮换（周一/周四、周二/周五、周三/周六，周日全开）· 每次 20 树脂"),
    "TrounceDomain": ("周本 / 首领", "每周 1 次领取奖励（30/60 树脂）· 周一 04:00 重置"),
    "OneTimeDomain": ("一次性秘境", "打完就不会再刷，日常自动化不需要它"),
}


def genshin_domain_meta():
    """{秘境名: {type, type_cn, country, areas, rule}} —— 给秘境名后面补详情用。"""
    pts = _cached("gs_points", genshin_points) or {}
    out = {}
    for type_key, items in pts.items():
        cn, rule = _GS_DOMAIN_RULES.get(type_key, ("", ""))
        if not cn:
            continue
        for x in items:
            name = x.get("name") or ""
            if not name:
                continue
            cur = out.setdefault(name, {"type": type_key, "type_cn": cn, "rule": rule,
                                        "country": x.get("country") or "", "areas": []})
            area = x.get("area") or ""
            if area and area not in cur["areas"]:
                cur["areas"].append(area)
    return out or None


def payload():
    """给前端一次性拿全部选项（原神/崩铁/绝区零页面用）。"""
    return {
        "genshin": {
            "domains": _cached("gs_domains", genshin_domains),
            "domain_names": _cached("gs_domains2", genshin_domain_names),
            "domain_meta": _cached("gs_domain_meta", genshin_domain_meta),
            "countries": _cached("gs_countries", genshin_countries),
            "teams": _cached("gs_teams", genshin_teams),
            "strategies": _cached("gs_strat", genshin_strategies),
            "bosses": _cached("gs_bosses", genshin_bosses),
            "leyline_types": GENSHIN_LEYLINES,
            "pot_tp": GENSHIN_POT_TP,
            "completion": GENSHIN_COMPLETION,
        },
        "starrail": {
            "enums": _cached("m7a_enums", m7a_enums) or {},
            "instance_names": _cached("m7a_instance_names", m7a_instance_names) or {},
            "drops": _cached("m7a_drops", m7a_drops) or {},
            "instance_rules": _M7A_INSTANCE_RULES,
            "features": _cached("m7a_features", m7a_features) or [],
        },
        "zzz": {
            "compendium": _cached("zzz_comp", zzz_compendium) or {},
            "restore_charge": ZZZ_RESTORE,
            "card_num": ZZZ_CARD_NUM,
            "levels": ZZZ_LEVELS,
            "auto_battle_configs": _cached("zzz_ab", zzz_auto_battle_configs),
            "apps": _cached("zzz_apps", zzz_apps) or {},
            "categories": zzz_all_categories(),
            "mission_types": zzz_all_mission_types(),
            "app_configs": _cached("zzz_appcfg", zzz_app_configs) or {},
            "app_labels": zzz_app_labels(),
        },
    }


if __name__ == "__main__":   # 自检：python config_center/options.py
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== 崩铁注释解析 ===")
    for k, v in (m7a_enums() or {}).items():
        print("  %-32s %s" % (k, v))
    print("=== 原神 ===")
    print("  国家:", genshin_countries())
    print("  秘境组数:", len(genshin_domains() or []), "秘境数:", len(genshin_domain_names() or []))
    print("  策略:", genshin_strategies())
    print("  首领:", (genshin_bosses() or [])[:8], "...共", len(genshin_bosses() or []))
    print("  队伍:", genshin_teams())
    print("=== 绝区零 ===")
    comp = zzz_compendium() or {}
    print("  tab:", list(comp.keys()))
    train = comp.get("训练") or []
    for c in train:
        print("   ", c["name"], "→", [m["name"] for m in c["mission_types"]][:6])