'use strict';
/* HoYo 每日自动化 · 配置中心 前端（无构建，纯原生 JS） */
(function () {
  var API = '/api';

  var S = {
    page: 'overview',
    summary: null,
    files: null,
    pending: new Map(),          // key: fid|path  -> {fid,path,value}
    advFid: 'ours',
    advMode: 'form',
    logName: 'daily',
    logLines: 220,
    logQ: '',
    logTimer: null,
    jobTimer: null,
    toolsTimer: null,
    treeCache: {},
    gs: null,
    ours: null
  };

  var NAV = [
    { sect: '概览' },
    { id: 'overview', title: '总览', sub: '今天跑没跑、下次什么时候跑，一眼看全', ic: '◎' },
    { sect: '三个游戏' },
    { id: 'genshin', title: '原神', sub: 'BetterGI 一条龙：任务开关、秘境、地脉花', ic: '✦' },
    { id: 'starrail', title: '崩坏：星穹铁道', sub: '三月七助手：清体力计划、每日、周常、通知', ic: '✧' },
    { id: 'zzz', title: '绝区零', sub: 'OneDragon：体力计划、战斗、账号', ic: '❖' },
    { sect: '系统' },
    { id: 'schedule', title: '定时与运行', sub: '每天几点跑、运行顺序、立即运行一次', ic: '⏱' },
    { id: 'accounts', title: '账号与登录', sub: '掉登录时自动填账号密码（绝不用验证码）', ic: '⌘' },
    { id: 'tools', title: '工具', sub: '下载 / 更新 / 单独启动三个上游程序', ic: '⤓' },
    { sect: '高级' },
    { id: 'advanced', title: '全部配置', sub: '三游所有原生配置文件的完整表单与原文', ic: '⚙' },
    { id: 'logs', title: '日志', sub: '出问题先看这里', ic: '▤' },
    { id: 'backups', title: '备份与恢复', sub: '每次保存都自动备份，随时回滚', ic: '⎘' }
  ];

  var DAYS = [['Monday', '周一'], ['Tuesday', '周二'], ['Wednesday', '周三'],
    ['Thursday', '周四'], ['Friday', '周五'], ['Saturday', '周六'], ['Sunday', '周日']];
  var COUNTRIES = ['蒙德', '璃月', '稻妻', '须弥', '枫丹', '纳塔', '至冬'];
  var LEY_TYPES = ['启示之花', '藏金之花'];

  /* ------------------------------------------------------------------ 基础 */
  function $(sel, root) { return (root || document).querySelector(sel); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = String(text);
    return n;
  }

  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function getJSON(p) {
    return fetch(API + p, { cache: 'no-store' }).then(function (r) { return r.json(); });
  }

  function postJSON(p, body) {
    return fetch(API + p, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  var toastTimer = null;
  function toast(msg, kind) {
    var t = $('#toast');
    t.textContent = String(msg || '');
    t.className = 'toast on' + (kind ? ' ' + kind : '');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = 'toast'; }, kind === 'err' ? 8000 : 4200);
  }

  function fail(r) {
    if (r && r.ok === false) {
      toast((r.error || '操作失败') + (r.detail ? '\n' + String(r.detail).split('\n')[0] : ''), 'err');
      return true;
    }
    return false;
  }

  function fidLabel(fid) {
    var f = (S.files || []).filter(function (x) { return x.id === fid; })[0];
    return f ? f.label : fid;
  }

  /* ------------------------------------------------------------------ 待保存状态 */
  function pv(fid, path, def) {
    var k = fid + '|' + path;
    return S.pending.has(k) ? S.pending.get(k).value : def;
  }

  function isPending(fid, path) { return S.pending.has(fid + '|' + path); }

  function setPending(fid, path, value) {
    S.pending.set(fid + '|' + path, { fid: fid, path: path, value: value });
    updateSaveBar();
  }

  function updateSaveBar() {
    var bar = $('#savebar');
    var n = S.pending.size;
    if (!n) { bar.className = 'savebar hidden'; return; }
    bar.className = 'savebar';
    var files = {};
    S.pending.forEach(function (o) { files[o.fid] = 1; });
    $('#saveText').textContent = n + ' 项未保存' + '（' + Object.keys(files).length + ' 个文件）';
  }

  function discardPending() {
    S.pending.clear();
    updateSaveBar();
    render();
    toast('已放弃未保存的修改');
  }

  async function saveAll() {
    if (!S.pending.size) return;
    var groups = {};
    S.pending.forEach(function (o) { (groups[o.fid] = groups[o.fid] || []).push(o); });
    var msgs = [], bad = false;
    var fids = Object.keys(groups);
    for (var i = 0; i < fids.length; i++) {
      var fid = fids[i], items = groups[fid], r;
      if (fid === 'accounts') {
        var payload = {};
        items.forEach(function (it) {
          var p = it.path.split('.');
          payload[p[0]] = payload[p[0]] || {};
          payload[p[0]][p[1]] = it.value;
        });
        r = await postJSON('/accounts', payload);
        if (fail(r)) { bad = true; continue; }
        msgs.push('账号已保存');
        continue;
      }
      if (fid === 'ours') {
        var dt = items.filter(function (x) { return x.path === 'scheduler.daily_time'; })[0];
        var rest = items.filter(function (x) { return x.path !== 'scheduler.daily_time'; });
        if (dt) {
          r = await postJSON('/schedule', { daily_time: dt.value });
          if (fail(r)) bad = true; else msgs.push(r.msg || '每日时间已保存');
        }
        if (rest.length) {
          r = await postJSON('/save', {
            fid: 'ours', note: '配置中心',
            ops: rest.map(function (x) { return { op: 'set', path: x.path, value: x.value }; })
          });
          if (fail(r)) bad = true; else msgs.push('总控配置已保存');
        }
        continue;
      }
      r = await postJSON('/save', {
        fid: fid, note: '配置中心',
        ops: items.map(function (x) { return { op: 'set', path: x.path, value: x.value }; })
      });
      if (fail(r)) { bad = true; continue; }
      msgs.push(fidLabel(fid) + ' 已保存' + (r.backup ? '（备份 ' + r.backup + '）' : ''));
      S.treeCache = {};
    }
    if (!bad) {
      S.pending.clear();
      updateSaveBar();
      S.summary = null;
      await render();
      toast(msgs.join('\n'), 'ok');
    } else {
      toast('部分内容保存失败，未保存的修改还留着', 'err');
    }
  }

  /* ------------------------------------------------------------------ 控件 */
  function control(fid, o, row) {
    var val = pv(fid, o.path, o.value);
    var dirty = isPending(fid, o.path);
    var t = o.type;

    if (o.readonly) {
      return el('span', 'badge dim', val === null || val === undefined ? 'null' : String(val));
    }

    function fire(v, ctl) {
      setPending(fid, o.path, v);
      if (ctl) ctl.classList.add('dirty');
      if (row) row.classList.add('dirty');
    }

    var ctl;
    if (t === 'bool') {
      ctl = el('button', 'switch');
      ctl.type = 'button';
      ctl.dataset.on = val ? '1' : '0';
      if (dirty) ctl.classList.add('dirty');
      ctl.onclick = function () {
        var on = ctl.dataset.on !== '1';
        ctl.dataset.on = on ? '1' : '0';
        fire(on, ctl);
      };
      return ctl;
    }
    if (t === 'int' || t === 'float') {
      ctl = el('input', 'w-sm');
      ctl.type = 'number';
      ctl.step = t === 'float' ? 'any' : '1';
      ctl.value = val === null || val === undefined ? '' : val;
      if (dirty) ctl.classList.add('dirty');
      ctl.onchange = function () {
        var n = parseFloat(ctl.value);
        if (isNaN(n)) { ctl.classList.add('bad'); toast('请输入数字', 'err'); return; }
        ctl.classList.remove('bad');
        fire(t === 'int' ? Math.round(n) : n, ctl);
      };
      return ctl;
    }
    if (t === 'text') {
      ctl = el('textarea', 'w-lg');
      ctl.value = val === null || val === undefined ? '' : String(val);
      if (dirty) ctl.classList.add('dirty');
      ctl.onchange = function () { fire(ctl.value, ctl); };
      return ctl;
    }
    if (t === 'list') {
      ctl = el('textarea', 'w-lg');
      ctl.value = JSON.stringify(val === undefined ? [] : val, null, 2);
      ctl.title = '数组，按 JSON 格式编辑';
      if (dirty) ctl.classList.add('dirty');
      ctl.onchange = function () {
        try {
          var arr = JSON.parse(ctl.value);
          if (!Array.isArray(arr)) throw new Error('不是数组');
          ctl.classList.remove('bad');
          fire(arr, ctl);
        } catch (e) {
          ctl.classList.add('bad');
          toast('格式不对（需要 JSON 数组）：' + e.message, 'err');
        }
      };
      return ctl;
    }
    if (t === 'null') {
      ctl = el('input', 'w-md');
      ctl.type = 'text';
      ctl.placeholder = 'null（填空即为 null）';
      ctl.value = '';
      ctl.onchange = function () { fire(ctl.value === '' ? null : ctl.value, ctl); };
      return ctl;
    }
    ctl = el('input', 'w-md');
    ctl.type = o.secret ? 'password' : 'text';
    ctl.value = val === null || val === undefined ? '' : String(val);
    ctl.autocomplete = 'off';
    if (dirty) ctl.classList.add('dirty');
    ctl.onchange = function () { fire(ctl.value, ctl); };
    return ctl;
  }

  function fieldRow(fid, o) {
    var row = el('div', 'row');
    row.dataset.search = ((o.label || '') + ' ' + (o.path || '') + ' ' + (o.help || '')).toLowerCase();
    var main = el('div', 'row-main');
    main.appendChild(el('div', 'row-label', o.label || o.path));
    if (o.help) main.appendChild(el('div', 'row-help', o.help));
    main.appendChild(el('div', 'row-path', o.path));
    row.appendChild(main);
    var ctl = el('div', 'row-ctl');
    ctl.appendChild(control(fid, o, row));
    row.appendChild(ctl);
    return row;
  }

  function selectBox(options, value, onchange) {
    var s = el('select');
    var list = options.slice();
    if (value && list.indexOf(value) < 0) list.unshift(value);
    list.forEach(function (o) {
      var op = el('option', null, o);
      op.value = o;
      s.appendChild(op);
    });
    s.value = value || list[0] || '';
    s.onchange = function () { onchange(s.value, s); };
    return s;
  }

  function switchBox(fid, path, value) {
    var v = pv(fid, path, value);
    var b = el('button', 'switch');
    b.type = 'button';
    b.dataset.on = v ? '1' : '0';
    if (isPending(fid, path)) b.classList.add('dirty');
    b.onclick = function () {
      var on = b.dataset.on !== '1';
      b.dataset.on = on ? '1' : '0';
      b.classList.add('dirty');
      setPending(fid, path, on);
    };
    return b;
  }

  function treeNodes(fid, nodes, host, depth) {
    nodes.forEach(function (n) {
      if (n.kind === 'group') {
        var d = el('details', 'grp');
        if (depth < 1) d.open = true;
        var sum = el('summary');
        sum.appendChild(el('span', null, n.label));
        sum.appendChild(el('span', 'badge dim', String(n.count != null ? n.count : n.children.length)));
        d.appendChild(sum);
        var body = el('div', 'grp-body');
        treeNodes(fid, n.children, body, depth + 1);
        d.appendChild(body);
        host.appendChild(d);
      } else {
        host.appendChild(fieldRow(fid, {
          path: n.path, label: n.label, help: n.help, type: n.type,
          value: n.value, secret: n.secret, readonly: n.readonly
        }));
      }
    });
  }

  function card(title, sub) {
    var c = el('div', 'card');
    if (title) c.appendChild(el('h2', null, title));
    if (sub) c.appendChild(el('p', 'sub', sub));
    return c;
  }

  function badge(text, kind) { return el('span', 'badge ' + (kind || ''), text); }

  function hint(text) { return el('div', 'hint', text); }

  function buttons(rows) {
    var wrap = el('div', 'btnrow');
    rows.forEach(function (r) {
      var b = el('button', 'btn' + (r.kind ? ' ' + r.kind : '') + (r.sm ? ' sm' : ''), r.text);
      b.type = 'button';
      b.onclick = r.onClick;
      wrap.appendChild(b);
    });
    return wrap;
  }

  function importantSection(fid, important, host, title) {
    if (!important || !important.length) return null;
    var c = card(title || '常用设置', '下面是最常改的几项；想改别的可以点卡片底部的『全部设置』。');
    important.forEach(function (o) { c.appendChild(fieldRow(fid, o)); });
    host.appendChild(c);
    return c;
  }

  /* ------------------------------------------------------------------ 导航与渲染 */
  function buildNav() {
    var nav = $('#nav');
    clear(nav);
    NAV.forEach(function (p) {
      if (p.sect) {
        nav.appendChild(el('div', 'sect', p.sect));
        return;
      }
      var a = el('a');
      a.dataset.page = p.id;
      a.appendChild(el('span', 'ic', p.ic));
      a.appendChild(el('span', null, p.title));
      a.onclick = function () { go(p.id); };
      nav.appendChild(a);
    });
    highlightNav();
  }

  function refreshFoot() {
    getJSON('/summary').then(function (s) {
      $('#footState').textContent = '每天 ' + (s.daily_time || '--:--') + ' 自动运行';
      if (s.task && s.task.next) $('#footState').title = '下次运行：' + s.task.next;
    }).catch(function () {
      $('#footState').textContent = '计划任务未就绪';
    });
  }

  function highlightNav() {
    var as = document.querySelectorAll('#nav a');
    for (var i = 0; i < as.length; i++) {
      as[i].className = as[i].dataset.page === S.page ? 'on' : '';
    }
  }

  function pageFromHash() {
    var h = (location.hash || '').replace(/^#\/?/, '');
    for (var i = 0; i < NAV.length; i++) if (NAV[i].id === h) return h;
    return '';
  }

  function go(page) {
    S.page = page;
    if (location.hash !== '#/' + page) {
      try { history.replaceState(null, '', '#/' + page); } catch (e) { location.hash = '#/' + page; }
    }
    $('#q').value = '';
    render();
    $('#view').scrollTop = 0;
  }

  async function render() {
    var p = NAV.filter(function (x) { return x.id === S.page; })[0] || NAV[1];
    $('#pageTitle').textContent = p.title;
    $('#pageSub').textContent = p.sub;
    highlightNav();
    if (S.logTimer) { clearInterval(S.logTimer); S.logTimer = null; }
    if (S.jobTimer) { clearInterval(S.jobTimer); S.jobTimer = null; }
    if (S.toolsTimer) { clearInterval(S.toolsTimer); S.toolsTimer = null; }
    var v = $('#view');
    clear(v);
    v.appendChild(el('div', 'hint', '读取中…'));
    try {
      if (p.id === 'overview') await pageOverview(v);
      else if (p.id === 'genshin') await pageGenshin(v);
      else if (p.id === 'starrail') await pageStarrail(v);
      else if (p.id === 'zzz') await pageZzz(v);
      else if (p.id === 'schedule') await pageSchedule(v);
      else if (p.id === 'accounts') await pageAccounts(v);
      else if (p.id === 'tools') await pageTools(v);
      else if (p.id === 'advanced') await pageAdvanced(v);
      else if (p.id === 'logs') await pageLogs(v);
      else if (p.id === 'backups') await pageBackups(v);
    } catch (e) {
      clear(v);
      var c = card('读取失败');
      c.appendChild(el('div', 'hint', String(e && e.message ? e.message : e)));
      v.appendChild(c);
    }
    applySearch();
    refreshFoot();
  }

  async function loadOurs() {
    if (!S.ours) S.ours = await getJSON('/ours');
    return S.ours;
  }

  async function loadTree(fid) {
    if (!S.treeCache[fid]) S.treeCache[fid] = await getJSON('/tree?fid=' + encodeURIComponent(fid));
    return S.treeCache[fid];
  }

  /* ------------------------------------------------------------------ 总览 */
  function gameBadge(last) {
    if (!last) return badge('还没跑过', 'dim');
    return badge(last.ok ? '成功' : '失败', last.ok ? 'ok' : 'err');
  }

  async function pageOverview(v) {
    clear(v);
    var s = await getJSON('/summary');
    S.summary = s;
    $('#footState').textContent = '每天 ' + (s.daily_time || '--:--') + ' 自动运行';

    var st = card('运行状态');
    var stats = el('div', 'stats');
    function stat(k, val, note) {
      var b = el('div', 'stat');
      b.appendChild(el('div', 'k', k));
      b.appendChild(el('div', 'v', val));
      if (note) b.appendChild(el('div', 'n', note));
      stats.appendChild(b);
    }
    stat('每天运行时间', s.daily_time || '--:--', s.weekday + ' · 计划任务');
    stat('下次运行', s.task && s.task.next ? s.task.next : '（读不到）', s.task && s.task.exists ? '任务已注册' : '任务未注册');
    stat('最近一次活动', s.last_activity || '（无记录）', '来自总控日志');
    stat('当前时间', (s.now || '').slice(11), s.now ? s.now.slice(0, 10) : '');
    st.appendChild(stats);
    var jr = el('div', 'hint mt8');
    jr.id = 'jobLine';
    st.appendChild(jr);
    v.appendChild(st);

    var gc = card('三个游戏', '上次结果来自总控日志里的『执行结束』记录。开关只控制每天自动运行时跑不跑它。');
    var g3 = el('div', 'grid g3');
    s.games.forEach(function (g) {
      var box = el('div', 'stat');
      var h = el('div', 'row');
      h.appendChild(el('div', 'row-label', g.name));
      var sw = switchBox('ours', 'games.' + g.key + '.enabled', g.enabled);
      h.appendChild(sw);
      box.appendChild(h);
      var line = el('div', 'mt8');
      line.appendChild(gameBadge(g.last));
      if (g.last && g.last.at) line.appendChild(el('span', 'hint', '  ' + g.last.at));
      box.appendChild(line);
      g3.appendChild(box);
    });
    gc.appendChild(g3);
    v.appendChild(gc);

    var rc = card('立即运行', '整轮跑需要管理员权限（会用计划任务启动，不弹 UAC）。单独跑某个游戏会直接开进程，第一次可能要过一次 UAC。');
    rc.appendChild(buttons([
      { text: '▶ 跑完整一轮', kind: 'primary', onClick: function () { runIt('all', this); } },
      { text: '只跑原神', onClick: function () { runIt('genshin', this); } },
      { text: '只跑崩铁', onClick: function () { runIt('starrail', this); } },
      { text: '只跑绝区零', onClick: function () { runIt('zzz', this); } }
    ]));
    v.appendChild(rc);

    var tc = card('工具', '三个上游程序是否已下载安装。缺的可以到『工具』页一键下载。');
    var chips = el('div', 'chips');
    s.tools.forEach(function (t) {
      chips.appendChild(badge(t.label + '：' + (t.installed ? '已安装' : '未安装'),
        t.installed ? 'ok' : 'warn'));
    });
    tc.appendChild(chips);
    v.appendChild(tc);

    updateJobLine(s.job);
    S.jobTimer = setInterval(async function () {
      try {
        var j = await getJSON('/job');
        updateJobLine(j);
      } catch (e) { /* 忽略 */ }
    }, 3000);
  }

  function updateJobLine(j) {
    var line = $('#jobLine');
    if (!line) return;
    if (!j) { line.textContent = ''; return; }
    if (j.running) {
      line.textContent = '正在运行：' + (j.mode === 'all' ? '完整一轮' : j.mode) +
        '，开始于 ' + (j.started || '') + '（' + (j.elapsed || 0) + ' 秒）';
    } else if (j.msg) {
      line.textContent = '上次手动运行：' + (j.msg || '') + (j.started ? '（' + j.started + ' 开始）' : '');
    } else {
      line.textContent = '';
    }
  }

  async function runIt(mode, btn) {
    var old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '启动中…'; }
    var r = await postJSON('/run', { mode: mode });
    if (btn) { btn.disabled = false; btn.textContent = old; }
    if (fail(r)) return;
    toast(r.msg || '已启动', 'ok');
    if (S.page === 'overview') {
      try { updateJobLine(await getJSON('/job')); } catch (e) { /* 忽略 */ }
    }
  }

  /* ------------------------------------------------------------------ 原神 */
  async function pageGenshin(v) {
    clear(v);
    var g = await getJSON('/genshin');
    S.gs = g;
    var ours = await loadOurs();

    var tc = card('一条龙任务', '按顺序执行。开关就是 BetterGI 一条龙里那 7 个任务。');
    g.tasks.forEach(function (t, i) {
      var row = el('div', 'row');
      row.dataset.search = t.name.toLowerCase();
      var main = el('div', 'row-main');
      var lab = el('div', 'row-label');
      lab.appendChild(el('span', null, (t.index >= 0 ? (t.index + 1) + '. ' : '') + t.name));
      main.appendChild(lab);
      main.appendChild(el('div', 'row-path', 'TaskEnabledList.' + t.guid));
      row.appendChild(main);
      var ctl = el('div', 'row-ctl');
      ctl.appendChild(switchBox('bg_daily', 'TaskEnabledList.' + t.guid, t.enabled));
      row.appendChild(ctl);
      tc.appendChild(row);
    });
    v.appendChild(tc);

    var want = { PartyName: 1, DomainName: 1, WeeklyDomainEnabled: 1, DailyRewardPartyName: 1 };
    var dc = card('秘境与队伍');
    g.fields.filter(function (f) { return want[f.key]; }).forEach(function (f) {
      dc.appendChild(fieldRow('bg_daily', { path: f.key, label: f.label, type: f.type, value: f.value }));
    });
    dc.appendChild(hint('队伍名要和游戏里队伍的名字完全一致；留空就用界面里当前选中的队伍。'));
    v.appendChild(dc);

    var lc = card('地脉花', '每天按周几决定跑不跑、跑哪种、去哪个国家。周一~周五按下面开关执行。');
    ['LeyLineRunCount', 'LeyLineResinExhaustionMode'].forEach(function (k) {
      var f = g.fields.filter(function (x) { return x.key === k; })[0];
      if (!f) return;
      var help = k === 'LeyLineResinExhaustionMode'
        ? '打开=一直刷到没树脂；关掉=只刷固定次数（推荐，树脂耗尽模式会在地图里 OCR 树脂图标而不稳）' : '';
      lc.appendChild(fieldRow('bg_daily', { path: f.key, label: f.label, type: f.type, value: f.value, help: help }));
    });
    var tb = el('table', 'tb');
    var thr = el('tr');
    ['周几', '跑不跑', '花', '国家'].forEach(function (h) { thr.appendChild(el('th', null, h)); });
    tb.appendChild(thr);
    g.days.forEach(function (d) {
      var tr = el('tr');
      tr.appendChild(el('td', null, d.cn));
      var td1 = el('td', 'c');
      td1.appendChild(switchBox('bg_daily', 'LeyLineRun' + d.key, d.enabled));
      tr.appendChild(td1);
      var td2 = el('td');
      var tp = pv('bg_daily', 'LeyLine' + d.key + 'Type', d.type);
      if (tp || d.enabled) {
        td2.appendChild(selectBox(LEY_TYPES, tp, function (val, ctl) {
          ctl.classList.add('dirty');
          setPending('bg_daily', 'LeyLine' + d.key + 'Type', val);
        }));
      } else {
        td2.appendChild(el('span', 'hint', '（按上方开关）'));
      }
      tr.appendChild(td2);
      var td3 = el('td');
      var cp = pv('bg_daily', 'LeyLine' + d.key + 'Country', d.country);
      if (cp || d.enabled) {
        td3.appendChild(selectBox(COUNTRIES, cp, function (val, ctl) {
          ctl.classList.add('dirty');
          setPending('bg_daily', 'LeyLine' + d.key + 'Country', val);
        }));
      }
      tr.appendChild(td3);
      tb.appendChild(tr);
    });
    lc.appendChild(tb);
    lc.appendChild(hint('『至冬』地脉花需要 BetterGI 0.66.0 以上（更早版本的至冬数据不全，会寻路失败）。'));
    v.appendChild(lc);

    var used = { PartyName: 1, DomainName: 1, WeeklyDomainEnabled: 1, DailyRewardPartyName: 1 };
    var oc = card('其它一条龙设置');
    g.fields.filter(function (f) { return !used[f.key]; }).forEach(function (f) {
      oc.appendChild(fieldRow('bg_daily', { path: f.key, label: f.label, type: f.type, value: f.value }));
    });
    v.appendChild(oc);

    v.appendChild(oursCard(ours, 'genshin', '我们自己的规则', '这里的 targets 决定『打哪个秘境、哪些天打』。'));
  }

  function oursCard(ours, key, title, sub) {
    var g = (ours.games || {})[key] || {};
    var c = card(title || '我们的设置', sub);
    Object.keys(g.fields || {}).forEach(function (k) {
      var f = g.fields[k];
      c.appendChild(fieldRow('ours', { path: 'games.' + key + '.' + k, label: f.label, type: f.type, value: f.value }));
    });
    if ((g.targets || []).length) {
      var tb = el('table', 'tb mt8');
      var thr = el('tr');
      ['目标', '细节'].forEach(function (h) { thr.appendChild(el('th', null, h)); });
      tb.appendChild(thr);
      g.targets.forEach(function (t) {
        var tr = el('tr');
        var name = (t.fields.filter(function (x) { return x.k === 'name'; })[0] || {}).v || '';
        tr.appendChild(el('td', null, name));
        var det = t.fields.filter(function (x) { return x.k !== 'name'; })
          .map(function (x) { return x.k + '=' + JSON.stringify(x.v); }).join('  ');
        tr.appendChild(el('td', null, det));
        tb.appendChild(tr);
      });
      c.appendChild(tb);
      c.appendChild(hint('这些明细在『全部配置 → 总控配置』里可以直接改。'));
    }
    if (!Object.keys(g.fields || {}).length && !(g.targets || []).length) {
      c.appendChild(hint('这个游戏在我们的配置里没有单独字段。'));
    }
    return c;
  }

  /* ------------------------------------------------------------------ 崩铁 */
  async function pageStarrail(v) {
    clear(v);
    var t = await loadTree('m7a');
    importantSection('m7a', t.important, v, '常用设置');
    var cc = card('全部设置', '崩铁的 config.yaml 有几百项，下面按分组折叠；也可以直接改原文。');
    cc.appendChild(buttons([
      { text: '展开/收起由你点分组标题', sm: true, onClick: function () { } },
      { text: '去『全部配置』页编辑原文', sm: true, onClick: function () { S.advFid = 'm7a'; S.advMode = 'raw'; go('advanced'); } }
    ]));
    var body = el('div', 'mt8');
    treeNodes('m7a', t.tree, body, 1);
    cc.appendChild(body);
    v.appendChild(cc);
    v.appendChild(oursCard(await loadOurs(), 'starrail', '我们自己的规则'));
  }

  /* ------------------------------------------------------------------ 绝区零 */
  async function pageZzz(v) {
    clear(v);
    var acc = await loadTree('od_account');
    var game = await loadTree('od_game');
    var charge = await loadTree('od_charge');
    var ours = await loadOurs();

    var c1 = card('账号与登录', '填了账号密码，掉登录时 OneDragon 会自己登进来。密码明文保存在本机 config 里，不会进仓库。');
    acc.important.forEach(function (o) { c1.appendChild(fieldRow('od_account', o)); });
    v.appendChild(c1);

    var c2 = card('游戏与窗口', '后台模式必须关闭（绝区零窗口受保护，后台模式会读不到画面）。');
    game.important.forEach(function (o) { c2.appendChild(fieldRow('od_game', o)); });
    v.appendChild(c2);

    var c3 = card('清电量计划', '这是绝区零真正执行的体力计划（不是我们 config 里的 zzz targets）。');
    charge.important.forEach(function (o) { c3.appendChild(fieldRow('od_charge', o)); });
    var d = el('details', 'grp mt8');
    var sum = el('summary');
    sum.appendChild(el('span', null, '展开完整计划（plan_list 每一条）'));
    d.appendChild(sum);
    var body = el('div', 'grp-body');
    treeNodes('od_charge', charge.tree, body, 1);
    d.appendChild(body);
    c3.appendChild(d);
    v.appendChild(c3);

    var c4 = card('其它配置');
    c4.appendChild(buttons([
      { text: '通知设置', sm: true, onClick: function () { S.advFid = 'od_notify'; S.advMode = 'form'; go('advanced'); } },
      { text: '实例列表', sm: true, onClick: function () { S.advFid = 'od_instance'; S.advMode = 'form'; go('advanced'); } }
    ]));
    v.appendChild(c4);

    var o = oursCard(ours, 'zzz', '我们自己的设置', '注意：这里的 targets 对绝区零不生效，真正生效的是上面的清电量计划。');
    v.appendChild(o);
  }

  /* ------------------------------------------------------------------ 定时与运行 */
  async function pageSchedule(v) {
    clear(v);
    var s = await getJSON('/summary');
    S.summary = s;
    var ours = await loadOurs();
    var sc = ours.scheduler || {};

    var c1 = card('每天几点跑', '保存后会同时改 Windows 计划任务。计划任务需要管理员权限才能改；没有权限时会先存配置，下次运行时程序自己再同步一次。');
    var row = el('div', 'row');
    var main = el('div', 'row-main');
    main.appendChild(el('div', 'row-label', '每日运行时间'));
    main.appendChild(el('div', 'row-help', '0-23 时；建议比平时起床时间早，跑完你正好用电脑'));
    main.appendChild(el('div', 'row-path', 'scheduler.daily_time'));
    row.appendChild(main);
    var ctl = el('div', 'row-ctl');
    var inp = el('input', 'w-sm');
    inp.type = 'time';
    inp.value = pv('ours', 'scheduler.daily_time', s.daily_time || '07:10');
    if (isPending('ours', 'scheduler.daily_time')) inp.classList.add('dirty');
    inp.onchange = function () {
      inp.classList.add('dirty');
      setPending('ours', 'scheduler.daily_time', inp.value);
    };
    ctl.appendChild(inp);
    row.appendChild(ctl);
    c1.appendChild(row);
    var cur = el('div', 'hint mt8');
    cur.textContent = '当前计划任务：' + (s.task && s.task.exists
      ? ((s.task.time || '?') + '，下次 ' + (s.task.next || '?'))
      : '还没注册');
    c1.appendChild(cur);
    v.appendChild(c1);

    var c2 = card('运行顺序与超时');
    Object.keys(sc).forEach(function (k) {
      if (k === 'daily_time') return;
      var f = sc[k];
      c2.appendChild(fieldRow('ours', { path: 'scheduler.' + k, label: f.label, type: f.type, value: f.value, help: f.help }));
    });
    if (sc.run_order) {
      c2.appendChild(hint('运行顺序是个数组，例如 ["genshin","starrail","zzz"]。'));
    }
    v.appendChild(c2);

    var c3 = card('立即运行', '整轮用计划任务启动（无 UAC）；单独跑某个游戏会直接开进程。');
    c3.appendChild(buttons([
      { text: '▶ 跑完整一轮', kind: 'primary', onClick: function () { runIt('all', this); } },
      { text: '只跑原神', onClick: function () { runIt('genshin', this); } },
      { text: '只跑崩铁', onClick: function () { runIt('starrail', this); } },
      { text: '只跑绝区零', onClick: function () { runIt('zzz', this); } }
    ]));
    var jl = el('div', 'hint mt8');
    jl.id = 'jobLine';
    c3.appendChild(jl);
    v.appendChild(c3);
    updateJobLine(s.job);
    S.jobTimer = setInterval(async function () {
      try { updateJobLine(await getJSON('/job')); } catch (e) { /* 忽略 */ }
    }, 3000);

    var c4 = card('说明');
    c4.appendChild(hint('· 开机后如果不到设定时间，程序自己会等；如果刚开机（运行时间不足 min_uptime_minutes），会先等系统稳定再跑。\n' +
      '· 一轮跑完会自动关游戏、把屏幕模式恢复成你自己玩的设置。\n' +
      '· 想看每次跑的详细过程，去『日志』页。'));
    v.appendChild(c4);
  }

  /* ------------------------------------------------------------------ 账号 */
  async function pageAccounts(v) {
    clear(v);
    var a = await getJSON('/accounts');
    var ours = await loadOurs();
    var c1 = card('账号与密码', '掉登录时程序会在登录界面自动填账号密码。滑块/图形验证码没法自动过，遇到会截图并提示你手动登一次。' +
      '密码明文保存在本机 config/accounts.yaml（已加进 .gitignore，不会进 GitHub）。');
    var tb = el('table', 'tb');
    var thr = el('tr');
    ['游戏', '账号', '密码', '掉登录自动登录', '每天自动跑'].forEach(function (h) {
      thr.appendChild(el('th', null, h));
    });
    tb.appendChild(thr);
    a.games.forEach(function (g) {
      var tr = el('tr');
      tr.appendChild(el('td', null, g.name));
      var td1 = el('td');
      var acc = el('input', 'w-md');
      acc.type = 'text';
      acc.placeholder = g.account || '（未填）';
      acc.autocomplete = 'off';
      acc.onchange = function () {
        if (!acc.value) return;
        acc.classList.add('dirty');
        setPending('accounts', g.game + '.account', acc.value);
      };
      td1.appendChild(acc);
      tr.appendChild(td1);
      var td2 = el('td');
      var pwd = el('input', 'w-md');
      pwd.type = 'password';
      pwd.placeholder = g.has_password ? '已保存（留空=不改）' : '未保存';
      pwd.autocomplete = 'new-password';
      pwd.onchange = function () {
        if (!pwd.value) return;
        pwd.classList.add('dirty');
        setPending('accounts', g.game + '.password', pwd.value);
      };
      td2.appendChild(pwd);
      tr.appendChild(td2);
      var td3 = el('td', 'c');
      var gf = ((ours.games || {})[g.game] || {}).fields || {};
      var al = gf.auto_login ? gf.auto_login.value : true;
      td3.appendChild(switchBox('ours', 'games.' + g.game + '.auto_login', al));
      tr.appendChild(td3);
      var td4 = el('td', 'c');
      var en = gf.enabled ? gf.enabled.value : true;
      td4.appendChild(switchBox('ours', 'games.' + g.game + '.enabled', en));
      tr.appendChild(td4);
      tb.appendChild(tr);
    });
    c1.appendChild(tb);
    c1.appendChild(hint('留空的输入框不会改动已保存的值。'));
    v.appendChild(c1);

    var c2 = card('怎么算『登录界面』');
    c2.appendChild(hint('程序不靠固定坐标：先截图，用 OCR 找『登录 / 进入游戏 / Login』这类文字和账号、密码输入框，' +
      '找到才动手；已经进游戏就什么都不做。所以不会在你玩的时候乱点。\n' +
      '失败截图存在 logs/login/ 下，方便排查。'));
    v.appendChild(c2);
  }

  /* ------------------------------------------------------------------ 工具 */
  async function pageTools(v) {
    clear(v);
    var t = await getJSON('/tools');
    var c = card('三个上游程序', '从官方 GitHub Release 下载（不复制别人的代码，只用官方发布包）。BetterGI 固定 0.66.0 并关闭了它自己的自动更新。');
    var g3 = el('div', 'grid g3');
    t.tools.forEach(function (x) {
      var box = el('div', 'stat');
      box.appendChild(el('div', 'k', x.game + ' · ' + x.label));
      var line = el('div', 'mt8');
      line.appendChild(badge(x.installed ? '已安装' : '未安装', x.installed ? 'ok' : 'warn'));
      if (x.tag) line.appendChild(el('span', 'hint', '  ' + x.tag));
      box.appendChild(line);
      box.appendChild(el('div', 'n mono', x.path));
      var b = el('div', 'btnrow mt8');
      var ib = el('button', 'btn sm', x.installed ? '重新下载/更新' : '下载安装');
      ib.type = 'button';
      ib.onclick = function () { installTool(x.key, ib); };
      b.appendChild(ib);
      var lb = el('button', 'btn sm ghost', '单独启动');
      lb.type = 'button';
      lb.onclick = function () { launchTool(x.key); };
      b.appendChild(lb);
      box.appendChild(b);
      g3.appendChild(box);
    });
    c.appendChild(g3);
    var st = el('div', 'hint mt12');
    st.id = 'toolState';
    c.appendChild(st);
    v.appendChild(c);
    updateToolState(t.state);

    S.toolsTimer = setInterval(async function () {
      try {
        var r = await getJSON('/tools');
        updateToolState(r.state);
        if (!r.state.running) { clearInterval(S.toolsTimer); S.toolsTimer = null; }
      } catch (e) { /* 忽略 */ }
    }, 2500);
  }

  function updateToolState(st) {
    var line = $('#toolState');
    if (!line || !st) return;
    if (st.running) {
      line.textContent = '正在处理：' + (st.tool || '') + ' ' + (st.phase || '') +
        (st.percent ? '（' + st.percent + '%）' : '');
    } else {
      line.textContent = st.phase ? ('上次：' + st.phase) : '';
    }
  }

  async function installTool(key, btn) {
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = '开始…';
    var r = await postJSON('/tools/install', { key: key });
    btn.disabled = false;
    btn.textContent = old;
    if (fail(r)) return;
    toast(r.msg || '已开始下载', 'ok');
    if (!S.toolsTimer) {
      S.toolsTimer = setInterval(async function () {
        try {
          var t = await getJSON('/tools');
          updateToolState(t.state);
          if (!t.state.running) { clearInterval(S.toolsTimer); S.toolsTimer = null; }
        } catch (e) { /* 忽略 */ }
      }, 2500);
    }
  }

  async function launchTool(key) {
    var r = await postJSON('/tools/launch', { key: key });
    if (fail(r)) return;
    toast(r.msg || '已启动', 'ok');
  }

  /* ------------------------------------------------------------------ 全部配置 */
  async function pageAdvanced(v) {
    clear(v);
    if (!S.files) {
      var f = await getJSON('/files');
      S.files = f.files || [];
    }
    var split = el('div', 'split');

    var left = card('配置文件');
    var list = el('div', 'filelist');
    var lastGroup = '';
    S.files.forEach(function (f) {
      if (f.group !== lastGroup) {
        list.appendChild(el('div', 'sect', f.group || '其它'));
        lastGroup = f.group;
      }
      var item = el('div', 'fileitem');
      item.dataset.fid = f.id;
      item.appendChild(el('span', 'nm', f.label));
      item.appendChild(el('span', 'tag', f.fmt));
      if (!f.exists) item.appendChild(badge('缺', 'err'));
      if (f.id === S.advFid) item.className = 'fileitem on';
      item.onclick = function () {
        S.advFid = f.id;
        pageAdvanced($('#view'));
      };
      list.appendChild(item);
    });
    left.appendChild(list);
    split.appendChild(left);

    var right = el('div');
    var meta = S.files.filter(function (x) { return x.id === S.advFid; })[0];
    var head = card(meta ? meta.label : S.advFid,
      meta ? (meta.rel + (meta.note ? ' · ' + meta.note : '')) : '');
    var tabs = el('div', 'tabs');
    [['form', '表单'], ['raw', '原文']].forEach(function (x) {
      var b = el('button', null, x[1]);
      b.type = 'button';
      if (S.advMode === x[0]) b.className = 'on';
      b.onclick = function () { S.advMode = x[0]; pageAdvanced($('#view')); };
      tabs.appendChild(b);
    });
    head.appendChild(tabs);
    head.appendChild(buttons([
      {
        text: '打开所在文件夹', sm: true, onClick: async function () {
          var r = await postJSON('/open', { fid: S.advFid });
          if (!fail(r)) toast('已打开');
        }
      }
    ]));
    right.appendChild(head);

    if (S.advMode === 'form') {
      var body = card('设置项');
      body.appendChild(el('div', 'hint', '读取中…'));
      right.appendChild(body);
      split.appendChild(right);
      v.appendChild(split);
      try {
        var t = await loadTree(S.advFid);
        clear(body);
        if (t.important && t.important.length) {
          body.appendChild(el('h2', null, '常用'));
          t.important.forEach(function (o) { body.appendChild(fieldRow(S.advFid, o)); });
          body.appendChild(el('div', 'hint mt12', '———————— 全部设置 ————————'));
        }
        var wrap = el('div');
        treeNodes(S.advFid, t.tree, wrap, 1);
        body.appendChild(wrap);
        applySearch();
      } catch (e) {
        clear(body);
        body.appendChild(el('div', 'hint', '读取失败：' + (e && e.message ? e.message : e)));
      }
      return;
    }

    var rawc = card('原文编辑', '改完点下面的『保存原文』。保存前会先做语法校验，不合法不会写盘。');
    rawc.appendChild(el('div', 'hint', '读取中…'));
    right.appendChild(rawc);
    split.appendChild(right);
    v.appendChild(split);
    var raw = await getJSON('/raw?fid=' + encodeURIComponent(S.advFid));
    clear(rawc);
    var ta = el('textarea', 'raw');
    ta.value = raw.text || '';
    rawc.appendChild(ta);
    rawc.appendChild(buttons([{
      text: '保存原文', kind: 'primary', onClick: async function () {
        var r = await postJSON('/raw', { fid: S.advFid, text: ta.value });
        if (fail(r)) return;
        S.treeCache = {};
        toast('已保存原文' + (r.backup ? '（备份 ' + r.backup + '）' : ''), 'ok');
        await render();
      }
    }]));
    rawc.appendChild(hint(raw.rel || ''));
  }

  /* ------------------------------------------------------------------ 日志 */
  async function pageLogs(v) {
    clear(v);
    var l = await getJSON('/logs');
    var c1 = card('日志来源');
    var chips = el('div', 'chips');
    l.logs.forEach(function (x) {
      var b = el('button', 'chip' + (S.logName === x.key ? ' on' : ''), x.title);
      b.type = 'button';
      b.title = x.exists ? '有日志' : '还没有日志文件';
      b.onclick = function () { S.logName = x.key; pageLogs($('#view')); };
      chips.appendChild(b);
    });
    c1.appendChild(chips);
    v.appendChild(c1);

    var c2 = card('内容');
    var bar = el('div', 'btnrow');
    var linesIn = el('input', 'w-sm');
    linesIn.type = 'number';
    linesIn.value = S.logLines;
    linesIn.title = '显示最后多少行';
    linesIn.onchange = function () {
      var n = parseInt(linesIn.value, 10);
      S.logLines = isNaN(n) ? 220 : Math.max(20, Math.min(3000, n));
      loadLog(body);
    };
    bar.appendChild(el('span', 'hint', '行数'));
    bar.appendChild(linesIn);
    var qIn = el('input', 'w-md');
    qIn.type = 'text';
    qIn.placeholder = '过滤关键字，例如 执行结束 / 失败 / 树脂';
    qIn.value = S.logQ;
    qIn.onchange = function () { S.logQ = qIn.value.trim(); loadLog(body); };
    bar.appendChild(qIn);
    bar.appendChild(buttons([
      { text: '↻ 刷新', sm: true, onClick: function () { loadLog(body); } },
      {
        text: '每 5 秒自动刷新', sm: true, onClick: function (ev) {
          var b = ev.target;
          if (S.logTimer) {
            clearInterval(S.logTimer);
            S.logTimer = null;
            b.textContent = '每 5 秒自动刷新';
            b.classList.remove('primary');
          } else {
            S.logTimer = setInterval(function () { loadLog(body); }, 5000);
            b.textContent = '停止自动刷新';
            b.classList.add('primary');
          }
        }
      }
    ]));
    c2.appendChild(bar);
    var info = el('div', 'hint mt8');
    info.id = 'logInfo';
    c2.appendChild(info);
    var body = el('pre', 'log');
    body.textContent = '读取中…';
    c2.appendChild(body);
    v.appendChild(c2);
    await loadLog(body);
  }

  async function loadLog(pre) {
    if (!pre) return;
    var url = '/log?name=' + encodeURIComponent(S.logName) + '&lines=' + S.logLines +
      '&q=' + encodeURIComponent(S.logQ);
    try {
      var r = await getJSON(url);
      var info = document.getElementById('logInfo');
      if (info) {
        info.textContent = (r.file ? r.file + ' · ' : '') + (r.mtime ? '最后修改 ' + r.mtime : '') +
          (r.error ? ' · ' + r.error : '');
      }
      pre.textContent = r.text || '（空）';
      pre.scrollTop = pre.scrollHeight;
    } catch (e) {
      pre.textContent = '读取失败：' + e;
    }
  }

  /* ------------------------------------------------------------------ 备份 */
  async function pageBackups(v) {
    clear(v);
    var b = await getJSON('/backups');
    if (!S.files) {
      var f = await getJSON('/files');
      S.files = f.files || [];
    }
    var c = card('自动备份', '每次保存前都会把原文件备份到 config/backup/，每个文件保留最近 30 份。');
    var tb = el('table', 'tb');
    var thr = el('tr');
    ['时间', '文件', '大小', ''].forEach(function (h) { thr.appendChild(el('th', null, h)); });
    tb.appendChild(thr);
    if (!b.backups.length) {
      var tr0 = el('tr');
      var td0 = el('td');
      td0.colSpan = 4;
      td0.appendChild(hint('还没有备份。'));
      tr0.appendChild(td0);
      tb.appendChild(tr0);
    }
    b.backups.forEach(function (x) {
      var tr = el('tr');
      tr.appendChild(el('td', null, x.mtime));
      tr.appendChild(el('td', null, x.name));
      tr.appendChild(el('td', null, (x.size / 1024).toFixed(0) + ' KB'));
      var td = el('td');
      var btn = el('button', 'btn sm danger', '恢复');
      btn.type = 'button';
      btn.onclick = async function () {
        if (!confirm('用这份备份覆盖当前文件？\n' + x.name)) return;
        var r = await postJSON('/restore', { name: x.name });
        if (fail(r)) return;
        S.treeCache = {};
        toast('已恢复：' + x.name, 'ok');
        render();
      };
      td.appendChild(btn);
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    c.appendChild(tb);
    v.appendChild(c);
  }

  /* ------------------------------------------------------------------ 搜索 */
  function applySearch() {
    var q = ($('#q').value || '').trim().toLowerCase();
    var rows = document.querySelectorAll('#view .row');
    for (var i = 0; i < rows.length; i++) {
      var hay = rows[i].dataset.search || '';
      rows[i].classList.toggle('hidden', !!q && hay.indexOf(q) < 0);
    }
    if (q) {
      var dets = document.querySelectorAll('#view details.grp');
      for (var j = 0; j < dets.length; j++) dets[j].open = true;
    }
  }

  /* ------------------------------------------------------------------ 启动 */
  var BOOT_PAGE = pageFromHash();

  function boot() {
    buildNav();
    if (BOOT_PAGE) S.page = BOOT_PAGE;
    window.addEventListener('hashchange', function () {
      var p = pageFromHash();
      if (p && p !== S.page) go(p);
    });
    $('#q').addEventListener('input', applySearch);
    $('#btnReload').onclick = function () {
      if (S.pending.size && !confirm('有 ' + S.pending.size + ' 项未保存，刷新会丢掉，继续？')) return;
      S.pending.clear();
      updateSaveBar();
      S.treeCache = {};
      S.files = null;
      S.ours = null;
      render();
    };
    $('#btnSave').onclick = saveAll;
    $('#btnDiscard').onclick = function () {
      if (S.pending.size && !confirm('放弃 ' + S.pending.size + ' 项未保存的修改？')) return;
      discardPending();
    };
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveAll();
      }
      if (e.key === '/' && document.activeElement && document.activeElement.tagName === 'BODY') {
        e.preventDefault();
        $('#q').focus();
      }
    });
    window.addEventListener('beforeunload', function (e) {
      if (S.pending.size) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
    render();
  }

  boot();
})();