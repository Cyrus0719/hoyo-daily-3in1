# -*- coding: utf-8 -*-
"""配置中心 · 注册表 + 读写层。

把三个游戏的原生配置文件和我们自己的 daily_config.yaml 统一成 "文件 id -> 文件" 的对象：
  list_files()            列出所有可编辑文件
  build_tree(fid)         把文件内容变成前端可渲染的树（分组 + 字段）
  save_ops(fid, ops)      按 path 修改（set / add / del），自动备份 + 原子写入
  raw_read / raw_write    原始文本编辑（带语法校验，兜底一切没被表单覆盖的键）

写入策略：先备份到 config/backup/<fid>_<时间戳>.<ext>（每个文件保留最近 30 份），
        再写 .tmp，最后 os.replace 原子替换 —— 中途断电也不会把配置写坏。
YAML 优先用 ruamel.yaml 往返（保留注释和键顺序）；没装则退回 PyYAML。JSON 用标准库。
"""
import copy
import io
import json
import os
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE / "config" / "backup"
MAX_BACKUPS = 30

try:  # ruamel 能保留注释/顺序，改崩铁的 config.yaml 时非常关键
    from ruamel.yaml import YAML as _RuamelYAML

    _HAS_RUAMEL = True
except Exception:  # noqa: BLE001
    _HAS_RUAMEL = False
    import yaml as _pyyaml

try:  # 既支持 python -m config_center.server，也支持直接跑本文件
    from . import labels as L
    from . import options as OPT
    from . import od_schema as ODS
except ImportError:  # noqa: BLE001
    import labels as L
    import options as OPT
    import od_schema as ODS

# --------------------------------------------------------------------------- 注册表
BG = BASE / "tools" / "BetterGI" / "BetterGI"
M7A = BASE / "tools" / "March7thAssistant"
OD = BASE / "OneDragon-ref"

_SECRET_HINTS = ("password", "passwd", "pwd", "token", "secret", "cookie", "apikey",
                 "api_key", "sendkey", "cdk", "webhook", "smtp_username", "account")


_SYSTEM_FILES = {"env.yml", "model.yml", "project.yml", "repository.yml",
                 "standalone_app.yml", "_group.yml"}


def _entry(fid, label, path, fmt, game, group="", secret_hints=None, readonly=None, note="", special="",
           schema=None, order="", create_ok=False):
    return {
        "id": fid,
        "label": label,
        "path": Path(path),
        "fmt": fmt,
        "game": game,
        "group": group,
        "secret_hints": tuple(secret_hints or _SECRET_HINTS),
        "readonly": set(readonly or ()),
        "note": note,
        "special": special,
        "system": Path(path).name in _SYSTEM_FILES,
        # schema: 上游自带的默认配置示例。当前文件通常只写了改动过的键，
        # 用它补全后界面才能看到全部可配项（写回时仍保持稀疏，不把默认值固化进去）。
        "schema": Path(schema) if schema else None,
        # order: 该文件支持"任务顺序"编辑时的策略名
        "order": order,
        # create_ok: 文件还不存在也允许打开/保存（上游第一次改这项时才写文件）
        "create_ok": bool(create_ok),
    }


