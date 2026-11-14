# -*- coding: utf-8 -*-
"""配置中心 · 中文标签 / 说明 / 重点设置清单。

三层命名：
  1. PATH_LABELS  精确到某个键（最准，优先）
  2. 分词字典      camelCase / snake_case 拆开后逐词翻译（覆盖面最广）
  3. 原样显示      实在不认识就显示原始键名（不会被藏起来）
"""
import re

# --------------------------------------------------------------------------- 分组标题
GROUP_LABELS = {
    # BetterGI 主配置
    "maskWindowConfig": "遮罩窗口外观",
    "commonConfig": "通用设置",
    "genshinStartConfig": "启动原神",
    "autoPickConfig": "自动拾取",
    "autoSkipConfig": "自动跳过对话",
    "autoFishingConfig": "自动钓鱼",
    "autoComboBuildConfig": "自动搭配合成",
    "quickTeleportConfig": "快捷传送",
    "autoGeniusInvokationConfig": "七圣召唤",
    "autoWoodConfig": "自动伐木",
    "autoFightConfig": "自动战斗",
    "autoMusicGameConfig": "音游玩法",
    "autoDomainConfig": "自动秘境",
    "autoBossConfig": "自动首领讨伐",
    "autoStygianOnslaughtConfig": "自动幽境危战",
    "autoArtifactSalvageConfig": "圣遗物分解",
    "autoEatConfig": "自动吃药",
    "autoLeyLineOutcropConfig": "自动地脉花",
    "autoCookConfig": "自动烹饪",
    "mapMaskConfig": "地图遮罩",
    "skillCdConfig": "技能冷却提示",
    "autoRedeemCodeConfig": "兑换码",
    "getGridIconsConfig": "图标获取",
    "macroConfig": "宏",
    "recordConfig": "录制回放",
    "musicConfig": "音乐",
    "scriptConfig": "战斗脚本仓库",
    "pathingConditionConfig": "寻路兜底条件",
    "hotKeyConfig": "热键",
    "notificationConfig": "通知推送",
    "keyBindingsConfig": "按键绑定",
    "otherConfig": "其它",
    "tpConfig": "传送与地图",
    "devConfig": "开发者",
    "hardwareAccelerationConfig": "硬件加速 / AI 推理",
    "childSessionConfig": "子窗口",
    # 一条龙每日任务
    "TaskEnabledList": "任务开关",
    "TaskOrder": "执行顺序",
    "TaskDefinitions": "任务名称表",
    "SecretTreasureObjects": "藏宝图对象",
    # 崩铁
    "notify": "通知",
    # 我们
    "scheduler": "定时与总控",
    "games": "各游戏设置",
    "targets": "目标列表",
}

