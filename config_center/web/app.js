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
    ours: null,
    options: null,
    updates: null,
    planDraft: null,
    powerDraft: null
  };

  var NAV = [
    { sect: '概览' },
    { id: 'setup', title: '开始使用', sub: '第一次用按这里一步步来；只玩其中几个游戏也能用', ic: '①' },
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
  var comboSeq = 0;

  /* 把 options 摊平成 [{v,l,g}]：支持字符串、{value,label}、{group,items} 三种写法 */
  function flattenOptions(list) {
    var out = [];
    (list || []).forEach(function (o) {
      if (o === null || o === undefined) return;
      if (typeof o === 'string' || typeof o === 'number') {
        out.push({ v: String(o), l: String(o), g: '' });
      } else if (o.items) {
        (o.items || []).forEach(function (it) {
          var v = (it !== null && typeof it === 'object') ? (it.value !== undefined ? it.value : it.label) : it;
          var l = (it !== null && typeof it === 'object') ? (it.label || it.value) : it;
          out.push({ v: String(v), l: String(l), g: o.group || '' });
        });
      } else {
        var vv = o.value !== undefined ? o.value : o.label;
        out.push({ v: String(vv), l: String(o.label || o.value), g: o.group || '' });
      }
    });
    return out;
  }

  function optionsSelect(opts, val, dirty, onPick) {
    var s = el('select');
    var groups = [], seen = {};
    opts.forEach(function (o) { if (o.g && !seen[o.g]) { seen[o.g] = 1; groups.push(o.g); } });
    function addOpt(parent, o) {
      var op = el('option', null, o.l);
      op.value = o.v;
      parent.appendChild(op);
    }
    if (groups.length) {
      opts.filter(function (o) { return !o.g; }).forEach(function (o) { addOpt(s, o); });
      groups.forEach(function (g) {
        var og = el('optgroup');
        og.label = g;
        opts.filter(function (o) { return o.g === g; }).forEach(function (o) { addOpt(og, o); });
        s.appendChild(og);
      });
    } else {
      opts.forEach(function (o) { addOpt(s, o); });
    }
    var cur = (val === null || val === undefined) ? '' : String(val);
    var has = opts.some(function (o) { return o.v === cur; });
    if (!has && cur) {  // 大小写/前后空格不一致（如 cpu vs CPU）也算同一个
      var low = cur.trim().toLowerCase();
      var same = opts.filter(function (o) { return o.v.trim().toLowerCase() === low; })[0];
      if (same) { cur = same.v; has = true; }
    }
    if (cur && !has) {
      var extra = el('option', null, cur + '（当前值，不在上游列表里）');
      extra.value = cur;
      s.insertBefore(extra, s.firstChild);
    }
    s.value = cur || (opts.length ? opts[0].v : '');
    if (dirty) s.classList.add('dirty');
    s.onchange = function () { onPick(s.value, s); };
    return s;
  }

  function comboInput(opts, val, dirty, onPick) {
    var id = 'dl' + (comboSeq++);
    var wrap = el('div', 'combo');
    var inp = el('input', 'w-md');
    inp.type = 'text';
    inp.value = (val === null || val === undefined) ? '' : String(val);
    inp.setAttribute('list', id);
    inp.autocomplete = 'off';
    if (dirty) inp.classList.add('dirty');
    inp.onchange = function () { onPick(inp.value, inp); };
    var dl = el('datalist');
    dl.id = id;
    opts.forEach(function (o) {
      var op = el('option');
      op.value = o.v;
      if (o.l && o.l !== o.v) op.label = o.l;
      dl.appendChild(op);
    });
    wrap.appendChild(inp);
    wrap.appendChild(dl);
    return wrap;
  }

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

    // 上游有明确选项的字段：给下拉/可填可选的输入框，别让人手打
    var optList = (o.ui && !o.secret) ? flattenOptions(o.options) : [];
    if (optList.length) {
      if (o.ui === 'select') {
        return optionsSelect(optList, val, dirty, fire);
      }
      return comboInput(optList, val, dirty, fire);
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

  /* 闹钟式时间选择：时/分两个下拉 + 常用时间一键选（不再是原生 time 控件的丑样子） */
  function alarmPicker(val, dirty, onPick) {
    var wrap = el('div', 'alarm');
    var cur = String(val || '07:00');
    var hm = cur.split(':');
    var hh = parseInt(hm[0], 10); if (isNaN(hh)) hh = 7;
    var mm = parseInt(hm[1], 10); if (isNaN(mm)) mm = 0;

    var hs = el('select', 'alarm-h');
    for (var i = 0; i < 24; i++) {
      var o = el('option', null, (i < 10 ? '0' : '') + i);
      o.value = String(i);
      hs.appendChild(o);
    }
    hs.value = String(hh);
    var ms = el('select', 'alarm-m');
    for (var j = 0; j < 60; j++) {
      var o2 = el('option', null, (j < 10 ? '0' : '') + j);
      o2.value = String(j);
      ms.appendChild(o2);
    }
    ms.value = String(mm);
    var colon = el('span', 'alarm-colon', ':');
    var tail = el('span', 'alarm-tail', '每天');
    if (dirty) { hs.classList.add('dirty'); ms.classList.add('dirty'); }

    function emit() { onPick(pad2(hs.value) + ':' + pad2(ms.value)); }
    function pad2(x) { x = String(x); return x.length < 2 ? '0' + x : x; }
    hs.onchange = emit;
    ms.onchange = emit;
    wrap.appendChild(hs);
    wrap.appendChild(colon);
    wrap.appendChild(ms);
    wrap.appendChild(tail);

    var presets = el('div', 'chips mt8');
    [['06:00', '早起'], ['06:30', ''], ['07:00', ''], ['07:10', '现在'], ['07:30', ''],
      ['08:00', '上班'], ['12:00', '午休'], ['18:00', ''], ['22:00', '睡前']].forEach(function (p) {
      var b = el('button', 'chip' + (p[0] === cur ? ' on' : ''), p[0] + (p[1] ? ' ' + p[1] : ''));
      b.type = 'button';
      b.onclick = function () {
        var a = p[0].split(':');
        hs.value = String(parseInt(a[0], 10));
        ms.value = String(parseInt(a[1], 10));
        var chips = wrap.parentNode ? wrap.parentNode.querySelectorAll('.chip') : [];
        for (var k = 0; k < chips.length; k++) chips[k].classList.remove('on');
        b.classList.add('on');
        emit();
      };
      presets.appendChild(b);
    });
    var box = el('div');
    box.appendChild(wrap);
    box.appendChild(presets);
    return box;
  }

  /* 有序列表编辑器：上下移 + 开关。items: [{id,label,sub,enabled,onToggle?}] */
  function orderEditor(items, onMove, onToggle) {
    var wrap = el('div', 'orderlist');
    items.forEach(function (it, i) {
      var row = el('div', 'orow');
      row.dataset.search = ((it.label || '') + ' ' + (it.sub || '')).toLowerCase();
      row.appendChild(el('span', 'onum', String(i + 1)));
      var main = el('div', 'orow-main');
      main.appendChild(el('div', 'row-label', it.label || it.id));
      if (it.sub) main.appendChild(el('div', 'row-path', it.sub));
      row.appendChild(main);
      if (onToggle && it.enabled !== undefined) {
        var sw = el('button', 'switch');
        sw.type = 'button';
        sw.dataset.on = it.enabled ? '1' : '0';
        sw.onclick = function () {
          var on = sw.dataset.on !== '1';
          sw.dataset.on = on ? '1' : '0';
          sw.classList.add('dirty');
          onToggle(i, on);
        };
        row.appendChild(sw);
      }
      var btns = el('div', 'obtns');
      [['↑', -1], ['↓', 1]].forEach(function (d) {
        var b = el('button', 'btn sm ghost', d[0]);
        b.type = 'button';
        b.disabled = (d[1] < 0 && i === 0) || (d[1] > 0 && i === items.length - 1);
        b.onclick = function () { onMove(i, i + d[1]); };
        btns.appendChild(b);
      });
      row.appendChild(btns);
      wrap.appendChild(row);
    });
    return wrap;
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
        host.appendChild(fieldRow(fid, n));
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
      if (p.id === 'setup') await pageSetup(v);
      else if (p.id === 'overview') await pageOverview(v);
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

  async function loadOptions() {
    if (!S.options) {
      try { S.options = await getJSON('/options'); } catch (e) { S.options = {}; }
    }
    return S.options;
  }

  function groupBlock(fid, n, open) {
    var d = el('details', 'grp');
    d.open = !!open;
    var sum = el('summary');
    sum.appendChild(el('span', null, n.label || n.name));
    sum.appendChild(el('span', 'badge dim', String(n.count != null ? n.count : (n.children || []).length)));
    d.appendChild(sum);
    var body = el('div', 'grp-body');
    (n.children || []).forEach(function (c) {
      if (c.kind === 'group') body.appendChild(groupBlock(fid, c, false));
      else body.appendChild(fieldRow(fid, c));
    });
    d.appendChild(body);
    return d;
  }

  async function loadUpdates(force) {
    if (!force && S.updates) return S.updates;
    try {
      S.updates = await getJSON('/updates' + (force ? '?force=1' : ''));
    } catch (e) {
      S.updates = { tools: [], error: String(e) };
    }
    return S.updates;
  }

  function findNode(nodes, name) {
    var list = nodes || [];
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (n.name === name) return n;
      if (n.children) {
        var r = findNode(n.children, name);
        if (r) return r;
      }
    }
    return null;
  }

  function walkFields(nodes, out) {
    var list = nodes || [];
    out = out || [];
    list.forEach(function (n) {
      if (n.kind === 'group') walkFields(n.children, out);
      else if (n.kind === 'field') out.push(n);
    });
    return out;
  }

  async function loadTree(fid) {
    if (!S.treeCache[fid]) S.treeCache[fid] = await getJSON('/tree?fid=' + encodeURIComponent(fid));
    return S.treeCache[fid];
  }

  /* ------------------------------------------------------------------ 开始使用 */
  async function pageSetup(v) {
    clear(v);
    var st = await getJSON('/setup');
    var PAGE_OF = { tools: 'tools', schedule: 'schedule', accounts: 'accounts',
      genshin: 'genshin', starrail: 'starrail', zzz: 'zzz' };

    var head = card('欢迎：一次装好，之后每天自动跑',
      '这个配置中心管三个游戏：原神（BetterGI）、崩坏：星穹铁道（三月七助手）、绝区零（OneDragon）。' +
      '你只玩其中几个也完全可以 —— 先把「只玩哪几个游戏」定下来，其余按下面清单走。');
    var stat = el('div', 'stats');
    function st1(k, val, note) {
      var b = el('div', 'stat');
      b.appendChild(el('div', 'k', k));
      b.appendChild(el('div', 'v', val));
      if (note) b.appendChild(el('div', 'n', note));
      stat.appendChild(b);
    }
    st1('每天跑的时间', st.daily_time || '（还没设）', '像上闹钟一样选几点几分');
    st1('清单进度', String(st.total) + ' 步', st.ready ? '都做完了' : '还差 ' + st.total + ' 步');
    st1('当前时间', (st.now || '').slice(11), (st.now || '').slice(0, 10));
    var enabledCnt = (st.games || []).filter(function (g) { return g.enabled; }).length;
    st1('要跑的游戏', enabledCnt + ' 个', enabledCnt === 0 ? '一个都没开，不会自动跑' : '关掉的不会跑');
    head.appendChild(stat);
    v.appendChild(head);

    var gc = card('我玩哪几个游戏', '关掉的那个就不会被自动跑，也不影响剩下的。三个都关就等于不跑，' +
      '这时候「帮我下载它的工具」也别做。');
    var g3 = el('div', 'grid g3');
    st.games.forEach(function (g) {
      var box = el('div', 'stat');
      var h = el('div', 'row');
      h.appendChild(el('div', 'row-label', g.name));
      h.appendChild(switchBox('ours', 'games.' + g.key + '.enabled', g.enabled));
      box.appendChild(h);
      var l1 = el('div', 'mt8');
      l1.appendChild(badge(g.installed ? g.tool_label + ' 已装' : g.tool_label + ' 未装', g.installed ? 'ok' : 'warn'));
      box.appendChild(l1);
      box.appendChild(el('div', 'hint mt8', g.has_path ? ('游戏路径：' + g.path) : '游戏路径还没填/不存在'));
      g3.appendChild(box);
    });
    gc.appendChild(g3);
    v.appendChild(gc);

    var lc = card('还差哪些步骤', '做完一项就自动打勾（除了手动跑一次那项，要真的跑成功才算）。');
    st.steps.forEach(function (s, i) {
      var row = el('div', 'row');
      var main = el('div', 'row-main');
      var lab = el('div', 'row-label steplab');
      lab.appendChild(el('span', 'onum', String(i + 1)));
      lab.appendChild(el('span', null, ' ' + s.title));
      main.appendChild(lab);
      main.appendChild(el('div', 'row-help', s.hint || ''));
      row.appendChild(main);
      var ctl = el('div', 'row-ctl');
      ctl.appendChild(badge(s.done ? '已完成' : '待做', s.done ? 'ok' : 'warn'));
      var b = el('button', 'btn sm', '去处理');
      b.type = 'button';
      b.onclick = function () { go(PAGE_OF[s.page] || s.page); };
      ctl.appendChild(b);
      row.appendChild(ctl);
      lc.appendChild(row);
    });
    v.appendChild(lc);

    var nc = card('第一次跑之前，必须知道的几件事');
    ['· 每天到点由 Windows 计划任务启动（任务名 HoYoDaily），跑完自动关游戏、把屏幕模式恢复成你自己玩的设置。',
      '· 你要做的只有一件事：偶尔确认游戏还能登录。掉登录时程序会用你填的账号密码自动登（绝不用手机验证码），滑块验证码挡路就只能手动登一次。',
      '· BetterGI 官方就是需要管理员权限的，第一次跑之前留意一下有没有 UAC 弹窗没点。',
      '· 想先验一个游戏：去「定时与运行」点「只跑原神 / 只跑崩铁 / 只跑绝区零」，比等第二天早上快。'
    ].forEach(function (line) { nc.appendChild(hint(line)); });
    v.appendChild(nc);

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

    var tc = card('工具', '三个上游程序是否已安装、有没有新版。缺的可以到『工具』页一键下载/更新。');
    var chips = el('div', 'chips');
    s.tools.forEach(function (t) {
      chips.appendChild(badge(t.label + '：' + (t.installed ? '已安装' : '未安装'),
        t.installed ? 'ok' : 'warn'));
    });
    tc.appendChild(chips);
    var upLine = el('div', 'hint mt8');
    upLine.textContent = '正在检查上游版本…';
    tc.appendChild(upLine);
    v.appendChild(tc);
    loadUpdates(false).then(function (u) {
      if (!document.body.contains(upLine)) return;
      var rows = (u && u.tools) || [];
      if (!rows.length) {
        upLine.textContent = '版本检查失败' + (u && u.error ? '：' + u.error : '');
        return;
      }
      clear(upLine);
      upLine.appendChild(el('span', 'hint', '已装 / 最新：'));
      rows.forEach(function (r) {
        var txt = ' ' + r.label + ' ' + (r.installed || '未记录') + (r.latest ? ' → ' + r.latest : '');
        upLine.appendChild(badge(txt, r.has_update === true ? 'warn' : 'dim'));
      });
      if (rows.some(function (r) { return r.has_update === true; })) {
        upLine.appendChild(el('span', 'hint', '（有新版，去『工具』页更新）'));
      }
    });

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
    var opt = (await loadOptions()) || {};
    var gs = opt.genshin || {};
    var COUNTRIES = (gs.countries && gs.countries.length) ? gs.countries
      : ['蒙德', '璃月', '稻妻', '须弥', '枫丹', '纳塔', '挪德卡莱', '至冬'];
    var LEY_TYPES = (gs.leyline_types && gs.leyline_types.length) ? gs.leyline_types : ['启示之花', '藏金之花'];

    // 一条龙 daily.json 的全部字段（带下拉选项），按名字索引
    var bt = await loadTree('bg_daily');
    var dailyFields = walkFields(bt.tree);
    var byName = {};
    dailyFields.forEach(function (n) { byName[n.name] = n; });
    function withNode(f) {
      var o = { path: f.key, label: f.label, type: f.type, value: f.value };
      var n = byName[f.key];
      if (n) {
        if (n.ui) o.ui = n.ui;
        if (n.options) o.options = n.options;
        if (n.opt_note) o.opt_note = n.opt_note;
        if (n.help) o.help = n.help;
      }
      return o;
    }

    // 一条龙任务：顺序（TaskOrder）+ 开关（TaskEnabledList），两样都能改
    var taskByGuid = {};
    g.tasks.forEach(function (t) { taskByGuid[t.guid] = t; });
    var orderGuids = g.tasks.filter(function (t) { return t.index >= 0; })
      .sort(function (a, b) { return a.index - b.index; })
      .map(function (t) { return t.guid; });
    g.tasks.forEach(function (t) { if (orderGuids.indexOf(t.guid) < 0) orderGuids.push(t.guid); });

    var tc = card('一条龙任务：先打哪个、打不打',
      '↑ ↓ 调顺序（对应 daily.json 的 TaskOrder），右边的开关是打不打（TaskEnabledList）。' +
      '关着的任务在一条龙里就是「跳过」。');
    var taskHolder = el('div');
    function curEnabled(guid) {
      var t = taskByGuid[guid] || {};
      if (isPending('bg_daily', 'TaskEnabledList.' + guid)) {
        return !!pv('bg_daily', 'TaskEnabledList.' + guid, t.enabled);
      }
      return !!t.enabled;
    }
    function rebuildTasks() {
      clear(taskHolder);
      taskHolder.appendChild(orderEditor(orderGuids.map(function (guid) {
        var t = taskByGuid[guid] || { name: guid };
        return { id: guid, label: t.name, sub: 'TaskEnabledList.' + guid, enabled: curEnabled(guid) };
      }), function (from, to) {
        if (to < 0 || to >= orderGuids.length) return;
        var mv = orderGuids.splice(from, 1)[0];
        orderGuids.splice(to, 0, mv);
        setPending('bg_daily', 'TaskOrder', orderGuids.slice());
        rebuildTasks();
      }, function (i, on) {
        var guid = orderGuids[i];
        setPending('bg_daily', 'TaskEnabledList.' + guid, on);
        rebuildTasks();
      }));
    }
    rebuildTasks();
    tc.appendChild(taskHolder);
    tc.appendChild(hint('BetterGI 界面里也能改这两样，界面里的设置优先级更高（我们只在保存时按你的选择写一次）。'));
    v.appendChild(tc);

    var want = { PartyName: 1, DomainName: 1, WeeklyDomainEnabled: 1, DailyRewardPartyName: 1 };
    var dMeta = gs.domain_meta || {};
    var dc = card('秘境与队伍', '秘境名从 BetterGI 的传送点数据里读（按类型分组、后面跟着国家区域），也可以自己填。');
    var detail = el('div', 'detail');
    function showDomain(name) {
      var d = dMeta[name];
      clear(detail);
      if (!d) {
        detail.textContent = name ? ('「' + name + '」查不到资料：可能是一次性秘境、名字抄错，或者上游数据里没有这个点。') : '';
        detail.className = 'detail warn';
        return;
      }
      detail.className = 'detail';
      detail.appendChild(el('span', 'dname', name));
      detail.appendChild(el('span', 'dtype', d.type_cn || d.type || ''));
      detail.appendChild(el('span', 'drule', d.rule || ''));
      if (d.country) detail.appendChild(el('span', 'dloc', d.country + (d.areas && d.areas.length ? ' · ' + d.areas.join('、') : '')));
    }
    g.fields.filter(function (f) { return want[f.key]; }).forEach(function (f) {
      var r = fieldRow('bg_daily', withNode(f));
      dc.appendChild(r);
      if (f.key === 'DomainName') {
        var inp = r.querySelector('input');
        if (inp) {
          inp.addEventListener('input', function () { showDomain(inp.value); });
          inp.addEventListener('change', function () { showDomain(inp.value); });
        }
        dc.appendChild(detail);
        showDomain(pv('bg_daily', 'DomainName', f.value));
      }
    });
    dc.appendChild(hint('队伍名要和游戏里队伍的名字完全一致；留空就用界面里当前选中的队伍。' +
      '原神官方没有把秘境掉落写进任何本地数据，所以这里只给类型和开放规则，不编套装名。'));
    v.appendChild(dc);

    var lc = card('地脉花', '每天按周几决定跑不跑、跑哪种、去哪个国家。周一~周日分别设置。');
    var LEY_HELP = {
      LeyLineResinExhaustionMode: '打开=一直刷到没树脂；关掉=只刷上面写死的次数（推荐，树脂耗尽模式会在地图里 OCR 树脂图标而不稳）',
      LeyLineOneDragonMode: '打开=地脉花按一条龙方式跑（不再单独领奖、不买树脂）',
      LeyLineOpenModeCountMin: '打开=只按最小次数判断'
    };
    ['LeyLineRunCount', 'LeyLineResinExhaustionMode', 'LeyLineOneDragonMode', 'LeyLineOpenModeCountMin'].forEach(function (k) {
      var f = g.fields.filter(function (x) { return x.key === k; })[0];
      if (!f) return;
      var o = withNode({ key: k, label: f.label, type: f.type, value: f.value });
      if (LEY_HELP[k]) o.help = LEY_HELP[k];
      lc.appendChild(fieldRow('bg_daily', o));
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
      td2.appendChild(optionsSelect(LEY_TYPES.map(function (x) { return { v: x, l: x, g: '' }; }), tp, false, function (val, ctl) {
        ctl.classList.add('dirty');
        setPending('bg_daily', 'LeyLine' + d.key + 'Type', val);
      }));
      tr.appendChild(td2);
      var td3 = el('td');
      var cp = pv('bg_daily', 'LeyLine' + d.key + 'Country', d.country);
      td3.appendChild(optionsSelect(COUNTRIES.map(function (x) { return { v: x, l: x, g: '' }; }), cp, false, function (val, ctl) {
        ctl.classList.add('dirty');
        setPending('bg_daily', 'LeyLine' + d.key + 'Country', val);
      }));
      tr.appendChild(td3);
      tb.appendChild(tr);
    });
    lc.appendChild(tb);
    lc.appendChild(hint('『至冬』地脉花需要 BetterGI 0.66.0 以上；寻路失败会记 WARNING，不判整轮失败。'));
    v.appendChild(lc);

    var used = { PartyName: 1, DomainName: 1, WeeklyDomainEnabled: 1, DailyRewardPartyName: 1 };
    var bossKeys = [];
    dailyFields.forEach(function (n) {
      if (/^AutoBoss/.test(n.name) && !used[n.name]) bossKeys.push(n.name);
    });
    if (bossKeys.length) {
      var bc = card('自动首领讨伐', 'daily.json 里 AutoBoss* 这一组。首领名、策略、队伍都给的是下拉，次数/复活次数是数字。');
      bossKeys.forEach(function (nm) { bc.appendChild(fieldRow('bg_daily', byName[nm])); });
      v.appendChild(bc);
    }

    var restFields = dailyFields.filter(function (n) {
      if (used[n.name]) return false;
      if (/^AutoBoss/.test(n.name)) return false;
      if (/^LeyLine/.test(n.name)) return false;
      if (/^TaskEnabledList|^TaskOrder$|^NextTaskId$/.test(n.name)) return false;
      return true;
    });
    if (restFields.length) {
      var oc = card('其它一条龙设置', 'daily.json 里剩下的字段，默认折叠。');
      var og = el('details', 'grp');
      og.open = false;
      var ogSum = el('summary');
      ogSum.appendChild(el('span', null, '展开 ' + restFields.length + ' 项'));
      og.appendChild(ogSum);
      var ogBody = el('div', 'grp-body');
      restFields.forEach(function (n) { ogBody.appendChild(fieldRow('bg_daily', n)); });
      og.appendChild(ogBody);
      oc.appendChild(og);
      v.appendChild(oc);
    }

    // BetterGI 程序自己的配置（User/config.json）
    var mt = await loadTree('bg_main');
    var HOT = /幽境|首领|秘境|地脉|战斗|启动|采集|钓鱼/;
    var hotNodes = [];
    var restNodes = [];
    (mt.tree || []).forEach(function (n) {
      if (n.kind === 'group' && HOT.test(n.label || '')) hotNodes.push(n);
      else restNodes.push(n);
    });
    if (hotNodes.length) {
      var hc = card('幽境危战 / 首领讨伐 / 战斗细节', '这些是 BetterGI 程序自己的设置（User/config.json），改完下次一条龙就用新值。');
      hotNodes.forEach(function (n) { hc.appendChild(groupBlock('bg_main', n, true)); });
      v.appendChild(hc);
    }
    if (restNodes.length) {
      var rc2 = card('其它 BetterGI 程序设置', '其余分组默认折叠，点标题展开。');
      restNodes.forEach(function (n) {
        rc2.appendChild(n.kind === 'group' ? groupBlock('bg_main', n, false) : fieldRow('bg_main', n));
      });
      v.appendChild(rc2);
    }

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
    var opt = (await loadOptions()) || {};
    var insMap = ((opt.starrail || {}).instance_names) || {};
    importantSection('m7a', t.important, v, '常用设置');

    if (insMap && Object.keys(insMap).length) {
      var ppNode = findNode(t.tree, 'power_plan');
      var base = isPending('m7a', 'power_plan') ? pv('m7a', 'power_plan', [])
        : ((ppNode && Array.isArray(ppNode.value)) ? ppNode.value : []);
      var ppRows = base.map(function (r) {
        return Array.isArray(r) ? [String(r[0] || ''), String(r[1] || ''), Number(r[2] || 0)] : ['', '', 0];
      });
      var types = Object.keys(insMap);
      function namesOf(type) {
        var m = insMap[type] || {};
        return Object.keys(m).filter(function (k) { return m[k] !== '跳过'; });
      }
      function commitPP() {
        setPending('m7a', 'power_plan', ppRows.map(function (r) { return [r[0], r[1], Number(r[2]) || 0]; }));
      }
      var pc = card('清体力计划', '按顺序刷这几项。副本类型、副本名都是下拉，次数是数字；改完点保存（整表替换，不会错位）。');
      var holder = el('div');
      function rebuildPP() {
        clear(holder);
        var tb = el('table', 'tb');
        var thr = el('tr');
        ['类型', '副本', '次数', ''].forEach(function (h) { thr.appendChild(el('th', null, h)); });
        tb.appendChild(thr);
        ppRows.forEach(function (r, i) {
          var ns = namesOf(r[0]);
          if (r[1] && ns.indexOf(r[1]) < 0) ns = [r[1]].concat(ns);
          var tr = el('tr');
          var td1 = el('td');
          td1.appendChild(optionsSelect(types.map(function (x) { return { v: x, l: x, g: '' }; }), r[0], false, function (val) {
            ppRows[i][0] = val;
            var n2 = namesOf(val);
            ppRows[i][1] = n2.length ? n2[0] : '';
            commitPP(); rebuildPP();
          }));
          tr.appendChild(td1);
          var td2 = el('td');
          td2.appendChild(optionsSelect(ns.map(function (x) { return { v: x, l: x, g: '' }; }), r[1], false, function (val) {
            ppRows[i][1] = val; commitPP();
          }));
          tr.appendChild(td2);
          var td3 = el('td');
          var num = el('input', 'w-sm');
          num.type = 'number';
          num.min = '0';
          num.value = String(r[2]);
          num.onchange = function () { ppRows[i][2] = Number(num.value) || 0; commitPP(); };
          td3.appendChild(num);
          tr.appendChild(td3);
          var td4 = el('td');
          var del = el('button', 'btn sm danger', '删除');
          del.type = 'button';
          del.onclick = function () { ppRows.splice(i, 1); commitPP(); rebuildPP(); };
          td4.appendChild(del);
          tr.appendChild(td4);
          tb.appendChild(tr);

          // 这一条刷什么、什么时候开——直接从三月七自己的 instance_drops.json 读
          var stInfo = opt.starrail || {};
          var drops = ((stInfo.drops || {})[r[0]] || {})[r[1]] || [];
          var rule = (stInfo.instance_rules || {})[r[0]] || '';
          var det = el('tr', 'detailrow');
          var td = el('td');
          td.colSpan = 4;
          var line = el('div', 'detail');
          if (drops.length) {
            line.appendChild(el('span', 'dname', '掉落'));
            line.appendChild(el('span', 'drule', drops.join('、')));
          }
          if (rule) line.appendChild(el('span', 'dtype', rule));
          if (!drops.length && !rule) line.appendChild(el('span', 'drule', '（这个副本上游没写掉落表）'));
          td.appendChild(line);
          det.appendChild(td);
          tb.appendChild(det);
        });
        holder.appendChild(tb);
        holder.appendChild(buttons([
          {
            text: '+ 加一条', sm: true, onClick: function () {
              var t0 = types[0] || '';
              var n0 = namesOf(t0);
              ppRows.push([t0, n0.length ? n0[0] : '', 1]);
              commitPP(); rebuildPP();
            }
          },
          {
            text: '看原始 YAML', sm: true, onClick: function () {
              S.advFid = 'm7a'; S.advMode = 'raw'; go('advanced');
            }
          }
        ]));
        holder.appendChild(hint('存的是 [[副本类型, 副本名, 次数], …]。三月七助手按这个顺序刷；次数填 0 通常表示刷到没体力。'));
      }
      rebuildPP();
      pc.appendChild(holder);
      v.appendChild(pc);
    }
    // 原项目里「高级但常用」的一组：之前只暴露了常用项，这些全漏了
    var ADV = [
      ['培养目标（按目标自动挑副本）', ['build_target_enable', 'build_target_scheme', 'build_target_ornament_weekly_count',
        'build_target_use_user_instance_when_only_erosion_and_ornament', 'break_down_level_four_relicset']],
      ['队伍与传送', ['instance_team_enable', 'instance_team_number', 'instance_teams', 'tp_before_instance', 'instance_team_use_priority']],
      ['燃料与沉浸器', ['merge_immersifier', 'merge_immersifier_limit', 'use_reserved_trailblaze_power',
        'calyx_golden_preference', 'use_fuel']],
      ['借人 / 支援', ['borrow_enable', 'borrow_character_enable', 'borrow_friends', 'borrow_scroll_times']],
      ['每日细项', ['daily_enable', 'daily_himeko_try_enable', 'daily_memory_one_enable', 'daily_memory_one_team',
        'daily_tasks', 'reward_assist_enable', 'reward_redemption_code_enable', 'reward_achievement_enable',
        'reward_message_enable']],
      ['周常 / 活动', ['echo_of_war_timestamp', 'echo_of_war_start_day_of_week', 'universe_enable',
        'activity_gardenofplenty_enable', 'activity_realmofthestrange_enable', 'activity_planarfissure_enable',
        'activity_journey_highlights_enable']],
      ['启动与退出', ['game_path', 'launcher_path', 'update_via_launcher', 'start_game_timeout', 'update_game_timeout',
        'exit_after_failure', 'pause_after_success', 'after_finish', 'check_update']],
      ['其它', ['log_level', 'log_retention_days', 'log_overlay_enable', 'play_audio', 'debug_mode_enable',
        'scheduled_on_conflict', 'scheduled_chain_continue_on_failure', 'home_cards', 'telemetry_id']]
    ];
    var advFields = walkFields(t.tree);
    var byFieldName = {};
    advFields.forEach(function (n) { byFieldName[n.name] = n; });
    var advCard = card('培养目标与进阶设置', '这些是原项目 config.yaml 里有、但之前配置中心没露出来的项。' +
      '「优先培养目标」打开后，三月七会按你选的培养方案自动挑该刷的副本。');
    ADV.forEach(function (g) {
      var has = g[1].filter(function (k) { return byFieldName[k]; });
      if (!has.length) return;
      var d = el('details', 'grp');
      if (g[0].indexOf('培养目标') === 0) d.setAttribute('open', 'open');
      var sum = el('summary');
      sum.appendChild(el('span', null, g[0]));
      sum.appendChild(el('span', 'badge dim', String(has.length)));
      d.appendChild(sum);
      var bd = el('div', 'grp-body');
      has.forEach(function (k) { bd.appendChild(fieldRow('m7a', byFieldName[k])); });
      d.appendChild(bd);
      advCard.appendChild(d);
    });
    v.appendChild(advCard);

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

  /* 绝区零体力计划：一条条编辑，副本名按「大类 → 类型 → 副本」级联筛选，下面带奖励提示 */
  function zzzPlanEditor(fid, listNode, opt) {
    var comp = (opt.zzz && opt.zzz.compendium) || {};
    var tabs = Object.keys(comp).filter(function (k) { return (comp[k] || []).length; });
    var levels = ((opt.zzz && opt.zzz.levels) || []).slice();
    var battles = ((opt.zzz && opt.zzz.auto_battle_configs) || []).slice();
    function catsOf(tab) {
      return (comp[tab] || []).map(function (c) { return c.name; });
    }
    function catObj(tab, cat) {
      return (comp[tab] || []).filter(function (x) { return x.name === cat; })[0];
    }
    function typesOf(tab, cat) {
      var c = catObj(tab, cat);
      return c ? (c.mission_types || []) : [];
    }
    function missionsOf(tab, cat, tname) {
      var t = typesOf(tab, cat).filter(function (x) { return x.name === tname; })[0];
      return t ? (t.missions || []) : [];
    }
    var items = (listNode.children || []).map(function (ch) {
      var o = {};
      (ch.children || []).forEach(function (f) { if (f.kind === 'field') o[f.name] = f.value; });
      return o;
    });
    var wrap = el('div');
    function commit() {
      setPending(fid, 'plan_list', items.map(function (x) {
        var y = {};
        Object.keys(x).forEach(function (k) { y[k] = x[k]; });
        return y;
      }));
    }
    function newId() {
      var s = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx';
      return s.replace(/[xy]/g, function (c) {
        var r = Math.random() * 16 | 0;
        return (c === 'x' ? r : ((r & 3) | 8)).toString(16);
      });
    }
    function rowWrap(label, helpText) {
      var row = el('div', 'row');
      var main = el('div', 'row-main');
      main.appendChild(el('div', 'row-label', label));
      if (helpText) main.appendChild(el('div', 'row-help', helpText));
      row.appendChild(main);
      var ctl = el('div', 'row-ctl');
      row.appendChild(ctl);
      return { row: row, ctl: ctl };
    }
    function numInput(value, onChange) {
      var inp = el('input', 'w-md');
      inp.type = 'number';
      inp.min = '0';
      inp.value = value === undefined || value === null ? '' : String(value);
      inp.onchange = function () { onChange(Number(inp.value) || 0, inp); };
      return inp;
    }
    function rebuild() {
      clear(wrap);
      if (!items.length) {
        wrap.appendChild(hint('一条计划都没有：跑起来只做「恶名狩猎/双倍」这类固定次数的，剩下的体力不会被花掉。'));
      }
      items.forEach(function (it, i) {
        var box = el('div', 'planbox');
        var hd = el('div', 'planhd');
        hd.appendChild(el('span', 'onum', String(i + 1)));
        hd.appendChild(el('span', 'planname', it.mission_name || '新计划'));
        var rm = el('button', 'btn sm danger', '删除');
        rm.type = 'button';
        rm.onclick = function () { items.splice(i, 1); commit(); rebuild(); };
        hd.appendChild(rm);
        box.appendChild(hd);

        var r1 = rowWrap('副本大类', '来自 OneDragon 自己的副本清单，大类决定下面能选哪些类型');
        r1.ctl.appendChild(selectBox(catsOf(it.tab_name).length ? catsOf(it.tab_name) : [it.category_name || ''], it.category_name, function (v) {
          it.category_name = v;
          var ts = typesOf(it.tab_name, v);
          it.mission_type_name = ts.length ? ts[0].name : it.mission_type_name;
          var ms = missionsOf(it.tab_name, it.category_name, it.mission_type_name);
          it.mission_name = ms.length ? ms[0].value : it.mission_name;
          commit(); rebuild();
        }));
        box.appendChild(r1.row);

        var tNames = typesOf(it.tab_name, it.category_name).map(function (x) { return x.name; });
        var r2 = rowWrap('副本类型', '只列这个大类下真的有的类型');
        r2.ctl.appendChild(selectBox(tNames.length ? tNames : [it.mission_type_name || ''], it.mission_type_name, function (v) {
          it.mission_type_name = v;
          var ms = missionsOf(it.tab_name, it.category_name, v);
          it.mission_name = ms.length ? ms[0].value : it.mission_name;
          commit(); rebuild();
        }));
        box.appendChild(r2.row);

        var ms = missionsOf(it.tab_name, it.category_name, it.mission_type_name);
        var vals = ms.map(function (m) { return m.value; });
        var r3 = rowWrap('副本名称', '');
        r3.ctl.appendChild(selectBox(vals.length ? vals : [it.mission_name || ''], it.mission_name, function (v) {
          it.mission_name = v; commit(); rebuild();
        }));
        box.appendChild(r3.row);

        var picked = ms.filter(function (m) { return m.value === it.mission_name; })[0];
        var det = el('div', 'detail');
        det.appendChild(el('span', 'dname', it.mission_name || '（未选）'));
        det.appendChild(el('span', 'dtype', (it.category_name || '?') + ' · ' + (it.mission_type_name || '?')));
        if (picked && picked.label && picked.label !== it.mission_name) {
          var mm = String(picked.label).match(/（([^（）]+)）\s*$/);
          det.appendChild(el('span', 'drule', mm ? ('给：' + mm[1]) : ('说明：' + picked.label)));
        } else {
          det.appendChild(el('span', 'drule', '上游没写这项给什么'));
        }
        det.appendChild(el('span', 'dloc', '计划 ' + (it.plan_times || 0) + ' 次 · 已完成 ' + (it.run_times || 0)));
        box.appendChild(det);

        var r4 = rowWrap('难度', '默认等级就是游戏里默认那档');
        r4.ctl.appendChild(selectBox(levels.length ? levels : [it.level || '默认等级'], it.level, function (v) {
          it.level = v; commit();
        }));
        box.appendChild(r4.row);

        var r5 = rowWrap('计划次数', '每天最多打几次');
        r5.ctl.appendChild(numInput(it.plan_times, function (v) { it.plan_times = v; commit(); }));
        box.appendChild(r5.row);

        var r6 = rowWrap('自动战斗配置', '来自 OneDragon 的 config/auto_battle');
        r6.ctl.appendChild(selectBox(battles.length ? battles : [it.auto_battle_config || ''], it.auto_battle_config, function (v) {
          it.auto_battle_config = v; commit();
        }));
        box.appendChild(r6.row);

        var r7 = rowWrap('队伍序号', '预设队伍从 1 开始');
        r7.ctl.appendChild(numInput(it.predefined_team_idx, function (v) { it.predefined_team_idx = v; commit(); }));
        box.appendChild(r7.row);

        wrap.appendChild(box);
      });
      var add = el('button', 'btn sm', '+ 加一条');
      add.type = 'button';
      add.onclick = function () {
        var tab = tabs[0] || '训练';
        var cat = catsOf(tab)[0] || '';
        var ty = typesOf(tab, cat)[0];
        var ms2 = ty ? (ty.missions || []) : [];
        items.push({
          tab_name: tab, category_name: cat,
          mission_type_name: ty ? ty.name : '',
          mission_name: ms2.length ? ms2[0].value : '',
          level: levels[0] || '默认等级',
          auto_battle_config: battles[0] || '全配队通用',
          run_times: 0, plan_times: 1, card_num: '默认数量',
          predefined_team_idx: 3, notorious_hunt_buff_num: 1, plan_id: newId()
        });
        commit(); rebuild();
      };
      wrap.appendChild(add);
    }
    rebuild();
    return wrap;
  }

  /* ------------------------------------------------------------------ 绝区零 */
  async function pageZzz(v) {
    clear(v);
    var acc = await loadTree('od_account');
    var game = await loadTree('od_game');
    var charge = await loadTree('od_charge');
    var ours = await loadOurs();
    var opt = (await loadOptions()) || {};

    var c1 = card('账号与登录', '填了账号密码，掉登录时 OneDragon 会自己登进来。密码明文保存在本机 config 里，不会进仓库。');
    acc.important.forEach(function (o) { c1.appendChild(fieldRow('od_account', o)); });
    v.appendChild(c1);

    var c2 = card('游戏与窗口', '后台模式必须关闭（绝区零窗口受保护，后台模式会读不到画面）。');
    game.important.forEach(function (o) { c2.appendChild(fieldRow('od_game', o)); });
    v.appendChild(c2);

    var grpTree = null;
    try { grpTree = await loadTree('od_group'); } catch (e) { grpTree = null; }
    var appListNode = grpTree ? findNode(grpTree.tree, 'app_list') : null;
    if (appListNode && (appListNode.children || []).length) {
      var appsMap = (opt.zzz && opt.zzz.apps) || {};
      var gc = card('一条龙要跑哪些功能、按什么顺序', '这就是 OneDragon 一条龙的完整应用清单：' +
        '↑ ↓ 调执行顺序，右边开关决定跑不跑。全表替换保存，不会错位。');
      var appsArr = [];
      (appListNode.children || []).forEach(function (child) {
        var idNode = findNode([child], 'app_id');
        var enNode = findNode([child], 'enabled');
        appsArr.push({ app_id: idNode ? String(idNode.value) : '', enabled: enNode ? !!enNode.value : false });
      });
      var appHolder = el('div');
      function commitApps() { setPending('od_group', 'app_list', appsArr.slice()); }
      function rebuildApps() {
        clear(appHolder);
        appHolder.appendChild(orderEditor(appsArr.map(function (a) {
          return { id: a.app_id, label: appsMap[a.app_id] || a.app_id, sub: 'app_id: ' + a.app_id, enabled: a.enabled };
        }), function (from, to) {
          if (to < 0 || to >= appsArr.length) return;
          var mv = appsArr.splice(from, 1)[0];
          appsArr.splice(to, 0, mv);
          commitApps(); rebuildApps();
        }, function (i, on) {
          appsArr[i].enabled = on;
          commitApps(); rebuildApps();
        }));
      }
      rebuildApps();
      gc.appendChild(appHolder);
      gc.appendChild(hint('没列在这里的应用（例如卦象集录、刮刮卡）在『全部配置 → 一条龙总开关』里。'));
      v.appendChild(gc);
    }

    var c3 = card('清电量计划', '这是绝区零真正执行的体力计划（不是我们 config 里的 zzz targets）。' +
      '副本名按「大类 → 类型 → 副本」三级筛选，选完下面会写这一项能给什么。');
    charge.important.forEach(function (o) { c3.appendChild(fieldRow('od_charge', o)); });
    var planNode = findNode(charge.tree, 'plan_list');
    if (planNode && (planNode.children || []).length !== undefined) {
      c3.appendChild(zzzPlanEditor('od_charge', planNode, opt));
    }
    var d = el('details', 'grp mt8');
    var sum = el('summary');
    sum.appendChild(el('span', null, '原始字段（plan_list 之外的东西，以及每条的完整键值）'));
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

    var c1 = card('每天几点跑', '像上闹钟一样挑时和分（下面还有几个常用时间一点就好）。保存后会同时改 Windows 计划任务；' +
      '没有管理员权限时会先存配置，下次运行程序自己再同步一次。');
    var row = el('div', 'row');
    var main = el('div', 'row-main');
    main.appendChild(el('div', 'row-label', '每日运行时间'));
    main.appendChild(el('div', 'row-help', '建议比平时起床时间早，跑完你正好用电脑'));
    main.appendChild(el('div', 'row-path', 'scheduler.daily_time'));
    row.appendChild(main);
    var ctl = el('div', 'row-ctl');
    ctl.appendChild(alarmPicker(pv('ours', 'scheduler.daily_time', s.daily_time || '07:10'),
      isPending('ours', 'scheduler.daily_time'), function (hhmm) {
        setPending('ours', 'scheduler.daily_time', hhmm);
        cur.textContent = '保存后计划任务会改成：每天 ' + hhmm;
      }));
    row.appendChild(ctl);
    c1.appendChild(row);
    var cur = el('div', 'hint mt8');
    cur.textContent = '当前计划任务：' + (s.task && s.task.exists
      ? ((s.task.time || '?') + '，下次 ' + (s.task.next || '?'))
      : '还没注册');
    c1.appendChild(cur);
    v.appendChild(c1);

    var c2 = card('运行顺序', '用 ↑ ↓ 调顺序：排在前面的先跑。三个游戏是串行跑的，前一个跑完才轮到下一个，' +
      '所以顺序决定了「万一前面卡住，后面还能不能赶上」。');
    var GNAMES = { genshin: '原神', starrail: '崩坏：星穹铁道', zzz: '绝区零' };
    var curOrder = (isPending('ours', 'scheduler.run_order') ? pv('ours', 'scheduler.run_order', [])
      : (sc.run_order && sc.run_order.value) || ['genshin', 'starrail', 'zzz']).slice();
    ['genshin', 'starrail', 'zzz'].forEach(function (k) { if (curOrder.indexOf(k) < 0) curOrder.push(k); });
    var orderHolder = el('div');
    function rebuildOrder() {
      clear(orderHolder);
      orderHolder.appendChild(orderEditor(curOrder.map(function (k) {
        return { id: k, label: GNAMES[k] || k, sub: k, enabled: undefined };
      }), function (from, to) {
        if (to < 0 || to >= curOrder.length) return;
        var mv = curOrder.splice(from, 1)[0];
        curOrder.splice(to, 0, mv);
        setPending('ours', 'scheduler.run_order', curOrder.slice());
        rebuildOrder();
      }, null));
    }
    rebuildOrder();
    c2.appendChild(orderHolder);
    v.appendChild(c2);

    var c2b = card('超时与开机等待');
    Object.keys(sc).forEach(function (k) {
      if (k === 'daily_time' || k === 'run_order') return;
      var f = sc[k];
      c2b.appendChild(fieldRow('ours', { path: 'scheduler.' + k, label: f.label, type: f.type, value: f.value, help: f.help }));
    });
    v.appendChild(c2b);

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
    var src = null;
    try { src = await getJSON('/sources'); } catch (e) { src = null; }
    var t = await getJSON('/tools');
    var up = {};
    try {
      var u = await loadUpdates(false);
      ((u && u.tools) || []).forEach(function (r) { up[r.key] = r; });
    } catch (e) { /* 忽略 */ }
    var c = card('三个上游程序', '从官方 GitHub Release 下载（只用官方发布包，不复制别人的代码）。' +
      'BetterGI 自己也开着自动更新；这里显示本地已装版本、上游最新版本，以及有没有新版。');
    var upBar = el('div', 'btnrow');
    upBar.appendChild(el('button', 'btn sm', '检查更新'));
    upBar.lastChild.type = 'button';
    upBar.lastChild.onclick = async function () {
      var self = this;
      self.disabled = true;
      self.textContent = '检查中…';
      var r = await loadUpdates(true);
      self.disabled = false;
      self.textContent = '检查更新';
      if (r && r.error) toast('检查失败：' + r.error, 'err');
      else toast('已刷新', 'ok');
      render();
    };
    if (S.updates && S.updates.error) upBar.appendChild(el('span', 'hint', '　检查失败：' + S.updates.error));
    c.appendChild(upBar);
    var g3 = el('div', 'grid g3 mt12');
    t.tools.forEach(function (x) {
      var box = el('div', 'stat');
      box.appendChild(el('div', 'k', x.game + ' · ' + x.label));
      var ur = up[x.key] || {};
      var line = el('div', 'mt8');
      line.appendChild(badge(x.installed ? '已安装' : '未安装', x.installed ? 'ok' : 'warn'));
      if (ur.has_update === true) line.appendChild(badge(' 有新版 ' + (ur.latest || ''), 'warn'));
      else if (ur.has_update === false) line.appendChild(badge(' 已是最新', 'dim'));
      else if (ur.error) line.appendChild(badge(' 版本查不到', 'dim'));
      box.appendChild(line);
      var vline = el('div', 'hint mt8');
      vline.textContent = '已装 ' + (ur.installed || x.version || '未记录') +
        ' · 最新 ' + (ur.latest || x.latest || '—');
      box.appendChild(vline);
      box.appendChild(el('div', 'n mono', x.path));
      var b = el('div', 'btnrow mt8');
      var ib = el('button', 'btn sm', x.installed ? (ur.has_update ? '更新到最新' : '重新下载') : '下载安装');
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

    // ---- 下载源（三月七那种 450MB 的包，直连经常被卡死，得能换源）
    if (src && src.sources) {
      var info = src.sources;
      var sd = (info && info.sources) ? info
        : { order: (info && info.order) || [], sources: [], extra_mirrors: (info && info.extra_mirrors) || [] };
      var sc = card('下载源', '按顺序自动换源：第一个失败或太慢就走下一个。国内社区常用镜像加快，' +
        '有梯子的话「本机代理」通常最快。');
      var order = sd.order.slice();
      var srcHolder = el('div');
      var speed = {};
      function rebuildSrc() {
        clear(srcHolder);
        srcHolder.appendChild(orderEditor(order.map(function (id) {
          var row = (sd.sources || []).filter(function (x) { return x.id === id; })[0] || { id: id, name: id };
          var sp = speed[id];
          return {
            id: id, label: row.name,
            sub: (row.note || '') + (sp ? '　测速：' + (sp.ok ? sp.kbs + ' KB/s' : '失败 ' + (sp.error || '')) : ''),
            enabled: undefined
          };
        }), function (from, to) {
          if (to < 0 || to >= order.length) return;
          var mv = order.splice(from, 1)[0];
          order.splice(to, 0, mv);
          saveSrc();
          rebuildSrc();
        }, null));
      }
      function saveSrc() {
        postJSON('/sources', { order: order, extra_mirrors: extraList }).then(function (r) {
          if (fail(r)) return;
          toast('下载源顺序已保存', 'ok');
        });
      }
      var extraList = (sd.sources || []).filter(function (x) {
        return String(x.id).indexOf('extra') === 0;
      }).map(function (x) { return x.prefix; });
      rebuildSrc();
      sc.appendChild(srcHolder);

      var bar = el('div', 'btnrow mt8');
      var probeB = el('button', 'btn sm', '测速（各取 2MB）');
      probeB.type = 'button';
      probeB.onclick = function () {
        probeB.disabled = true;
        probeB.textContent = '测速中…';
        getJSON('/sources/probe').then(function (r) {
          probeB.disabled = false;
          probeB.textContent = '测速（各取 2MB）';
          if (r && r.error) { toast(r.error, 'err'); return; }
          (r.rows || []).forEach(function (x) { speed[x.id] = x; });
          rebuildSrc();
          var best = (r.rows || []).filter(function (x) { return x.ok; })
            .sort(function (a, b) { return b.kbs - a.kbs; })[0];
          toast(best ? ('最快：' + best.name + '（' + best.kbs + ' KB/s）') : '所有源都连不上，检查网络', best ? 'ok' : 'err');
        }).catch(function (e) {
          probeB.disabled = false;
          probeB.textContent = '测速（各取 2MB）';
          toast('测速失败：' + e, 'err');
        });
      };
      bar.appendChild(probeB);
      sc.appendChild(bar);

      var ex = el('div', 'row mt8');
      var exm = el('div', 'row-main');
      exm.appendChild(el('div', 'row-label', '自定义镜像前缀（可选，逗号分隔）'));
      exm.appendChild(el('div', 'row-help', '格式像 https://某个镜像.com/ ，程序会把它拼在官方地址前面。'));
      ex.appendChild(exm);
      var exc = el('div', 'row-ctl');
      var exi = el('input', 'w-lg');
      exi.type = 'text';
      exi.value = extraList.join(', ');
      exi.placeholder = 'https://gh-proxy.com/';
      exc.appendChild(exi);
      ex.appendChild(exc);
      sc.appendChild(ex);
      var exb = el('div', 'btnrow');
      var exSave = el('button', 'btn sm ghost', '保存镜像');
      exSave.type = 'button';
      exSave.onclick = function () {
        extraList = exi.value.split(',').map(function (s) { return s.trim(); }).filter(function (s) { return s; });
        saveSrc();
      };
      exb.appendChild(exSave);
      sc.appendChild(exb);
      sc.appendChild(hint('「更新三月七失败」八成是直连被卡：先点测速，把能跑的那个源拖到第一位再更新。' +
        '官方 full.7z 是 453MB（比 full.zip 少 230MB），程序已经优先选 .7z。'));
      v.appendChild(sc);
    }

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