_BUILTIN = [
    _entry("ours", "总控配置", BASE / "config" / "daily_config.yaml", "yaml", "all",
           group="我们", note="调度时间、各游戏开关、目标列表都在这里"),
    _entry("accounts", "账号与密码", BASE / "config" / "accounts.yaml", "yaml", "all",
           group="我们", note="明文保存，别提交到 GitHub（已在 .gitignore 里）", special="accounts"),
    _entry("display", "屏幕与显示", BASE / "config" / "display_user.json", "json", "all",
           group="我们", note="跑完之后恢复成你自己玩的显示设置"),

    _entry("bg_main", "BetterGI 主配置", BG / "User" / "config.json", "json", "genshin",
           group="原神", note="BetterGI 自己的全部设置（含启动/战斗/秘境/截图/热键）"),
    _entry("bg_daily", "一条龙 · 每日任务", BG / "User" / "OneDragon" / "daily.json", "json", "genshin",
           group="原神", note="每天要跑哪些任务、打哪个秘境、地脉花怎么跑", special="genshin_daily",
           order="genshin_taskorder"),

    _entry("m7a", "三月七助手配置", M7A / "config.yaml", "yaml", "starrail",
           group="崩铁", note="崩铁的全部设置：清体力计划、培养目标、每日、活动、通知",
           schema=M7A / "assets" / "config" / "config.example.yaml"),

    _entry("od_game", "游戏与窗口", OD / "config" / "01" / "game.yml", "yaml", "zzz", group="绝区零"),
    _entry("od_account", "账号与登录", OD / "config" / "01" / "game_account.yml", "yaml", "zzz",
           group="绝区零", note="填了账号密码，掉登录时 OneDragon 能自动登回来"),
    _entry("od_charge", "清电量计划", OD / "config" / "01" / "one_dragon" / "charge_plan.yml", "yaml", "zzz",
           group="绝区零", note="绝区零真正执行的体力计划（我们 config 里的 zzz targets 不生效）",
           special="zzz_charge"),
    _entry("od_group", "一条龙总开关", OD / "config" / "01" / "one_dragon" / "_group.yml", "yaml", "zzz",
           group="绝区零", note="一条龙里哪些功能跑：邮件、体力刷本、恶名狩猎、周常、零号空洞…",
           order="zzz_applist"),
    _entry("od_notify", "通知设置", OD / "config" / "01" / "notify.yml", "yaml", "zzz", group="绝区零"),
    _entry("od_instance", "实例列表", OD / "config" / "one_dragon.yml", "yaml", "zzz", group="绝区零"),
    _entry("od_custom", "自定义配置", OD / "config" / "custom.yml", "yaml", "zzz", group="绝区零"),
]

_CACHE = {"files": None, "ts": 0.0}


def _discover():
    """自动发现没写死在注册表里的配置文件（一条龙方案、其它 yml），保证不遗漏。"""
    extra = []
    known = {str(e["path"].resolve()).lower() for e in _BUILTIN}
    patterns = [
        (BG / "User" / "OneDragon", "*.json", "genshin", "原神", "一条龙方案"),
        (OD / "config", "*.yml", "zzz", "绝区零", "配置"),
        (OD / "config" / "01", "*.yml", "zzz", "绝区零", "配置"),
        (OD / "config" / "01" / "one_dragon", "*.yml", "zzz", "绝区零", "配置"),
    ]
    for d, pat, game, gname, gtag in patterns:
        if not d.is_dir():
            continue
        for p in sorted(d.glob(pat)):
            if str(p.resolve()).lower() in known:
                continue
            if p.name.endswith((".sample.yml", ".merged.yml")):
                continue
            extra.append(_entry(
                "auto:" + str(p.relative_to(BASE)).replace(os.sep, "/"),
                p.stem, p, "yaml" if p.suffix == ".yml" else "json", game,
                group=gname, note=gtag,
            ))
    # 绝区零：源码里定义了设置、但文件还没生成的功能（config/01/one_dragon/<app_id>.yml）
    od_dir = OD / "config" / "01" / "one_dragon"
    _SKIP = {"config", "envs", "push", "operation_debug", "screenshot_helper", "model",
             "basic_game", "basic_model", "custom", "game_account", "notify", "one_dragon",
             "standalone_app", "pip", "charge_plan"}
    try:
        schema_apps = ODS.apps()
    except Exception:  # noqa: BLE001
        schema_apps = {}
    for aid in sorted(schema_apps):
        if aid in _SKIP:
            continue
        p = od_dir / (aid + ".yml")
        if str(p.resolve()).lower() in known:
            continue
        extra.append(_entry(
            "auto:" + str(p.relative_to(BASE)).replace(os.sep, "/"),
            ODS.app_label(aid), p, "yaml", "zzz", group="绝区零",
            note="这个功能还没生成配置文件，改了才会写出来", create_ok=True,
        ))
    return extra


def list_files(force=False):
    now = time.time()
    if not force and _CACHE["files"] is not None and now - _CACHE["ts"] < 3:
        return _CACHE["files"]
    files = _BUILTIN + _discover()
    out = []
    for e in files:
        p = e["path"]
        st = None
        try:
            st = p.stat()
        except OSError:
            pass
        out.append({
            "id": e["id"], "label": e["label"], "group": e["group"], "game": e["game"],
            "fmt": e["fmt"], "special": e["special"], "note": e["note"],
            "system": e.get("system", False),
            "rel": str(p.relative_to(BASE)).replace(os.sep, "/") if str(p).startswith(str(BASE)) else str(p),
            "exists": st is not None, "size": st.st_size if st else 0,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)) if st else "",
        })
    _CACHE["files"] = out
    _CACHE["ts"] = now
    return out