# --------------------------------------------------------------------------- 精确键名
PATH_LABELS = {
    # BetterGI 启动
    "genshinStartConfig.installPath": "游戏路径（YuanShen.exe）",
    "genshinStartConfig.autoEnterGameEnabled": "自动进入游戏",
    "genshinStartConfig.linkedStartEnabled": "联动退出（关 BetterGI 时关游戏）",
    "genshinStartConfig.genshinStartArgs": "启动参数",
    "genshinStartConfig.startGameWithCmd": "用命令行启动",
    "genshinStartConfig.autoDisableGenshinHdrEnabled": "自动关闭 HDR",
    "genshinStartConfig.recordGameTimeEnabled": "记录游戏时长",
    # BetterGI 战斗
    "autoFightConfig.strategyName": "战斗策略（用哪个脚本）",
    "autoFightConfig.teamNames": "战斗队伍名（留空=自动识别当前队伍）",
    "autoFightConfig.fightFinishDetectEnabled": "战斗结束检测",
    "autoFightConfig.onlyPickEliteDropsMode": "只捡精英掉落",
    "autoFightConfig.kazuhaPickupEnabled": "万叶吸掉落",
    "autoFightConfig.burstEnabled": "自动放大招",
    "autoFightConfig.timeout": "战斗超时（秒）",
    "autoFightConfig.guardianAvatar": "护盾角色",
    "autoFightConfig.guardianCombatSkip": "有护盾时跳过战斗",
    # BetterGI 秘境
    "autoDomainConfig.partyName": "秘境队伍（留空=用一条龙的）",
    "autoDomainConfig.domainName": "秘境名",
    "autoDomainConfig.resinPriorityList": "树脂使用优先级",
    "autoDomainConfig.autoEat": "秘境里自动吃药",
    "autoDomainConfig.autoArtifactSalvage": "打完分解圣遗物",
    "autoDomainConfig.reviveRetryCount": "团灭重试次数",
    "autoDomainConfig.fightEndDelay": "战斗结束等待（秒）",
    "autoDomainConfig.walkToF": "走到 F 键交互点",
    # BetterGI 地脉花
    "autoLeyLineOutcropConfig.country": "国家",
    "autoLeyLineOutcropConfig.leyLineOutcropType": "地脉花类型（启示/藏金）",
    "autoLeyLineOutcropConfig.count": "固定次数",
    "autoLeyLineOutcropConfig.isResinExhaustionMode": "树脂耗尽模式（不推荐）",
    "autoLeyLineOutcropConfig.openModeCountMin": "先开地图再数次数",
    "autoLeyLineOutcropConfig.team": "队伍（留空=自动识别）",
    "autoLeyLineOutcropConfig.timeout": "超时（秒）",
    "autoLeyLineOutcropConfig.useTransientResin": "允许用须臾树脂",
    "autoLeyLineOutcropConfig.useFragileResin": "允许用脆弱树脂",
    # BetterGI 幽境危战
    "autoStygianOnslaughtConfig.bossNum": "危战层数",
    "autoStygianOnslaughtConfig.fightTeamName": "危战队伍",
    "autoStygianOnslaughtConfig.strategyName": "危战战斗策略",
    # BetterGI 脚本仓库
    "scriptConfig.subscribedScriptPaths": "已订阅的战斗脚本",
    "scriptConfig.autoUpdateSubscribedScripts": "自动更新订阅脚本",
    "scriptConfig.autoUpdateBeforeCommandLineRun": "命令行启动前先更新脚本",
    "scriptConfig.customRepoUrl": "自定义脚本仓库地址",
    "scriptConfig.autoUpdateScriptRepoPeriod": "脚本仓库更新周期（天）",
    # BetterGI 其它
    "autoPickConfig.enabled": "启用自动拾取",
    "autoPickConfig.pickKey": "拾取键",
    "autoPickConfig.mode": "拾取模式（白名单/黑名单）",
    "autoSkipConfig.enabled": "启用自动跳过",
    "autoSkipConfig.quicklySkipConversationsEnabled": "快速跳过对话",
    "autoSkipConfig.clickChatOption": "对话选项策略",
    "autoSkipConfig.submitGoodsEnabled": "自动提交物品",
    "captureMode": "截图模式（BitBlt/WGC）",
    "commonConfig.screenshotEnabled": "运行结束截图",
    "commonConfig.exitToTray": "关闭时最小化到托盘",
    "commonConfig.runForVersion": "上次运行版本（只读）",
    "otherConfig.autoRestartConfig": "失败自动重启",
    "tpConfig.reviveStatueOfTheSevenArea": "复活神像区域",
    "tpConfig.reviveStatueOfTheSevenCountry": "复活神像国家",
    "hardwareAccelerationConfig.inferenceDevice": "推理设备（0=GPU）",
    "hardwareAccelerationConfig.cpuOcr": "文字识别用 CPU",
    "hardwareAccelerationConfig.gpuDevice": "GPU 编号",
    "detailedErrorLogs": "详细错误日志",
    "selectedOneDragonFlowConfigName": "当前使用的一条龙方案",

    # 一条龙 daily.json
    "PartyName": "打本队伍名",
    "DomainName": "默认秘境",
    "WeeklyDomainEnabled": "打每周秘境（周本）",
    "DailyRewardPartyName": "领每日奖励的队伍",
    "MinResinToKeep": "至少保留的原粹树脂",
    "CraftingBenchCountry": "合成台所在国家",
    "AdventurersGuildCountry": "冒险家协会国家",
    "SereniteaPotTpType": "尘歌壶传送方式",
    "CompletionAction": "全部完成后做什么",
    "Name": "方案名",
    "LeyLineOneDragonMode": "地脉花走一条龙流程",
    "LeyLineRunCount": "地脉花次数",
    "LeyLineResinExhaustionMode": "地脉花：树脂耗尽模式",
    "LeyLineOpenModeCountMin": "地脉花：先开地图数次数",
    "AutoBossRunCount": "首领讨伐次数",
    "AutoBossReviveRetryCount": "首领团灭重试",
    "AutoBossTimeout": "首领超时（秒）",
    "AutoBossStrategyName": "首领战斗策略",

    # 崩铁
    "game_path": "游戏路径（StarRail.exe）",
    "game_process_name": "进程名",
    "game_title_name": "窗口标题",
    "launcher_path": "启动器路径",
    "update_via_launcher": "通过启动器更新",
    "start_game_timeout": "启动游戏超时（秒）",
    "update_game_timeout": "更新游戏超时（秒）",
    "instance_type": "清体力：副本类型",
    "instance_names": "清体力：副本名称列表",
    "instance_names_challenge_count": "清体力：各副本次数",
    "tp_before_instance": "打本前先传送",
    "use_reserved_trailblaze_power": "用后备开拓力",
    "use_fuel": "用燃料（体力药）",
    "merge_immersifier": "优先合成沉浸器",
    "merge_immersifier_limit": "沉浸器合成上限",
    "calyx_golden_preference": "花萼偏好",
    "build_target_enable": "按培养目标刷",
    "break_down_level_four_relicset": "分解 4 星遗器",
    "daily_enable": "启用每日实训",
    "daily_tasks": "每日任务清单",
    "daily_material_enable": "每日材料本",
    "daily_himeko_try_enable": "姬子试用",
    "daily_memory_one_enable": "记忆的碎片",
    "reward_enable": "启用奖励领取",
    "reward_dispatch_enable": "派遣委托",
    "reward_mail_enable": "领邮件",
    "reward_assist_enable": "支援奖励",
    "reward_quest_enable": "任务奖励",
    "reward_srpass_enable": "无名勋礼",
    "reward_redemption_code_enable": "兑换码",
    "reward_achievement_enable": "成就奖励",
    "reward_message_enable": "短信奖励",
    "universe_enable": "启用模拟宇宙",
    "universe_count": "模拟宇宙次数",
    "universe_operation_mode": "模拟宇宙方式",
    "universe_category": "模拟宇宙类别",
    "fight_enable": "启用历战余响",
    "fight_operation_mode": "历战余响方式",
    "fight_team_enable": "历战余响用指定队伍",
    "forgottenhall_enable": "启用忘却之庭",
    "purefiction_enable": "启用虚构叙事",
    "apocalyptic_enable": "启用末日幻影",
    "echo_of_war_enable": "启用历战余响（回声）",
    "activity_enable": "启用活动任务",
    "activity_dailycheckin_enable": "每日签到",
    "currencywars_enable": "以太战线",
    "weekly_divergent_enable": "差分宇宙（周常）",
    "divergent_station_priority_enable": "优先差分宇宙",
    "pause_after_success": "成功后暂停（不自动关）",
    "pause_after_failure": "失败后暂停",
    "exit_after_failure": "失败也退出",
    "after_finish": "运行结束后",
    "play_audio": "结束播放提示音",
    "check_update": "启动时检查更新",
    "auto_update": "自动更新三月七",
    "update_source": "更新源",
    "mirrorchyan_cdk": "Mirror酱 CDK",
    "auto_set_resolution_enable": "自动改游戏分辨率",
    "auto_set_game_path_enable": "自动识别游戏路径",
    "use_background_screenshot": "后台截图",
    "ocr_gpu_acceleration": "OCR 用 GPU 加速",
    "power_enable": "运行前切换电源计划",
    "power_plan": "用户电源计划",
    "power_plan_keep": "保持电源计划",
    "loop_mode": "循环模式",
    "scheduled_time": "定时运行时间",
    "power_limit": "体力上限（超过就停）",
    "refresh_hour": "刷新时间（小时）",
    "log_level": "日志级别",
    "log_retention_days": "日志保留天数",
    "log_overlay_enable": "日志悬浮窗",
    "debug_mode_enable": "调试模式",
    "browser_type": "浏览器类型",
    "browser_headless_enable": "无头浏览器",
    "cloud_game_enable": "云游戏模式",
    "notification_enable": "启用通知",
    "notify_level": "通知级别",
    "notify_merge": "合并通知",
    "notify_send_images": "通知附带截图",
    "notify_winotify_enable": "Windows 系统通知",
    "notify_telegram_enable": "Telegram",
    "notify_bark_enable": "Bark",
    "notify_smtp_enable": "邮件",
    "notify_onebot_enable": "OneBot",
    "notify_dingtalk_enable": "钉钉",
    "notify_serverchan3_enable": "Server酱³",
    "notify_pushplus_enable": "PushPlus",
    "notify_wechatworkbot_enable": "企业微信机器人",
    "notify_custom_enable": "自定义 Webhook",
    "redemption_code": "要兑换的码",
    "already_used_codes": "已用过的码",

    # 绝区零 OneDragon
    "background_mode": "后台模式（必须 false）",
    "background_gamepad_type": "后台手柄类型",
    "original_hdr_value": "HDR 原值",
    "game_path": "游戏路径",
    "account": "账号",
    "password": "密码",
    "game_region": "区服（cn=国服）",
    "restore_charge": "电量用完后",
    "double_reward": "使用双倍奖励",
    "plan_list": "体力计划列表",
    "run_times": "已完成次数",
    "plan_times": "计划次数",
    "category_name": "副本大类",
    "mission_type_name": "副本类型",
    "mission_name": "副本名称",
    "level": "难度",
    "auto_battle_config": "自动战斗配置",
    "predefined_team_idx": "队伍序号",
    "card_num": "卡片数量",
    "notorious_hunt_buff_num": "恶名狩猎增益",
    "active_app_id": "当前应用",

    # 我们的
    "scheduler.daily_time": "每天几点跑（HH:MM）",
    "scheduler.enabled": "启用定时",
    "scheduler.run_order": "运行顺序",
    "scheduler.timeout_minutes": "单次总超时（分钟）",
    "scheduler.min_uptime_minutes": "开机至少稳定多少分钟才开跑",
    "scheduler.boot_wait_max_minutes": "等开机稳定最多等多久",
    "games.genshin.party_name": "原神打本队伍名",
    "games.genshin.resin_policy": "树脂策略",
    "games.genshin.stall_minutes": "卡死判定（分钟没日志）",
    "games.starrail.stall_minutes": "卡死判定（分钟没日志）",
    "games.starrail.fuel_policy": "开拓力策略",
    "games.zzz.battery_policy": "电量策略",
    "display.auto_switch_window": "跑的时候自动切窗口化",
    "display.auto_width": "自动化时窗口宽",
    "display.auto_height": "自动化时窗口高",
    # 2026-11-14 补：这几个键原来完全没中文，界面上直接显示英文键名
    "region": "区服",
    "auto_login": "掉登录自动登录",
    "do_commissions": "每日委托",
    "claim_welkin": "领取月卡",
    "claim_katheryne": "凯瑟琳奖励",
    "switch_only": "只是开关（不是秘境）",
    "category": "副本大类",
    "mode": "运行方式",
    "proxy": "网络代理",
    "windowed_value": "窗口化标志值",
}

