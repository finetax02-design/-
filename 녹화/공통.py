"""여러 프로그램이 함께 쓰는 것들을 한곳에 모아 둔다.

지금까지 하나하나 확인해 온 것들이다. 무엇이 왜 이런지는 작동원리.md 에 있다.

  전표 목록 찾기        열 이름으로 가려낸다. 자리는 믿을 수 없다
  계정과목 채우기        F2 로 코드도움을 열고 마스터에서 코드로 고른다
  과세 -> 불공          체크하고 유형 칸을 진짜로 눌러 일괄변경
  불공제사유            창을 거치지 않고 칸에 직접 넣는다
  고객사 열기           수임처에서 이름을 찾아 회계를 누른다
  매입 조회             구분을 2.매입 으로 바꾸고 조회를 누른다

전송(F3)은 어디에서도 부르지 않는다.
"""
import collections
import json
import re

CDP = "http://localhost:9222"

과세 = "51"
불공 = "54"
미추천 = "5"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

NOISE = [re.compile(r"\(오더번호[^)]*\)"), re.compile(r"\(\d[^)]*\)"),
         re.compile(r"\[[^\]]*\]"), re.compile(r"외\s*\d+\s*건"), re.compile(r"\d+")]


def 품명다듬기(name):
    s = str(name or "")
    for pat in NOISE:
        s = pat.sub(" ", s)
    return re.sub(r"[\s\-_/,]+", " ", s).strip().lower()


# ---------------------------------------------------------------- 화면 읽기

GRIDS = r"""(args) => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const rowsOf = g => {
    let src = g;
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try { const n = src.getRowCount();
          return { count: n, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] }; }
    catch (e) { return { count: 0, rows: [] }; }
  };
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
  const out = { main: null, popup: null };
  let best = null;
  while (queue.length && visited < 60000) {
    const { o, d } = queue.shift();
    if (d > 9) continue;
    let keys = [];
    try { keys = Object.keys(o); } catch (e) { continue; }
    for (const k of keys) {
      if (d === 0 && SKIP.test(k)) continue;
      let v;
      try { v = o[k]; } catch (e) { continue; }
      if (!v || (typeof v !== 'object' && typeof v !== 'function')) continue;
      try { if (v.nodeType || v === window) continue; } catch (e) { continue; }
      try { if (seen.has(v)) continue; seen.add(v); } catch (e) { continue; }
      visited++;
      if (gridish(v)) {
        let cols = [];
        try { cols = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cols.includes('nm_acctit_cha')) {
          // 같은 열 구성을 가진 것이 여럿일 수 있다. 자료가 가장 많은 것을 고른다.
          const got = rowsOf(v);
          if (!best || got.count > best.count) { best = { g: v, count: got.count, rows: got.rows }; }
        } else if (cols.includes('cd_acctit') && cols.includes('nm_acctit')) {
          window.__pop = v;
          out.popup = args.withPopup ? rowsOf(v) : { count: rowsOf(v).count, rows: [] };
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  if (best) {
    window.__g = best.g;
    try { window.__dp = best.g.getDataSource(); } catch (e) { window.__dp = null; }
    out.main = { count: best.count, rows: args.withMain ? best.rows : [] };
  }
  return JSON.stringify(out);
}"""

# 화면 위쪽의 고객사명, 기수, 기간
HEADER = r"""() => {
  const 나온것 = [];
  for (const el of document.querySelectorAll('span,div,button,a,strong')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.y > 40 || r.width < 2) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
    own = own.trim().replace(/\s+/g, ' ');
    if (!own || own.length > 40) continue;
    나온것.push({ x: Math.round(r.x), 글자: own });
  }
  나온것.sort((a, b) => a.x - b.x);
  let 이름 = '', 기수 = '', 기간 = '';
  for (const t of 나온것) {
    if (!기수 && /^\d+기$/.test(t.글자)) { 기수 = t.글자; continue; }
    if (!기간 && /~/.test(t.글자)) { 기간 = t.글자; continue; }
    if (!이름 && t.x < 400 && !/^\d/.test(t.글자) && t.글자.length >= 2) 이름 = t.글자;
  }
  return JSON.stringify({ 이름: 이름, 기수: 기수, 기간: 기간 });
}"""

# 글자가 딱 맞는 것
BTN = r"""(args) => {
  const out = [];
  for (const el of document.querySelectorAll('button,a,li,span,div,[role=button],[role=menuitem]')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    if (t !== args.글) continue;
    let 안쪽 = true;
    for (const c of el.children) {
      const ct = (c.innerText || '').trim().replace(/\s+/g, ' ');
      if (ct === t) { 안쪽 = false; break; }
    }
    if (!안쪽) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 5 || r.height < 5) continue;
    out.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               자리: `${Math.round(r.x)},${Math.round(r.y)}` });
  }
  return JSON.stringify(out.slice(0, 10));
}"""