def get(fid):
    for e in _BUILTIN + _discover():
        if e["id"] == fid:
            return e
    raise KeyError("未知的配置文件: %s" % fid)


# --------------------------------------------------------------------------- 读写
def _read_text(p: Path) -> str:
    data = p.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def _yaml_loader():
    if _HAS_RUAMEL:
        y = _RuamelYAML()
        y.preserve_quotes = True
        y.width = 4096
        y.allow_unicode = True
        return y
    return None


def _load(meta, text):
    fmt = meta["fmt"]
    if fmt == "json":
        return json.loads(text)
    y = _yaml_loader()
    if y is not None:
        doc = y.load(text)
        return doc if doc is not None else {}
    return _pyyaml.safe_load(text) or {}


def _dump(meta, doc) -> str:
    if meta["fmt"] == "json":
        return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if _HAS_RUAMEL:
        y = _yaml_loader()
        buf = io.StringIO()
        y.dump(doc, buf)
        return buf.getvalue()
    return _pyyaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4096)


def load_raw(fid):
    """只读磁盘上的真实内容（不补默认值）。"""
    meta = get(fid)
    p = meta["path"]
    if not p.exists():
        if meta.get("create_ok"):        # 上游配置还没生成：当成空文件，保存时创建
            return meta, {}, ""
        raise FileNotFoundError(str(p))
    text = _read_text(p)
    doc = _load(meta, text)
    if doc is None and meta.get("create_ok"):
        doc = {}
    return meta, doc, text


_OD_APP_PREFIX = "auto:OneDragon-ref/config/01/one_dragon/"


def _od_app_id(fid):
    """auto:OneDragon-ref/config/01/one_dragon/<app_id>.yml -> app_id"""
    fid = str(fid or "")
    if not fid.startswith(_OD_APP_PREFIX):
        return ""
    return fid[len(_OD_APP_PREFIX):].rsplit(".", 1)[0]


def _schema_doc(meta):
    """读上游自带的默认配置示例（如三月七的 config.example.yaml）。

    绝区零每个功能没有示例文件，默认值写在源码里（@property + self.get('k', 默认)），
    这里改读 od_schema 解析出来的默认值表，效果一样：当前文件没写的键也能在界面看到。
    """
    sp = meta.get("schema")
    if not sp:
        aid = _od_app_id(meta.get("id"))
        if not aid:
            return None
        sch = ODS.schema(aid)
        return sch or None
    try:
        text = _read_text(Path(sp))
    except OSError:
        return None
    try:
        doc = _load({"fmt": meta["fmt"]}, text)
    except Exception:  # noqa: BLE001
        return None
    return doc if isinstance(doc, dict) else None


def _merge_defaults(cur, sch, path="", added=None):
    """把 schema 里有、当前文件里没有的键补进 cur，并把补进来的路径记到 added。

    只补"缺失"的键，已有值一律不动 —— 所以界面看到的是「当前值 + 上游默认值」，
    而写回时仍写回稀疏文件（不把默认值固化，上游以后改默认值还能跟着变）。
    """
    if added is None:
        added = set()
    if not isinstance(cur, dict) or not isinstance(sch, dict):
        return added
    for k, v in sch.items():
        p = (path + "." if path else "") + str(k)
        if k not in cur:
            cur[k] = copy.deepcopy(v)
            added.add(p)
        elif isinstance(cur[k], dict) and isinstance(v, dict):
            _merge_defaults(cur[k], v, p, added)
    return added


def load_doc(fid):
    """返回 (meta, doc, text)。doc = 当前值 + 上游默认值（schema 存在时）。

    meta["_defaults"] 里是"这些值来自默认值、文件里还没有"的路径，
    界面据此打上「默认」标记，用户一改就落盘。
    """
    meta, raw, text = load_raw(fid)
    sch = _schema_doc(meta)
    if not sch:
        return meta, raw, text
    merged = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    added = _merge_defaults(merged, sch)
    meta = dict(meta)
    meta["_defaults"] = sorted(added)
    aid = _od_app_id(fid)
    if aid:  # 源码里的中文 docstring 当字段说明、内置表当字段名
        klabels, helps = ODS.labels(aid)
        if helps:
            meta["_helps"] = dict(helps)
        if klabels:
            meta["_labels"] = dict(klabels)
    if meta.get("id") == "m7a":
        # 崩铁：上游 config.example.yaml 每个键都有中文注释，直接当字段名/说明
        lab, hlp = OPT.m7a_key_meta()
        labs = dict(meta.get("_labels") or {})
        hlps = dict(meta.get("_helps") or {})
        for k, v in lab.items():
            labs.setdefault(k, v)
        for k, v in hlp.items():
            hlps.setdefault(k, v)
        meta["_labels"], meta["_helps"] = labs, hlps
    return meta, merged, text