# --------------------------------------------------------------------------- 分词字典
WORDS = {
    "enable": "启用", "enabled": "启用", "disable": "禁用", "disabled": "禁用",
    "name": "名称", "names": "名称", "path": "路径", "paths": "路径", "url": "地址", "urls": "地址",
    "count": "次数", "counts": "次数", "times": "次数", "num": "数量", "number": "数量",
    "time": "时间", "timeout": "超时", "seconds": "秒", "second": "秒", "minute": "分钟",
    "interval": "间隔", "delay": "延迟", "period": "周期", "hour": "小时", "day": "天", "days": "天数",
    "speed": "速度", "level": "等级", "mode": "模式", "type": "类型", "kind": "类型",
    "team": "队伍", "party": "队伍", "avatar": "角色", "character": "角色", "uid": "UID",
    "account": "账号", "password": "密码", "token": "Token", "secret": "密钥", "key": "Key",
    "cookie": "Cookie", "cdk": "兑换码", "code": "兑换码", "codes": "兑换码",
    "size": "尺寸", "width": "宽", "height": "高", "x": "X", "y": "Y", "opacity": "不透明度",
    "theme": "主题", "version": "版本", "log": "日志", "logs": "日志", "debug": "调试",
    "strategy": "策略", "fight": "战斗", "attack": "攻击", "battle": "战斗", "skill": "技能",
    "domain": "秘境", "boss": "首领", "leyline": "地脉", "resin": "树脂",
    "condensed": "浓缩树脂", "transient": "须臾树脂", "fragile": "脆弱树脂", "original": "原粹",
    "run": "运行", "runs": "次数", "reward": "奖励", "rewards": "奖励", "daily": "每日",
    "week": "周", "weekly": "每周", "sunday": "周日", "monday": "周一", "tuesday": "周二",
    "wednesday": "周三", "thursday": "周四", "friday": "周五", "saturday": "周六",
    "country": "国家", "teleport": "传送", "map": "地图", "zoom": "缩放",
    "pick": "拾取", "pickup": "拾取", "drops": "掉落", "skip": "跳过", "dialog": "对话",
    "dialogue": "对话", "eat": "进食", "cook": "烹饪", "wood": "木材", "fish": "钓鱼",
    "fishing": "钓鱼", "music": "音游", "craft": "合成", "mail": "邮件",
    "expedition": "探索派遣", "commission": "委托", "pot": "尘歌壶", "serenitea": "尘歌壶",
    "salvage": "分解", "recognition": "识别", "detect": "检测", "detection": "检测",
    "screenshot": "截图", "screenshots": "截图", "ocr": "OCR", "gpu": "GPU", "cpu": "CPU",
    "model": "模型", "models": "模型", "cache": "缓存", "hotkey": "热键", "hotkeys": "热键",
    "window": "窗口", "windows": "窗口", "notify": "通知", "notification": "通知",
    "notifications": "通知", "retry": "重试", "revive": "复活", "buy": "购买", "use": "使用",
    "borrow": "借用", "friend": "好友", "friends": "好友", "instance": "副本", "instances": "副本",
    "calyx": "花萼", "golden": "金", "trailblaze": "开拓力", "fuel": "燃料",
    "immersifier": "沉浸器", "universe": "模拟宇宙", "divergent": "差分宇宙",
    "forgottenhall": "忘却之庭", "purefiction": "虚构叙事", "apocalyptic": "末日幻影",
    "echo": "回声", "war": "战争", "activity": "活动", "power": "电源", "plan": "计划",
    "plans": "计划", "browser": "浏览器", "cloud": "云", "game": "游戏", "games": "游戏",
    "update": "更新", "updates": "更新", "mirror": "镜像", "proxy": "代理",
    "notification_enable": "启用通知", "winotify": "Windows 通知", "telegram": "Telegram",
    "discord": "Discord", "serverchan": "Server酱", "bark": "Bark", "smtp": "邮件",
    "onebot": "OneBot", "gocqhttp": "GoCQHTTP", "dingtalk": "钉钉", "pushplus": "PushPlus",
    "wechatwork": "企业微信", "workweixin": "企业微信", "gotify": "Gotify",
    "pushdeer": "PushDeer", "lark": "飞书", "kook": "KOOK", "meow": "MeoW",
    "webhook": "Webhook", "custom": "自定义", "matrix": "Matrix", "qq": "QQ",
    "check": "检查", "auto": "自动", "manual": "手动", "default": "默认",
    "max": "最大", "min": "最小", "limit": "上限", "total": "总", "left": "剩余",
    "start": "开始", "end": "结束", "finish": "结束", "first": "第一", "last": "上次",
    "show": "显示", "display": "显示", "lines": "行数", "list": "列表",
    "autoplot": "自动剧情", "combat": "战斗", "simulation": "模拟", "double": "双倍",
    "config": "配置", "settings": "设置", "restore": "恢复", "reset": "重置",
    "daily_signin": "每日签到", "intel_board": "情报板", "life_on_line": "生活在线",
    "lost_void": "迷失之地", "notorious_hunt": "恶名狩猎", "withered_domain": "枯萎之地",
    "standalone": "独立应用", "app": "应用", "skip": "跳过", "obtain": "获取",
    # 2026-11-14 补：这三类词原来没收录，导致「自动 switch 窗口」这种半翻译
    "switch": "切换", "only": "仅", "open": "打开", "close": "关闭",
    "click": "点击", "press": "按下", "move": "移动", "task": "任务", "tasks": "任务",
    "panel": "面板", "screen": "屏幕", "resolution": "分辨率", "text": "文本",
    "source": "来源", "status": "状态", "priority": "优先级", "selected": "选中",
    "select": "选择", "choose": "选择", "after": "之后", "before": "之前",
    "ratio": "比例", "predefined": "预设", "color": "颜色", "line": "线", "lines": "行数",
    "value": "值", "values": "值", "label": "标签", "metrics": "指标",
    "lifecycle": "生命周期", "detail": "详细", "details": "详细", "mission": "任务",
    "background": "背景", "shadow": "阴影", "timestamp": "时间戳", "idx": "序号",
    "completed": "已完成", "complete": "完成", "guide": "引导", "guided": "引导",
    "quick": "快速", "bot": "机器人", "asset": "资源", "assets": "资源",
    "claim": "领取", "overlay": "悬浮层", "font": "字体", "device": "设备",
    "training": "训练", "category": "分类", "mask": "遮罩", "box": "框",
    "crosshair": "准星", "record": "录制", "artifact": "圣遗物", "artifacts": "圣遗物",
    "challenge": "挑战", "threads": "线程", "buff": "增益", "option": "选项",
    "options": "选项", "endpoint": "接口", "extra": "额外", "enemy": "敌人",
    "failure": "失败", "user": "用户", "scale": "缩放", "border": "边框",
    "thickness": "粗细", "direction": "方向", "main": "主", "fast": "快速",
    "hangout": "邀约", "api": "接口", "card": "卡片", "cards": "卡片",
    "guardian": "护盾", "statue": "神像", "script": "脚本", "scripts": "脚本",
    "mouse": "鼠标", "base": "基础", "group": "组", "groups": "组", "tab": "标签页",
    "notorious": "恶名", "hunt": "狩猎", "pip": "源", "store": "商店",
    "minutes": "分钟", "policy": "策略", "usage": "占用", "memory": "内存",
    "radius": "半径", "item": "物品", "items": "物品", "sleep": "休眠",
    "active": "激活", "action": "动作", "cd": "冷却", "factor": "系数",
    "burst": "爆发", "paimon": "派蒙", "star": "星", "stars": "星",
    "button": "按钮", "macro": "宏", "error": "错误", "errors": "错误",
    "webview": "网页视图", "message": "消息", "messages": "消息", "pass": "密码",
    "target": "目标", "targets": "目标", "repository": "仓库", "region": "区服",
    "coffee": "咖啡", "ember": "余烬", "currencywars": "货币战争", "scheduled": "定时",
    "warn": "警告", "warning": "警告", "info": "信息", "output": "输出", "input": "输入",
    "format": "格式", "version": "版本", "page": "页", "quality": "画质", "fps": "帧率",
    "frame": "帧", "loop": "循环", "wait": "等待", "debug": "调试", "verbose": "详细输出",
    "test": "测试", "save": "保存", "load": "载入", "export": "导出", "import": "导入",
    "log": "日志", "logs": "日志", "file": "文件", "folder": "文件夹", "dir": "目录",
    "key": "键", "keys": "按键", "token": "令牌", "time": "时间", "timer": "计时",
    "date": "日期", "weekday": "星期", "month": "月", "year": "年", "push": "推送",
    "sound": "声音", "volume": "音量", "mute": "静音", "theme": "主题",
    "dark": "深色", "light": "浅色", "layout": "布局", "content": "内容",
    "title": "标题", "desc": "描述", "description": "描述", "comment": "注释",
    "note": "备注", "notes": "备注", "size": "大小", "width": "宽", "height": "高",
    "position": "位置", "offset": "偏移", "image": "图像", "images": "图像",
    "icon": "图标", "play": "播放", "pause": "暂停", "stop": "停止",
    # 2026-11-14 第二批：BetterGI 主配置里剩下的半翻译
    "id": "ID", "ley": "地脉", "leyline": "地脉", "client": "客户端", "do": "执行",
    "cost": "开销", "bgi": "BGI", "normal": "普通", "special": "特殊", "exit": "退出",
    "redeem": "兑换", "feeds": "推送源", "global": "全局", "chat": "聊天", "picture": "图片",
    "hold": "长按", "specify": "指定", "bonus": "加成", "repo": "仓库", "track": "追踪",
    "cancel": "取消", "pos": "位置", "from": "来自", "server": "服务器", "send": "发送",
    "menu": "菜单", "cap": "上限", "allow": "允许", "launcher": "启动器", "build": "构建",
    "merge": "合并", "link": "链接", "env": "环境", "blood": "血量", "order": "顺序",
    "capture": "截图", "trigger": "触发", "voice": "语音", "confirm": "确认", "event": "事件",
    "process": "进程", "prompt": "提示", "fallback": "回退", "tp": "传送", "space": "空格",
    "refresh": "刷新", "elite": "精英", "visible": "可见", "up": "上", "down": "下",
    "left": "左", "right": "右", "top": "顶", "bottom": "底", "exp": "经验",
    "lost": "迷失", "set": "设置", "regular": "常规", "dish": "料理", "adventurers": "冒险家",
    "seek": "寻找", "ms": "毫秒", "recover": "恢复", "point": "点位", "enhance": "强化",
    "scroll": "滚动", "channel": "渠道", "method": "方式", "subject": "主题", "object": "对象",
    "result": "结果", "copy": "复制", "email": "邮箱", "port": "端口", "username": "用户名",
    "element": "元素", "elemental": "元素", "quest": "任务", "ui": "界面", "restart": "重启",
    "operation": "操作", "keep": "保留", "full": "完整", "simulated": "模拟", "sign": "签到",
    "telemetry": "遥测", "dodge": "闪避", "pawnshop": "当铺", "wechat": "微信", "feishu": "飞书",
    "ding": "钉钉", "wechatwork": "企业微信", "wechatworkbot": "企业微信机器人", "blur": "模糊",
    "gap": "间距", "column": "列", "row": "行", "cover": "遮蔽", "scaling": "缩放",
    "family": "字体族", "rect": "矩形", "stroke": "描边", "drawable": "可绘制", "style": "样式",
    "html": "网页", "current": "当前", "once": "一次", "had": "曾有", "xxtui": "消息推送",
    "seven": "七圣", "exe": "程序", "uid": "UID", "px": "像素", "py": "纵坐标", "x": "横坐标",
    "y": "纵坐标", "lv": "等级", "tp": "传送", "num": "数量", "total": "总计",
}