# 글자가 들어 있는 것 (목록이 어디에 그려질지 모를 때)
LIKE = r"""(args) => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 30 || !t.includes(args.글)) continue;
    let 안쪽 = true;
    for (const c of el.children) {
      const ct = (c.innerText || '').trim().replace(/\s+/g, ' ');
      if (ct === t) { 안쪽 = false; break; }
    }
    if (!안쪽) continue;
    out.push({ 글자: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               오른쪽: Math.round(r.x + r.width), 가운데y: Math.round(r.y + r.height / 2),
               너비: Math.round(r.width),
               자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}` });
  }
  return JSON.stringify(out.slice(0, 25));
}"""

# 입력칸에 글자를 넣는다. 리액트가 알아듣도록 네이티브 setter 를 쓴다.
TYPE_IN = r"""(args) => {
  const 것들 = [];
  for (const el of document.querySelectorAll('input')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 12) continue;
    const t = (el.type || 'text').toLowerCase();
    if (t !== 'text' && t !== 'search' && t !== '') continue;
    if (args.힌트 && !(el.placeholder || '').includes(args.힌트)) continue;
    것들.push({ el: el, w: r.width });
  }
  if (!것들.length) return JSON.stringify({ ok: false, reason: '입력칸이 없음' });
  것들.sort((a, b) => b.w - a.w);
  const el = 것들[0].el;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, args.글);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.focus();
  const r = el.getBoundingClientRect();
  return JSON.stringify({ ok: true, 값: el.value,
                          x: Math.round(r.x + r.width / 2),
                          y: Math.round(r.y + r.height / 2) });
}"""

# 수임처 줄에서 회계 단추 찾기
FIND_ROW = r"""(args) => {
  const 후보 = [];
  for (const el of document.querySelectorAll('button,a,span,div,[role=button]')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (t !== args.단추) continue;
    let 안쪽 = true;
    for (const c of el.children) {
      const ct = (c.innerText || '').trim().replace(/\s+/g, ' ');
      if (ct === t) { 안쪽 = false; break; }
    }
    if (!안쪽) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    let 줄 = el, 줄글 = '';
    for (let i = 0; i < 6 && 줄; i++) {
      줄 = 줄.parentElement;
      if (!줄) break;
      const tt = (줄.innerText || '').trim().replace(/\s+/g, ' ');
      if (tt.includes(args.이름)) { 줄글 = tt.slice(0, 120); break; }
      if (tt.length > 400) break;
    }
    if (!줄글) continue;
    후보.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                자리: `${Math.round(r.x)},${Math.round(r.y)}`, 줄: 줄글 });
  }
  return JSON.stringify(후보.slice(0, 10));
}"""

# 메뉴 검색칸 아래에 떠오른 줄들
MENU_ITEMS = r"""(args) => {
  const 것들 = [];
  for (const el of document.querySelectorAll('li,a,button,div,span,[role=menuitem]')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.y <= args.iy || r.y - args.iy > 500) continue;
    if (Math.abs(r.x - args.ix) > 700) continue;
    if (r.width < 40 || r.height < 12 || r.height > 60) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 50) continue;
    것들.push({ 글자: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                자리: `${Math.round(r.x)},${Math.round(r.y)}`, 너비: Math.round(r.width) });
  }
  const 남길것 = new Map();
  for (const c of 것들) {
    const 열쇠 = c.글자 + '|' + Math.round(c.y / 8);
    const 앞 = 남길것.get(열쇠);
    if (!앞 || c.너비 > 앞.너비) 남길것.set(열쇠, c);
  }
  const 결과 = [...남길것.values()];
  결과.sort((a, b) => a.y - b.y);
  return JSON.stringify(결과.slice(0, 20));
}"""

# ---------------------------------------------------------------- 계정과목

PREP = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  let r;
  try { r = (dp || g).getJsonRows(args.row, args.row)[0]; } catch (e) { r = null; }
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(r.nm_trade ?? '') !== String(args.trade ?? '')
      || String(r.mn_mnam ?? '') !== String(args.amount ?? '')) {
    return JSON.stringify({ ok: false, reason: '대조 실패' });
  }
  const codeField = args.field === 'nm_acctit_cha' ? 'cd_acctit_cha' : 'cd_acctit_dae';
  if (r[codeField]) return JSON.stringify({ ok: false, reason: '이미 채워져 있음' });
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: args.field, fieldName: args.field }); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setCurrent ' + String(e).slice(0, 90) }); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  return JSON.stringify({ ok: true });
}"""

GOTO = r"""(args) => {
  const p = window.__pop;
  if (!p) return JSON.stringify({ ok: false, reason: '팝업 그리드 없음' });
  try { p.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'nm_acctit', fieldName: 'nm_acctit' }); }
  catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 120) }); }
  try { if (p.setFocusToGrid) p.setFocusToGrid(); } catch (e) {}
  return JSON.stringify({ ok: true });
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    return JSON.stringify({ cd_cha: r.cd_acctit_cha, cd_dae: r.cd_acctit_dae,
                            status: r.ty_jungstat });
  } catch (e) { return JSON.stringify({ error: String(e).slice(0, 100) }); }
}"""

# ---------------------------------------------------------------- 불공

PREP_TEMPLATE = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  let src = g;
  try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
  let r = null;
  try { r = src.getJsonRows(args.row, args.row)[0]; } catch (e) {}
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(r.ty_mth2) !== args.want_ty || String(r.cd_notdedct) !== args.want_cd) {
    return JSON.stringify({ ok: false,
      reason: `본보기 줄이 달라졌습니다 (유형 ${r.ty_mth2} 사유 ${r.cd_notdedct})` });
  }
  try { if (typeof g.setTopItem === 'function') g.setTopItem(args.row); } catch (e) {}
  return JSON.stringify({ ok: true, 거래처: r.nm_trade });
}"""