def _write_atomic(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(str(tmp), str(p))


def backup(meta) -> str:
    """备份当前文件内容，返回备份文件名（失败返回空串）。"""
    p = meta["path"]
    if not p.exists():
        return ""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = meta["id"].replace(":", "_").replace("/", "_")
    name = "%s_%s%s" % (safe, stamp, p.suffix)
    dst = BACKUP_DIR / name
    n = 1
    while dst.exists():
        dst = BACKUP_DIR / ("%s_%s_%d%s" % (safe, stamp, n, p.suffix))
        n += 1
    try:
        dst.write_bytes(p.read_bytes())
    except OSError:
        return ""
    _prune_backups(safe)
    return dst.name


def _prune_backups(safe_id: str):
    rows = sorted(BACKUP_DIR.glob(safe_id + "_*"), key=lambda x: x.stat().st_mtime, reverse=True)
    for old in rows[MAX_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(fid=None):
    if not BACKUP_DIR.is_dir():
        return []
    out = []
    for p in BACKUP_DIR.iterdir():
        if not p.is_file():
            continue
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    if fid:
        safe = fid.replace(":", "_").replace("/", "_")
        out = [x for x in out if x["name"].startswith(safe + "_")]
    return out[:200]


def restore_backup(fid, name):
    meta = get(fid)
    src = BACKUP_DIR / os.path.basename(name)
    if not src.is_file():
        raise FileNotFoundError("备份不存在: %s" % name)
    text = _read_text(src)
    _load(meta, text)  # 先校验能解析
    backup(meta)
    _write_atomic(meta["path"], text)
    return True


# --------------------------------------------------------------------------- path 工具
def _split(path):
    return [s for s in str(path).split(".") if s != ""]


def get_path(doc, path, default=None):
    cur = doc
    for seg in _split(path):
        if isinstance(cur, dict):
            if seg not in cur:
                return default
            cur = cur[seg]
        elif isinstance(cur, list):
            try:
                i = int(seg)
            except ValueError:
                return default
            if i < 0 or i >= len(cur):
                return default
            cur = cur[i]
        else:
            return default
    return cur


def set_path(doc, path, value):
    segs = _split(path)
    if not segs:
        raise ValueError("空路径")
    cur = doc
    for seg in segs[:-1]:
        if isinstance(cur, dict):
            if seg not in cur or not isinstance(cur[seg], (dict, list)):
                cur[seg] = {}
            cur = cur[seg]
        elif isinstance(cur, list):
            cur = cur[int(seg)]
        else:
            raise ValueError("路径不可写: %s" % path)
    last = segs[-1]
    if isinstance(cur, list):
        i = int(last)
        if i >= len(cur):
            raise IndexError("下标越界: %s" % path)
        cur[i] = value
    else:
        cur[last] = value


def del_path(doc, path):
    segs = _split(path)
    parent = get_path(doc, ".".join(segs[:-1]), None)
    last = segs[-1]
    if isinstance(parent, dict):
        parent.pop(last, None)
    elif isinstance(parent, list):
        i = int(last)
        if 0 <= i < len(parent):
            parent.pop(i)


def coerce(new, old):
    """按原值的类型把前端传来的值转换过去（前端可能传字符串）。"""
    if isinstance(old, bool):
        if isinstance(new, str):
            return new.strip().lower() in ("1", "true", "yes", "on", "是")
        return bool(new)
    if isinstance(old, int) and not isinstance(old, bool):
        try:
            return int(round(float(new)))
        except (TypeError, ValueError):
            return old
    if isinstance(old, float):
        try:
            return float(new)
        except (TypeError, ValueError):
            return old
    if isinstance(old, list):
        return new if isinstance(new, list) else [new]
    if isinstance(old, str):
        return new if isinstance(new, str) else str(new)
    return new


def _materialize(doc, ref, path):
    """要写的键只存在于"上游默认值"里时，先把这一整棵子树落到文件里，再改。"""
    segs = _split(path)
    if not segs or ref is None or not isinstance(doc, dict):
        return
    top = segs[0]
    if top in doc:
        return
    val = ref.get(top) if isinstance(ref, dict) else None
    if val is None:
        return
    doc[top] = copy.deepcopy(val) if isinstance(val, (dict, list)) else val


def apply_ops(meta, doc, ops, ref=None):
    """ops: [{op: set|add|del, path, value}]。返回实际生效的变更列表。

    doc 是磁盘上的真实内容（稀疏），ref 是"当前值 + 上游默认值"的合并视图：
    类型判断和"值没变"的判定都看 ref，写只写 doc，所以默认值不会被无谓地固化。
    """
    applied = []
    for op in ops or []:
        kind = (op.get("op") or "set").lower()
        path = op.get("path") or ""
        if kind == "set":
            old_raw = get_path(doc, path, "<不存在>")
            old = old_raw if old_raw != "<不存在>" else get_path(ref if ref is not None else doc, path, "<不存在>")
            new = coerce(op.get("value"), old if old != "<不存在>" else op.get("value"))
            if old_raw != "<不存在>" and old_raw == new:
                continue
            _materialize(doc, ref, path)
            set_path(doc, path, new)
            applied.append({"op": "set", "path": path,
                            "old": None if old == "<不存在>" else old, "new": new})
        elif kind == "add":
            parent = get_path(doc, path, None)
            if isinstance(parent, list):
                parent.append(op.get("value"))
                applied.append({"op": "add", "path": path, "index": len(parent) - 1, "new": op.get("value")})
            else:
                raise ValueError("只能往列表里加项: %s" % path)
        elif kind == "del":
            target = op.get("path")
            old = get_path(doc, target, None)
            del_path(doc, target)
            applied.append({"op": "del", "path": target, "old": old})
        else:
            raise ValueError("未知操作: %s" % kind)
    return applied


def save_ops(fid, ops, note=""):
    meta, raw, _text = load_raw(fid)
    ref = raw
    sch = _schema_doc(meta)
    if sch:
        ref = copy.deepcopy(raw)
        _merge_defaults(ref, sch)
    applied = apply_ops(meta, raw, ops, ref=ref)
    if not applied:
        return {"ok": True, "applied": [], "backup": "", "changed": 0}
    text = _dump(meta, raw)
    _load(meta, text)  # 自检：写回去还能解析
    bak = backup(meta)
    _write_atomic(meta["path"], text)
    _CACHE["files"] = None
    _log_change(meta, applied, note)
    return {"ok": True, "applied": applied, "backup": bak, "changed": len(applied)}


def _log_change(meta, applied, note):
    try:
        line = "%s INFO [config] 修改 %s（%d 项）%s | %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), meta["label"], len(applied),
            (" - " + note) if note else "",
            "; ".join("%s: %r -> %r" % (a["path"], a.get("old"), a.get("new")) for a in applied[:12]),
        )
        with open(BASE / "logs" / "config_changes.log", "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def raw_read(fid):
    meta, doc, text = load_doc(fid)
    return {"text": text, "rel": str(meta["path"].relative_to(BASE)).replace(os.sep, "/"),
            "size": len(text), "fmt": meta["fmt"]}


def raw_write(fid, text):
    meta = get(fid)
    if text is None:
        raise ValueError("没有内容")
    try:
        _load(meta, text)  # 语法校验，解析不过就不写
    except Exception as e:  # ruamel/PyYAML 的 ParserError 不是 ValueError 的子类
        first = str(e).strip().splitlines()[0] if str(e).strip() else e.__class__.__name__
        raise ValueError("语法错误: %s" % first)
    bak = backup(meta)
    _write_atomic(meta["path"], text)
    _CACHE["files"] = None
    try:
        with open(BASE / "logs" / "config_changes.log", "a", encoding="utf-8") as fh:
            fh.write("%s INFO [config] 原始编辑 %s（%d 字节）\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"), meta["label"], len(text)))
    except OSError:
        pass
    return {"ok": True, "backup": bak}