def _tokens(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", str(name))
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
    return [t.lower() for t in re.split(r"[_\W]+", s) if t]


_CJK = re.compile(r"[\u4e00-\u9fff]")
# 这些虚词直接丢掉，翻出来只会让中文更别扭
_DROP = {"the", "a", "an", "of", "to", "in", "on", "by", "is", "and", "or", "with", "for"}


def humanize(name):
    """逐词翻译，但拼接时只在「两侧都不是中文」处留空格。

    2026-11-14 修：原来是 " ".join()，于是 "auto_switch_window" 被译成
    「自动 switch 窗口」这种半中半英的怪串。现在中文之间不加空格，
    中英之间加一个空格（"GPU 占用"），全部词都没收录时原样返回键名。
    """
    toks = [t for t in _tokens(name) if t not in _DROP]
    if not toks:
        return str(name)
    parts = [WORDS.get(t) for t in toks]
    if all(p is None for p in parts):
        return str(name)
    out = []
    prev_cn = None
    for t, p in zip(toks, parts):
        piece = p if p else t
        cn = bool(_CJK.search(piece))
        if out and not (cn and prev_cn):
            out.append(" ")
        out.append(piece)
        prev_cn = cn
    return "".join(out)


def group_label(path, name, game=""):
    if path in PATH_LABELS:
        return PATH_LABELS[path]
    if name in GROUP_LABELS:
        return GROUP_LABELS[name]
    return humanize(name)


def field_label(path, name, game=""):
    if path in PATH_LABELS:
        return PATH_LABELS[path]
    if name in PATH_LABELS:
        return PATH_LABELS[name]
    return humanize(name)


HELP = {
    "genshinStartConfig.installPath": "填 YuanShen.exe 的完整路径；BetterGI 用它启动游戏。",
    "autoFightConfig.strategyName": "BetterGI 用哪个战斗脚本。脚本里没有你队伍的角色时，战斗会站着不动——这是『站桩挨打』的根源。",
    "autoFightConfig.teamNames": "留空 = 自动识别当前队伍；填了只对指定队伍生效。",
    "scriptConfig.subscribedScriptPaths": "从脚本仓库订阅的战斗脚本。订阅后可用『自动更新订阅脚本』保持最新。",
    "scriptConfig.autoUpdateSubscribedScripts": "每次运行前自动拉取订阅脚本的新版本。",
    "autoLeyLineOutcropConfig.isResinExhaustionMode": "开启后靠地图上的树脂图标 OCR 判断还剩多少，地图没渲染完就会读成 0 并直接结束。推荐关掉，用『固定次数』。",
    "autoLeyLineOutcropConfig.count": "固定次数模式下每次运行打几朵花（每次 20/40 树脂）。",
    "autoDomainConfig.partyName": "留空则用一条龙 daily.json 里的 PartyName。",
    "autoDomainConfig.resinPriorityList": "按顺序消耗：浓缩树脂优先于原粹树脂。",
    "genshinStartConfig.linkedStartEnabled": "关掉 BetterGI 时一起关游戏。自动化期间建议开，手动玩的时候注意它会关你的游戏。",
    "scheduler.daily_time": "计划任务 HoYoDaily 的每日触发时间；保存后会自动同步到 Windows 计划任务。",
    "scheduler.min_uptime_minutes": "刚开机就跑容易冷启动失败（2026-11-09 事故：开机 7 分钟就跑，进游戏花了 6 分 50 秒，一条龙被取消）。",
    "scheduler.boot_wait_max_minutes": "等开机稳定最多等多久，超时也照样开跑。",
    "games.genshin.stall_minutes": "引擎进程还在、但日志这么久没有新内容 = 卡死，杀掉重来。",
    "games.genshin.party_name": "打秘境用的队伍名（写进 BetterGI 一条龙）。",
    "game_region": "cn=国服。掉登录时 OneDragon 用账号密码自动登回。",
    "account": "手机号或米游社账号。明文存在本机，不会进仓库。",
    "password": "明文保存。想加密可以让我加 DPAPI。",
    "pause_after_success": "关掉（false）才是跑完自动退出；开了会停在三月七界面等你点。",
    "merge_immersifier": "优先把开拓力合成沉浸器，会让『体力计划』没燃料可刷——想稳定刷本建议关掉。",
    "background_mode": "必须 false（前台模式）。后台模式在绝区零上截图会失败。",
    "LeyLineRunCount": "地脉花次数。每次 40 树脂时 6 次 = 240，超过早上的实际树脂，会空转；建议 5。",
    "PartyName": "打秘境用的队伍名，要和游戏里队伍名完全一致。",
}

IMPORTANT = {
    "bg_main": [
        ("genshinStartConfig.installPath", "游戏路径", "YuanShen.exe 完整路径"),
        ("genshinStartConfig.autoEnterGameEnabled", "自动进入游戏", "自动化启动后自动点进游戏"),
        ("genshinStartConfig.linkedStartEnabled", "联动退出", "关 BetterGI 时一起关游戏"),
        ("autoFightConfig.strategyName", "战斗策略", "脚本里没有你队伍的角色就会站着不动"),
        ("autoFightConfig.teamNames", "战斗队伍名", "留空 = 自动识别当前队伍"),
        ("scriptConfig.autoUpdateSubscribedScripts", "自动更新战斗脚本", "保持脚本认识新角色"),
        ("autoDomainConfig.partyName", "秘境队伍", "留空 = 用一条龙里的队伍"),
        ("autoLeyLineOutcropConfig.country", "地脉花国家", "0.66+ 已支持至冬"),
        ("autoLeyLineOutcropConfig.count", "地脉花次数", "40 树脂/次，注意别超过实际树脂"),
        ("autoLeyLineOutcropConfig.isResinExhaustionMode", "地脉花：树脂耗尽模式", "不推荐，会读错树脂"),
        ("autoPickConfig.enabled", "自动拾取", ""),
        ("autoSkipConfig.quicklySkipConversationsEnabled", "快速跳过对话", ""),
        ("captureMode", "截图模式", "出错时可试试 WGC"),
        ("otherConfig.autoRestartConfig", "失败自动重启", ""),
        ("commonConfig.screenshotEnabled", "运行结束截图", "排错时很有用"),
    ],
    "m7a": [
        ("game_path", "游戏路径", "StarRail.exe 完整路径"),
        ("use_reserved_trailblaze_power", "用后备开拓力", ""),
        ("use_fuel", "用燃料", ""),
        ("merge_immersifier", "优先合成沉浸器", "开了会挤掉刷本燃料"),
        ("daily_enable", "启用每日实训", ""),
        ("reward_enable", "启用奖励领取", ""),
        ("universe_enable", "模拟宇宙", ""),
        ("fight_enable", "历战余响", ""),
        ("forgottenhall_enable", "忘却之庭", ""),
        ("purefiction_enable", "虚构叙事", ""),
        ("apocalyptic_enable", "末日幻影", ""),
        ("activity_enable", "活动", ""),
        ("auto_set_resolution_enable", "自动改分辨率", "需要 1920x1080 才能识别"),
        ("pause_after_success", "成功后停住", "必须 false 才会自动退出"),
        ("after_finish", "结束后动作", "Exit = 关闭三月七"),
        ("exit_after_failure", "失败也退出", "建议 true，否则会一直挂着"),
        ("auto_update", "自动更新三月七", "升级可能改行为，谨慎"),
        ("notification_enable", "通知", ""),
        ("notify_winotify_enable", "Windows 系统通知", ""),
        ("loop_mode", "循环模式", ""),
        ("scheduled_time", "定时时间", "我们用计划任务，不用它自己的定时"),
        ("power_limit", "体力上限", ""),
        ("log_level", "日志级别", ""),
    ],
    "od_game": [
        ("background_mode", "后台模式", "必须 false"),
        ("background_gamepad_type", "后台手柄类型", ""),
        ("original_hdr_value", "HDR 原值", ""),
    ],
    "od_charge": [
        ("restore_charge", "发电站充电方式", "『使用储蓄电量』= 体力优先用电池"),
        ("double_reward", "双倍奖励", "有双倍活动时打开"),
        ("plan_list", "体力计划", "真正生效的清体力计划，逐条 plan_times / run_times"),
    ],
    "od_account": [
        ("game_path", "游戏路径", ""),
        ("account", "账号", ""),
        ("password", "密码", ""),
        ("game_region", "区服", "cn=国服"),
    ],
    "bg_daily": [
        ("PartyName", "打本队伍名", "要和游戏里的队伍名完全一致"),
        ("DomainName", "默认秘境", "『自动秘境』打哪个本"),
        ("WeeklyDomainEnabled", "打每周秘境", "周本（每周前几次有额外奖励）"),
        ("LeyLineRunCount", "地脉花次数", "40 树脂/次，别超过早上实际树脂（建议 5）"),
        ("LeyLineResinExhaustionMode", "地脉花：树脂耗尽模式", "不推荐，地图没渲染完会读成 0"),
        ("DailyRewardPartyName", "领每日奖励队伍", ""),
        ("MinResinToKeep", "至少保留的原粹树脂", "0 = 全部花光"),
        ("CompletionAction", "全部完成后", ""),
        ("CraftingBenchCountry", "合成台国家", ""),
        ("AdventurersGuildCountry", "冒险家协会国家", ""),
    ],
    "ours": [
        ("scheduler.daily_time", "每天几点跑", "HH:MM，会自动同步到计划任务"),
        ("scheduler.run_order", "三个游戏的顺序", ""),
        ("scheduler.min_uptime_minutes", "开机后等多久才跑", "防冷启动失败"),
        ("scheduler.boot_wait_max_minutes", "最多等多久", ""),
        ("scheduler.timeout_minutes", "单次总超时", ""),
    ],
}


def help_text(path, game=""):
    return HELP.get(path, "")


def first_str(d):
    """列表项分组标题里用的：从 dict 里挑一个最有代表性的字符串。"""
    if not isinstance(d, dict):
        return ""
    for k in ("name", "mission_name", "category_name", "label", "title", "id"):
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    for v in d.values():
        if isinstance(v, str) and v and len(v) <= 20:
            return v
    return ""