CELL_BOUNDS = r"""(args) => {
  const g = window.__g;
  try {
    const b = g.getCellBounds(args.row, 'ty_mth2');
    if (!b) return JSON.stringify({ ok: false, reason: '칸 자리를 못 얻음' });
    return JSON.stringify({ ok: true, x: b.x, y: b.y, w: b.width, h: b.height });
  } catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 90) }); }
}"""

CURRENT = r"""() => {
  try { return JSON.stringify(window.__g.getCurrent() || {}); } catch (e) { return '{}'; }
}"""

CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  try { if (g.checkAll) g.checkAll(false); else if (g.resetCheckables) g.resetCheckables(false); }
  catch (e) {}
  try {
    if (typeof g.checkItems === 'function') g.checkItems(args.rows, true);
    else if (typeof g.checkItem === 'function') for (const r of args.rows) g.checkItem(r, true);
    else return JSON.stringify({ 요청: args.rows.length, 센수: -1, 하나씩: -1 });
  } catch (e) { return JSON.stringify({ 요청: args.rows.length, 센수: -1, 하나씩: -1,
                                        오류: String(e).slice(0, 100) }); }
  let 센수 = -1;
  for (const m of ['getCheckedItemIndices', 'getCheckedRows', 'getCheckedItems']) {
    try {
      if (typeof g[m] === 'function') {
        const v = g[m]();
        if (Array.isArray(v)) { 센수 = v.length; break; }
      }
    } catch (e) {}
  }
  let 하나씩 = -1;
  try {
    if (typeof g.isCheckedItem === 'function') {
      하나씩 = 0;
      for (const r of args.rows) if (g.isCheckedItem(r)) 하나씩++;
    }
  } catch (e) {}
  return JSON.stringify({ 요청: args.rows.length, 센수: 센수, 하나씩: 하나씩 });
}"""

SELECTED_TEXT = r"""() => {
  for (const el of document.querySelectorAll('span,div,em')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    const m = t.match(/^(\d+)건\s*선택됨$|^선택됨\s*(\d+)건$/);
    if (m) return m[1] || m[2];
  }
  for (const el of document.querySelectorAll('div')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (t.length < 20 && t.includes('선택됨')) {
      const m = t.match(/(\d+)\s*건/);
      if (m) return m[1];
    }
  }
  return '';
}"""

POPUP = r"""() => {
  const 안내 = [], 표 = [], 단추 = [], 라디오 = [];
  const 보임 = el => {
    if (el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  // 확인창의 변경내용은 글자가 아니라 input 의 값으로 들어 있다.
  const 칸글자 = c => {
    let t = (c.innerText || '').trim();
    if (t) return t;
    const 값 = [];
    for (const i of c.querySelectorAll('input,textarea')) if (i.value) 값.push(i.value);
    return 값.join(' ').trim();
  };
  for (const tb of document.querySelectorAll('table')) {
    if (!보임(tb)) continue;
    if (!/변경항목|변경내용/.test(tb.innerText || '')) continue;
    const rows = [];
    for (const tr of tb.rows) rows.push([...tr.cells].map(칸글자));
    표.push({ 줄: rows.slice(0, 12) });
  }
  for (const el of document.querySelectorAll('button,[role=button],[class*=btn],[class*=Btn]')) {
    if (!보임(el)) continue;
    const t = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 20) continue;
    if (!단추.includes(t)) 단추.push(t);
  }
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = el.closest('label') || el.parentElement;
    if (!lab || !보임(lab)) continue;
    const t = (lab.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^[0-9A-B][.\s]/.test(t)) continue;
    라디오.push({ 코드: t[0], 글자: t.slice(0, 26), 골라짐: !!el.checked });
  }
  for (const el of document.querySelectorAll('[class*=dialog],[class*=modal],[class*=popup]')) {
    if (!보임(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 40) continue;
    let t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    const 값 = [];
    for (const i of el.querySelectorAll('input[type=text],input:not([type]),textarea')) {
      if (i.value) 값.push(i.value);
    }
    if (값.length) t += ' [입력칸: ' + 값.join(' / ') + ']';
    if (t && !안내.includes(t)) 안내.push(t.slice(0, 300));
  }
  return JSON.stringify({ 안내: 안내.slice(0, 6), 표: 표, 단추: 단추.slice(0, 60),
                          라디오: 라디오 });
}"""

SET_REASON = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  let src = g;
  try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
  const 읽기 = () => { try { return src.getJsonRows(args.row, args.row)[0] || null; }
                       catch (e) { return null; } };
  const 앞 = 읽기();
  if (!앞) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(앞.nm_trade || '') !== args.거래처) {
    return JSON.stringify({ ok: false, reason: `줄이 밀렸습니다 (${앞.nm_trade})` });
  }
  if (String(앞.cd_notdedct || '') === args.사유) {
    return JSON.stringify({ ok: true, 그대로: true });
  }
  let 열자리 = -1;
  try {
    g.getColumns().forEach((c, i) => {
      if (String(c.name || c.fieldName || '') === 'cd_notdedct') 열자리 = i;
    });
  } catch (e) {}
  try { g.setValue(args.row, 'cd_notdedct', args.사유); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setValue ' + String(e).slice(0, 90) }); }
  try { if (typeof g.onCellEdited === 'function') g.onCellEdited(g, args.row, args.row, 열자리); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'onCellEdited ' + String(e).slice(0, 90) }); }
  const 뒤 = 읽기();
  return JSON.stringify({ ok: true, 앞사유: 앞.cd_notdedct, 뒤사유: 뒤 && 뒤.cd_notdedct });
}"""


# ---------------------------------------------------------------- 거드는 것

def 누르기(page, 글, 아래것=True):
    """글자가 딱 맞는 것을 눌러 준다. 여러 개면 아래쪽 것."""
    것 = json.loads(page.evaluate(BTN, {"글": 글}))
    if not 것:
        return None
    것.sort(key=lambda c: (c["y"], c["x"]))
    표적 = 것[-1] if 아래것 else 것[0]
    page.mouse.click(표적["x"], 표적["y"])
    page.wait_for_timeout(800)
    return 표적


def 전표읽기(page):
    """전표 목록을 읽는다. 없으면 빈 목록."""
    try:
        d = json.loads(page.evaluate(GRIDS, {"withMain": True, "withPopup": False}))
    except Exception:
        return None
    if not d.get("main"):
        return None
    return d["main"]["rows"]


def 화면머리(page):
    try:
        return json.loads(page.evaluate(HEADER))
    except Exception:
        return {"이름": "", "기수": "", "기간": ""}


# ---------------------------------------------------------------- 배우기

def 배우기(rows):
    """계정과목이 채워진 건에서 사업자번호별, 품명별 계정을 배운다."""
    biz = {"cha": collections.defaultdict(collections.Counter),
           "dae": collections.defaultdict(collections.Counter)}
    item = {"cha": collections.defaultdict(collections.Counter),
            "dae": collections.defaultdict(collections.Counter)}
    common = {"cha": collections.Counter(), "dae": collections.Counter()}
    for r in rows:
        for side, cf, nf in (("cha", "cd_acctit_cha", "nm_acctit_cha"),
                             ("dae", "cd_acctit_dae", "nm_acctit_dae")):
            code = r.get(cf)
            if not code:
                continue
            pair = f"{code}|{r.get(nf)}"
            common[side][pair] += 1
            if r.get("no_bisocial"):
                biz[side][str(r["no_bisocial"])][pair] += 1
            key = 품명다듬기(r.get("nm_good"))
            if key:
                item[side][key][pair] += 1
    return biz, item, common


def 짚어보기(rec, side, biz, item, common, 최빈값도):
    for src, why in ((biz[side].get(str(rec.get("no_bisocial") or "")), "거래처"),
                     (item[side].get(품명다듬기(rec.get("nm_good"))), "품명")):
        if src:
            pair, n = src.most_common(1)[0]
            code, _, name = pair.partition("|")
            return code, name, why
    if 최빈값도 and common[side]:
        pair, n = common[side].most_common(1)[0]
        code, _, name = pair.partition("|")
        return code, name, "최빈값"
    return None, None, "없음"


def 불공규칙만들기(rows):
    """거래처마다 과거에 불공이었는지 과세였는지 세어 규칙을 만든다.

    한 번이라도 불공이었으면 불공으로 본다. 앞 기간에는 화면에서 과세로
    보내고 나중에 수기로 고쳤을 수 있기 때문이다. 판단이 갈린 것이 아니라
    처리 시점이 달랐던 것이다.
    """
    묶음 = collections.defaultdict(list)
    for r in rows:
        biz = str(r.get("no_bisocial") or "")
        if biz:
            묶음[biz].append(r)
    규칙 = {}
    자세히 = []
    for biz, rs in 묶음.items():
        kinds = collections.Counter(str(x.get("ty_mth2")) for x in rs)
        n_tax, n_no = kinds.get(과세, 0), kinds.get(불공, 0)
        codes = collections.Counter(str(x.get("cd_notdedct") or "").strip()
                                    for x in rs if str(x.get("cd_notdedct") or "").strip())
        code = codes.most_common(1)[0][0] if codes else ""
        판정 = "불공" if n_no else "과세"
        적용 = 판정 == "불공" and code in 사유이름
        if 적용:
            규칙[biz] = code
        자세히.append({"사업자번호": biz, "거래처명": rs[0].get("nm_trade"),
                       "과세": n_tax, "불공": n_no, "판정": 판정,
                       "사유코드": code, "적용": "Y" if 적용 else "N"})
    return 규칙, 자세히


# ---------------------------------------------------------------- 일하기
#
# 아래 것들은 사람에게 묻지 않고 스스로 한다. 대신 한 걸음마다 확인하고
# 어긋나면 그 자리에서 멈춘다. 전송(F3)은 어디에서도 부르지 않는다.

def 계정과목채우기(page, 말하기):
    """미추천으로 남은 빈 계정과목 칸을 과거 이력대로 채운다."""
    rows = 전표읽기(page)
    if not rows:
        return {"결과": "전표 없음", "성공": 0, "실패": 0, "건너뜀": 0}

    배운것 = [r for r in rows if str(r.get("ty_jungstat")) != 미추천]
    biz, item, common = 배우기(배운것)

    할일, 건너뜀 = [], []
    for i, r in enumerate(rows):
        if str(r.get("ty_jungstat")) != 미추천:
            continue
        cha_code, cha_name, cha_why = 짚어보기(r, "cha", biz, item, common, False)
        if not cha_code and not r.get("cd_acctit_cha"):
            건너뜀.append((i, r, "차변 판단 불가"))
            continue
        dae_code, dae_name, dae_why = 짚어보기(r, "dae", biz, item, common, True)
        for side, field, code, name, why in (
                ("차변", "nm_acctit_cha", cha_code, cha_name, cha_why),
                ("대변", "nm_acctit_dae", dae_code, dae_name, dae_why)):
            cf = "cd_acctit_cha" if field == "nm_acctit_cha" else "cd_acctit_dae"
            if r.get(cf):
                continue
            if not code:
                건너뜀.append((i, r, f"{side} 판단 불가"))
                continue
            할일.append({"row": i, "rec": r, "side": side, "field": field,
                         "code": code, "name": name, "why": why})

    말하기(f"    미추천 {sum(1 for r in rows if str(r.get('ty_jungstat')) == 미추천)}건"
           f"  채울 칸 {len(할일)}개  건너뜀 {len(건너뜀)}개")
    for i, r, why in 건너뜀[:8]:
        말하기(f"      건너뜀 {i + 1}번째 {r.get('nm_trade')} : {why}")
    if not 할일:
        return {"결과": "채울 것 없음", "성공": 0, "실패": 0, "건너뜀": len(건너뜀)}

    마스터 = []
    성공, 실패 = 0, []

    for x in 할일:
        r = x["rec"]
        앞 = json.loads(page.evaluate(STATE, {"row": x["row"]}))
        준비 = json.loads(page.evaluate(PREP, {
            "row": x["row"], "field": x["field"],
            "trade": r.get("nm_trade"), "amount": r.get("mn_mnam")}))
        if not 준비.get("ok"):
            실패.append((x, 준비.get("reason")))
            break

        page.keyboard.press("F2")
        page.wait_for_timeout(1300)

        if not 마스터:
            팝 = json.loads(page.evaluate(GRIDS, {"withMain": False, "withPopup": True})).get("popup")
            if not 팝 or not 팝["rows"]:
                page.keyboard.press("Escape")
                실패.append((x, "계정과목 코드도움을 못 읽음"))
                break
            마스터 = 팝["rows"]
            말하기(f"    계정과목 마스터 {len(마스터)}개 확보")
        else:
            page.evaluate(GRIDS, {"withMain": False, "withPopup": False})

        찾음 = next((i for i, pr in enumerate(마스터)
                     if str(pr.get("cd_acctit")) == str(x["code"])), None)
        if 찾음 is None:
            page.keyboard.press("Escape")
            실패.append((x, f"코드 {x['code']} 를 마스터에서 못 찾음"))
            break

        간것 = json.loads(page.evaluate(GOTO, {"row": 찾음}))
        if not 간것.get("ok"):
            page.keyboard.press("Escape")
            실패.append((x, f"코드도움 이동 실패 {간것.get('reason')}"))
            break

        눌렀나 = False
        for sel in ("button:has-text('확인(enter)')", "button:has-text('확인')"):
            try:
                loc = page.locator(sel).last
                if loc.count() and loc.is_visible():
                    loc.click(timeout=4000)
                    눌렀나 = True
                    break
            except Exception:
                pass
        if not 눌렀나:
            page.keyboard.press("Enter")
        page.wait_for_timeout(1100)

        뒤 = json.loads(page.evaluate(STATE, {"row": x["row"]}))
        열쇠 = "cd_cha" if x["field"] == "nm_acctit_cha" else "cd_dae"
        if 앞.get(열쇠) != 뒤.get(열쇠):
            성공 += 1
        else:
            실패.append((x, "값이 바뀌지 않음"))
            break

    for x, why in 실패:
        말하기(f"    [멈춤] {x['row'] + 1}번째 {x['rec'].get('nm_trade')}"
               f" {x['side']} : {why}")
    말하기(f"    계정과목 {성공} / {len(할일)}칸 채움")
    return {"결과": "정상" if not 실패 else "도중 멈춤",
            "성공": 성공, "실패": len(실패), "건너뜀": len(건너뜀)}


def _창기다리기(page, 초=8):
    """창은 먼저 뜨고 알맹이는 나중에 채워진다. 다 채워질 때까지 기다린다."""
    남은 = int(초 * 1000)
    d = json.loads(page.evaluate(POPUP))
    while 남은 > 0:
        글 = " ".join(d["안내"]) + " " + " ".join(
            " ".join(row) for tb in d["표"] for row in tb["줄"])
        찼다 = bool(d["라디오"]) or "대상이 없습니다" in 글 or "선택후" in 글 or any(
            any(c.strip() for c in row) for tb in d["표"] for row in tb["줄"][1:])
        if 찼다:
            break
        page.wait_for_timeout(400)
        남은 -= 400
        d = json.loads(page.evaluate(POPUP))
    return d


def 불공전환(page, 규칙, 말하기):
    """규칙에 따라 과세를 불공으로 바꾸고 사유를 넣는다. 사유별로 따로 돈다."""
    결과 = {"바꾼건": 0, "못한사유": [], "멈춤": ""}
    for 사유 in sorted(사유이름):
        rows = 전표읽기(page)
        if rows is None:
            결과["멈춤"] = "전표 목록을 못 읽음"
            return 결과
        대상, 본보기 = [], []
        for i, r in enumerate(rows):
            ty = str(r.get("ty_mth2") or "")
            cd = str(r.get("cd_notdedct") or "")
            biz = str(r.get("no_bisocial") or "")
            if ty == 불공 and cd == 사유:
                # 규칙과 어긋나는 줄은 본보기로 쓰지 않는다
                if 규칙.get(biz) in (None, 사유):
                    본보기.append(i)
            elif ty == 과세 and 규칙.get(biz) == 사유:
                대상.append(i)
        if not 대상:
            continue
        if not 본보기:
            말하기(f"    사유 {사유} {사유이름[사유]}: 바꿀 줄 {len(대상)}건이지만"
                   f" 본보기가 없어 건너뜁니다")
            결과["못한사유"].append(f"{사유}(본보기없음, {len(대상)}건)")
            continue

        말하기(f"    사유 {사유} {사유이름[사유]}: {len(대상)}건 바꿉니다")
        본 = 본보기[0]

        res = json.loads(page.evaluate(CHECK_ROWS, {"rows": 대상}))
        화면수 = page.evaluate(SELECTED_TEXT)
        센것 = [n for n in (res.get("센수"), res.get("하나씩")) if n is not None and n >= 0]
        if 화면수.isdigit():
            센것.append(int(화면수))
        if not 센것 or max(센것) != len(대상):
            결과["멈춤"] = f"사유 {사유}: 체크가 {센것} 로 어긋남"
            return 결과

        p = json.loads(page.evaluate(PREP_TEMPLATE,
                                     {"row": 본, "want_ty": 불공, "want_cd": 사유}))
        if not p.get("ok"):
            결과["멈춤"] = f"사유 {사유}: 본보기 준비 실패 {p.get('reason')}"
            return 결과
        page.wait_for_timeout(500)
        bd = json.loads(page.evaluate(CELL_BOUNDS, {"row": 본}))
        if not bd.get("ok"):
            결과["멈춤"] = f"사유 {사유}: 유형 칸 자리를 못 얻음"
            return 결과
        page.mouse.click(bd["x"] + bd["w"] / 2, bd["y"] + bd["h"] / 2)
        page.wait_for_timeout(500)
        cur = json.loads(page.evaluate(CURRENT))
        if cur.get("itemIndex") != 본 or cur.get("fieldName") != "ty_mth2":
            결과["멈춤"] = f"사유 {사유}: 유형 칸을 못 잡음 {cur}"
            return 결과
        화면수2 = page.evaluate(SELECTED_TEXT)
        if 화면수2.isdigit() and int(화면수2) != len(대상):
            결과["멈춤"] = f"사유 {사유}: 칸을 누른 뒤 선택됨이 {화면수2}건으로 바뀜"
            return 결과

        if not 누르기(page, "일괄변경"):
            결과["멈춤"] = f"사유 {사유}: 일괄변경 단추를 못 찾음"
            return 결과
        if not 누르기(page, "전체일괄변경"):
            결과["멈춤"] = f"사유 {사유}: 전체일괄변경을 못 찾음"
            return 결과

        d = _창기다리기(page)
        글 = " ".join(d["안내"]) + " " + " ".join(
            " ".join(row) for tb in d["표"] for row in tb["줄"])
        if "대상이 없습니다" in 글 or "선택후" in 글:
            결과["멈춤"] = f"사유 {사유}: 위하고가 바꿀 대상을 못 알아봄"
            return 결과
        if "불공" not in 글:
            결과["멈춤"] = f"사유 {사유}: 확인창의 변경내용이 비어 있음"
            return 결과
        숫자 = [int(n) for tb in d["표"] for row in tb["줄"] for c in row
                for n in re.findall(r"\b(\d+)\b", c)]
        if 숫자 and len(대상) not in 숫자:
            결과["멈춤"] = f"사유 {사유}: 확인창 숫자 {숫자} 가 {len(대상)}건과 다름"
            return 결과

        눌렀나 = False
        for 글자 in ("확인(Enter)", "확인(enter)", "확인"):
            if 누르기(page, 글자):
                눌렀나 = True
                break
        if not 눌렀나:
            결과["멈춤"] = f"사유 {사유}: 확인 단추를 못 찾음"
            return 결과

        # 사유 창이 뜬다. 라디오는 움직이지 않으므로 그대로 확인만 하고
        # 사유는 뒤에서 칸에 직접 넣는다.
        page.wait_for_timeout(900)
        d2 = _창기다리기(page, 4)
        if d2["라디오"]:
            눌렀나 = False
            for 글자 in ("선택(enter)", "선택(Enter)", "확인(Enter)", "확인(enter)", "선택", "확인"):
                if 누르기(page, 글자):
                    눌렀나 = True
                    break
            if not 눌렀나:
                결과["멈춤"] = f"사유 {사유}: 사유 창의 확인 단추를 못 찾음"
                return 결과
        page.wait_for_timeout(1500)

        뒤rows = 전표읽기(page)
        if 뒤rows is None:
            결과["멈춤"] = f"사유 {사유}: 바꾼 뒤 목록을 못 읽음"
            return 결과
        for i in 대상:
            if i >= len(뒤rows) or str(뒤rows[i].get("nm_trade") or "") != str(rows[i].get("nm_trade") or ""):
                결과["멈춤"] = f"사유 {사유}: {i + 1}번째 줄이 밀림"
                return 결과
        안바뀐 = [i for i in 대상 if str(뒤rows[i].get("ty_mth2") or "") != 불공]
        if 안바뀐:
            결과["멈춤"] = f"사유 {사유}: 유형이 안 바뀐 줄 {len(안바뀐)}건"
            return 결과

        고칠것 = [i for i in 대상 if str(뒤rows[i].get("cd_notdedct") or "") != 사유]
        for i in 고칠것:
            rr = json.loads(page.evaluate(SET_REASON, {
                "row": i, "사유": 사유, "거래처": str(뒤rows[i].get("nm_trade") or "")}))
            if not rr.get("ok"):
                결과["멈춤"] = f"사유 {사유}: {i + 1}번째 사유 넣기 실패 {rr.get('reason')}"
                return 결과
        page.wait_for_timeout(1000)

        끝rows = 전표읽기(page) or 뒤rows
        된것 = sum(1 for i in 대상
                   if i < len(끝rows)
                   and str(끝rows[i].get("ty_mth2") or "") == 불공
                   and str(끝rows[i].get("cd_notdedct") or "") == 사유)
        말하기(f"      바뀐 줄 {된것} / {len(대상)}")
        if 된것 != len(대상):
            결과["멈춤"] = f"사유 {사유}: {len(대상) - 된것}건이 어긋남"
            return 결과
        결과["바꾼건"] += 된것

    return 결과


def 고객사열기(browser, 수임처탭, 표적, 말하기):
    """수임처 화면에서 이름으로 찾아 회계를 누르고 전자세금계산서까지 간다.

    돌려주는 것: (전표화면, 새로 열린 탭들, 잘못된 까닭)
    """
    수임처탭.bring_to_front()
    전탭 = {id(pg): pg for ctx in browser.contexts for pg in ctx.pages}

    r = json.loads(수임처탭.evaluate(TYPE_IN, {"글": 표적["고객사명"], "힌트": "회사명"}))
    if not r.get("ok"):
        return None, [], f"수임처 검색칸을 못 찾음 ({r.get('reason')})"
    수임처탭.mouse.click(r["x"], r["y"])
    수임처탭.keyboard.press("Enter")
    수임처탭.wait_for_timeout(2500)

    후보 = json.loads(수임처탭.evaluate(FIND_ROW,
                                       {"이름": 표적["고객사명"], "단추": "회계"}))
    if len(후보) != 1:
        return None, [], f"회계 단추가 {len(후보)}개 (하나일 때만 누릅니다)"
    수임처탭.mouse.click(후보[0]["x"], 후보[0]["y"])

    새탭 = None
    for _ in range(14):
        수임처탭.wait_for_timeout(3000)
        것들 = [pg for ctx in browser.contexts for pg in ctx.pages]
        맞는것 = [pg for pg in 것들
                  if "smarta.wehago.com" in pg.url
                  and (표적["cd_com"] in pg.url or f"cNum={표적['cno']}" in pg.url)]
        if 맞는것:
            새탭 = 맞는것[0]
            break
    if 새탭 is None:
        return None, [], "고객사 화면이 안 열림"

    새탭.bring_to_front()
    새탭.wait_for_timeout(3000)
    h = 화면머리(새탭)
    if not h["이름"] or not (표적["고객사명"] in h["이름"] or h["이름"] in 표적["고객사명"]):
        return None, [새탭], f"다른 고객사 화면 (화면: {h['이름']})"
    말하기(f"    고객사 열림: {h['이름']} {h['기수']}")

    r2 = json.loads(새탭.evaluate(TYPE_IN, {"글": "전자세금계산서", "힌트": "메뉴"}))
    if not r2.get("ok"):
        return None, [새탭], "메뉴 검색칸을 못 찾음"
    새탭.wait_for_timeout(2000)
    줄들 = json.loads(새탭.evaluate(MENU_ITEMS, {"ix": r2["x"], "iy": r2["y"]}))
    딱 = [c for c in 줄들 if c["글자"] == "전자세금계산서"]
    if not 딱:
        return None, [새탭], "메뉴에서 전자세금계산서를 못 찾음"

    전표화면 = None
    for c in 딱:
        새탭.mouse.click(c["x"], c["y"])
        for _ in range(5):
            새탭.wait_for_timeout(3000)
            것들 = [pg for ctx in browser.contexts for pg in ctx.pages]
            맞는것 = [pg for pg in 것들
                      if "SAAC0103" in pg.url
                      and (표적["cd_com"] in pg.url or f"cno={표적['cno']}" in pg.url)]
            if 맞는것:
                전표화면 = 맞는것[0]
                break
        if 전표화면:
            break
    if 전표화면 is None:
        return None, [새탭], "전자세금계산서 화면이 안 열림"

    전표화면.bring_to_front()
    전표화면.wait_for_timeout(3000)
    h2 = 화면머리(전표화면)
    if not h2["이름"] or not (표적["고객사명"] in h2["이름"] or h2["이름"] in 표적["고객사명"]):
        return None, [새탭, 전표화면], f"전표 화면이 다른 고객사 (화면: {h2['이름']})"

    지금탭 = [pg for ctx in browser.contexts for pg in ctx.pages]
    새로연것 = [pg for pg in 지금탭 if id(pg) not in 전탭]
    return 전표화면, 새로연것, ""


def 매입조회(page, 말하기):
    """구분을 2.매입 으로 바꾸고 조회를 누른다. 돌려주는 것: (건수, 까닭)"""
    이미 = json.loads(page.evaluate(LIKE, {"글": "2. 매입"}))
    if not 이미:
        덩어리 = json.loads(page.evaluate(LIKE, {"글": "1. 매출"}))
        if not 덩어리:
            return -1, "구분 칸을 못 찾음"
        덩어리.sort(key=lambda c: -c["너비"])
        큰것 = 덩어리[0]
        골랐나 = False
        for x, y in ((큰것["오른쪽"] - 10, 큰것["가운데y"]), (큰것["x"], 큰것["y"])):
            page.mouse.click(x, y)
            page.wait_for_timeout(1800)
            것들 = json.loads(page.evaluate(LIKE, {"글": "매입"}))
            고를것 = [c for c in 것들 if c["글자"] in ("2. 매입", "2.매입", "매입")]
            if not 고를것:
                continue
            고를것.sort(key=lambda c: c["y"])
            page.mouse.click(고를것[0]["x"], 고를것[0]["y"])
            page.wait_for_timeout(1800)
            if json.loads(page.evaluate(LIKE, {"글": "2. 매입"})):
                골랐나 = True
                break
        if not 골랐나:
            return -1, "구분을 매입으로 못 바꿈"
    말하기("    구분 2. 매입")

    단추 = json.loads(page.evaluate(BTN, {"글": "조회"}))
    if not 단추:
        return -1, "조회 단추를 못 찾음"
    page.mouse.click(단추[0]["x"], 단추[0]["y"])
    for _ in range(7):
        page.wait_for_timeout(4000)
        rows = 전표읽기(page)
        if rows:
            말하기(f"    조회 {len(rows)}건")
            return len(rows), ""
    return 0, ""