# --------------------------------------------------------------------------- 树
def _type_of(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        if "\n" in v or len(v) > 160:
            return "text"
        return "str"
    if v is None:
        return "null"
    if isinstance(v, list):
        return "list"
    return "str"


def _secret(meta, path):
    last = _split(path)[-1].lower() if path else ""
    return any(h in last for h in meta["secret_hints"])


def _node(meta, value, path, depth=0, dset=None):
    name = _split(path)[-1] if path else ""
    if isinstance(value, dict):
        children = [_node(meta, v, (path + "." if path else "") + str(k), depth + 1, dset)
                    for k, v in value.items()]
        return {"kind": "group", "name": name, "path": path,
                "label": L.group_label(path, name, meta["game"]), "children": children,
                "is_default": bool(dset and path in dset)}
    if isinstance(value, list) and value and isinstance(value[0], dict):
        children = [_node(meta, v, "%s.%d" % (path, i), depth + 1, dset) for i, v in enumerate(value)]
        for i, c in enumerate(children):
            c["label"] = ("第 %d 项" % (i + 1)) + ("：" + str(L.first_str(value[i])) if L.first_str(value[i]) else "")
        return {"kind": "group", "name": name, "path": path,
                "label": L.group_label(path, name, meta["game"]), "children": children,
                "list_group": True, "count": len(value)}
    node = {
        "kind": "field", "name": name, "path": path, "type": _type_of(value),
        "value": value, "secret": _secret(meta, path),
        "label": (meta.get("_labels") or {}).get(path) or L.field_label(path, name, meta["game"]),
        "help": (meta.get("_helps") or {}).get(path) or L.help_text(path, meta["game"]),
        "readonly": path in meta["readonly"] or name.lower() in ("lastupdatescriptrepotime", "runforversion"),
        # is_default: 这个键文件里还没写，值来自上游默认配置（改了就落盘）
        "is_default": bool(dset and path in dset),
    }
    if not node["readonly"] and not node["secret"]:
        try:  # 有明确枚举的字段给下拉，别让人手打（上游加了新选项这里自动跟着变）
            opt = OPT.for_node(meta["id"], path, name, value)
        except Exception:  # noqa: BLE001
            opt = None
        if opt:
            node.update(opt)
    return node


def build_tree(fid):
    meta, doc, text = load_doc(fid)
    if not isinstance(doc, dict):
        raise ValueError("配置根节点不是对象")
    dset = set(meta.get("_defaults") or [])
    tree = [_node(meta, v, str(k), 0, dset) for k, v in doc.items()]
    rules = L.IMPORTANT.get(meta["id"]) or L.IMPORTANT.get(meta["game"]) or []
    important = []
    def _imp(path, label, help_txt, val):
        item = {"path": path, "label": label, "help": help_txt,
                "type": _type_of(val), "value": val, "secret": _secret(meta, path),
                "is_default": path in dset}
        if not item["secret"]:
            try:
                opt = OPT.for_node(meta["id"], path, path.rsplit(".", 1)[-1], val)
            except Exception:  # noqa: BLE001
                opt = None
            if opt:
                item.update(opt)
        return item

    for path, label, help_txt in rules:
        val = get_path(doc, path, "<不存在>")
        if val == "<不存在>":
            continue
        if isinstance(val, dict):
            # 常用区里塞不下字典：展开成一行一个子项（子项还是字典/列表的跳过）
            for k, sub in val.items():
                if isinstance(sub, (dict, list)):
                    continue
                important.append(_imp("%s.%s" % (path, k), "%s · %s" % (label, k), help_txt, sub))
            continue
        if isinstance(val, list) and val and isinstance(val[0], (dict, list)):
            continue
        important.append(_imp(path, label, help_txt, val))
    fields = []

    def _count(nodes):
        for n in nodes:
            if n.get("kind") == "group":
                _count(n.get("children") or [])
            else:
                fields.append(n)

    _count(tree)
    return {
        "meta": {"id": meta["id"], "label": meta["label"], "game": meta["game"], "fmt": meta["fmt"],
                 "rel": str(meta["path"].relative_to(BASE)).replace(os.sep, "/"),
                 "note": meta["note"], "special": meta["special"], "size": len(text),
                 "schema": str(Path(meta["schema"]).relative_to(BASE)).replace(os.sep, "/") if meta.get("schema") else "",
                 "fields": len(fields),
                 "defaults": sum(1 for n in fields if n.get("is_default")),
                 "order": meta.get("order") or ""},
        "tree": tree, "important": important,
    }