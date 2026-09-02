"""과세 -> 불공 일괄변환. 불공제사유까지 한 번에 바꾼다.

위하고 일괄변경의 순서는 이렇다. 사용자가 손으로 하는 것과 같다.

  1 사유가 정확히 들어간 불공 줄 하나를 손으로 만들어 둔다  (본보기 줄)
  2 바꿀 줄들을 전부 체크한다
  3 본보기 줄의 '유형' 칸을 클릭한다
  4 오른쪽 맨 아래 일괄변경 > 전체일괄변경
  5 불공제사유 창이 뜨면 사유를 고르고 확인
  
3번이 핵심이다. 어느 칸을 클릭했는지가 곧 '무엇을 바꿀지' 고르는 것이다.
거래처 칸을 잡은 채로 실행하면
'[품명] [유형] [차변계정] [대변계정] [관리] [전표상태] 선택후, 실행하세요'
라는 안내만 뜬다. 유형 칸을 잡아야 유형이 바뀐다.

5번의 사유 창은 현재 줄의 사유를 미리 골라 놓고 뜬다.
본보기 줄이 현재 줄이므로 본보기의 사유가 이미 골라져 있다.
그래서 라디오를 누를 일이 없다. 여섯 번 실패한 그 라디오다.
다만 정말 그런지 믿지 않고, 무엇이 골라져 있는지 읽어 대조한 뒤에만 확인한다.

안전장치
  - 본보기 줄의 유형과 사유를 잡기 직전에 다시 확인한다
  - 체크한 건수를 화면의 '선택됨 N건' 글자와도 맞춰 본다
  - 사유 창에 골라진 사유가 원하는 것과 다르면 확인하지 않고 멈춘다
  - 바꾼 뒤 실제로 유형과 사유가 들어갔는지 거래처명으로 대조한다
  - 전송(F3)은 절대 부르지 않는다
"""
import collections
import csv
import json
import re
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "일괄변환기록.txt"

과세 = "51"
불공 = "54"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

GRAB = r"""() => {
  // 같은 열 구성을 가진 그리드가 여러 개일 수 있다. 화면에 안 보이는 빈 것도 있다.
  // 그래서 하나만 찾고 멈추지 않고 전부 모은 뒤 자료가 가장 많은 것을 고른다.
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const found = [];
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
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
        let names = [];
        try { names = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (names.includes('nm_acctit_cha')) found.push(v);
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  if (!found.length) return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });

  const 후보 = [];
  let best = null, bestN = -1;
  for (const g of found) {
    let src = g, n = 0, err = '';
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try { n = src.getRowCount() || 0; } catch (e) { err = String(e).slice(0, 60); }
    후보.push({ 건수: n, 오류: err });
    if (n > bestN) { bestN = n; best = { g: g, src: src, n: n }; }
  }
  if (!best || best.n <= 0) {
    return JSON.stringify({ ok: false, reason: '전표 목록은 찾았으나 자료가 없음', 후보: 후보 });
  }
  window.__g = best.g;
  let rows = [], err = '';
  try { rows = best.src.getJsonRows(0, best.n - 1) || []; }
  catch (e) { err = String(e).slice(0, 120); }
  return JSON.stringify({ ok: rows.length > 0, rows: rows, 후보: 후보,
                          reason: rows.length ? '' : ('자료를 읽지 못함 ' + err) });
}"""


# 본보기 줄이 그대로인지 확인하고, 그 줄이 화면에 보이게 한다.
# setCurrent 로는 안 된다. 파란 테두리만 옮길 뿐 위하고는 못 알아듣는다.
# 진짜 마우스로 유형 칸을 눌러야 '유형을 바꾸겠다' 는 뜻이 전달된다.
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
  try { if (typeof g.setTopItem === 'function') g.setTopItem(args.row); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setTopItem ' + String(e).slice(0, 80) }); }
  return JSON.stringify({ ok: true, 거래처: r.nm_trade });
}"""

# 유형 칸이 화면 어디에 있는지 묻는다. 화면 좌표를 그대로 돌려준다.
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

# 바꿀 줄들을 체크한다. 세는 방법이 하나만으로는 못 미더워 여러 가지로 확인한다.
CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  const L = [];
  for (const m of ['checkAll', 'resetCheckables']) {
    try { if (typeof g[m] === 'function') { g[m](false); L.push(m + '(false) 로 초기화'); break; } }
    catch (e) { L.push(m + ' 오류: ' + String(e).slice(0, 80)); }
  }
  try {
    if (typeof g.checkItems === 'function') g.checkItems(args.rows, true);
    else if (typeof g.checkItem === 'function') for (const r of args.rows) g.checkItem(r, true);
    else return JSON.stringify({ ok: false, reason: '체크할 방법이 없음', log: L });
  } catch (e) { return JSON.stringify({ ok: false, reason: '체크 오류 ' + String(e).slice(0, 120), log: L }); }

  let 센수 = -1;
  for (const m of ['getCheckedItemIndices', 'getCheckedRows', 'getCheckedItems']) {
    try {
      if (typeof g[m] === 'function') {
        const v = g[m]();
        if (Array.isArray(v)) { 센수 = v.length; L.push(`${m} 로 ${v.length}줄`); break; }
      }
    } catch (e) {}
  }
  // 위의 것이 못 미더울 때를 대비해 한 줄씩 물어본다
  let 하나씩 = -1;
  try {
    if (typeof g.isCheckedItem === 'function') {
      하나씩 = 0;
      for (const r of args.rows) if (g.isCheckedItem(r)) 하나씩++;
      L.push(`한 줄씩 물어보니 ${하나씩}줄`);
    }
  } catch (e) {}
  return JSON.stringify({ 요청: args.rows.length, 센수: 센수, 하나씩: 하나씩, log: L });
}"""

# 화면 아래의 '선택됨 N건' 글자를 읽는다. 그리드가 세는 것과 맞는지 보려는 것이다.
SELECTED_TEXT = r"""() => {
  for (const el of document.querySelectorAll('span,div,em')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    const m = t.match(/^(\d+)건\s*선택됨$|^선택됨\s*(\d+)건$/);
    if (m) return m[1] || m[2];
  }
  // 글자가 두 조각으로 나뉘어 있을 수 있다
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

# 지금 열려 있는 창을 읽는다.
# 상자를 골라내려 하면 껍데기를 잡는다. 라디오 때와 같다.
# 그래서 고르지 않고 화면의 표와 단추를 있는 그대로 전부 훑는다.
POPUP = r"""() => {
  const 안내 = [], 표 = [], 단추 = [], 라디오 = [], 상자 = [];
  const 보임 = el => {
    if (el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };

  // 칸의 글자를 읽는다. 글자가 없으면 입력칸 안의 값을 본다.
  // 확인창의 변경내용은 글자가 아니라 input 의 값으로 들어 있다.
  const 칸글자 = c => {
    let t = (c.innerText || '').trim();
    if (t) return t;
    const 값 = [];
    for (const i of c.querySelectorAll('input,textarea')) if (i.value) 값.push(i.value);
    for (const sel of c.querySelectorAll('select')) {
      const o = sel.selectedOptions && sel.selectedOptions[0];
      if (o) 값.push(o.text || o.value);
    }
    return 값.join(' ').trim();
  };

  // 화면의 모든 표. 어느 것이 진짜인지 모르니 자리와 함께 다 적는다.
  for (const tb of document.querySelectorAll('table')) {
    if (!보임(tb)) continue;
    const t = (tb.innerText || '');
    if (!/변경항목|변경내용/.test(t)) continue;
    const r = tb.getBoundingClientRect();
    const rows = [];
    for (const tr of tb.rows) rows.push([...tr.cells].map(칸글자));
    표.push({ 자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
              줄: rows.slice(0, 12) });
  }

  // 화면의 모든 단추
  for (const el of document.querySelectorAll('button,[role=button],[class*=btn],[class*=Btn]')) {
    if (!보임(el)) continue;
    const t = (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 20) continue;
    const r = el.getBoundingClientRect();
    단추.push(`${t} (${Math.round(r.x)},${Math.round(r.y)})`);
  }

  // 사유 라디오. 껍데기가 한 벌 더 있으므로 크기가 있는 것만 본다.
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = el.closest('label') || el.parentElement;
    if (!lab || !보임(lab)) continue;
    const t = (lab.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^[0-9A-B][.\s]/.test(t)) continue;
    const r = lab.getBoundingClientRect();
    라디오.push({ 코드: t[0], 글자: t.slice(0, 26), 골라짐: !!el.checked,
                  x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) });
  }

  // 창처럼 보이는 것들의 글자. 고르지 않고 다 적는다.
  for (const el of document.querySelectorAll('[class*=dialog],[class*=Dialog],[class*=modal],[class*=popup],[class*=layer]')) {
    if (!보임(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 40) continue;
    let t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    const 값 = [];
    for (const i of el.querySelectorAll('input[type=text],input:not([type]),textarea')) {
      if (i.value) 값.push(i.value);
    }
    if (값.length) t += ' [입력칸: ' + 값.join(' / ') + ']';
    if (!t) continue;
    상자.push(`(${Math.round(r.x)},${Math.round(r.y)}) ${Math.round(r.width)}x${Math.round(r.height)} `
              + `<${el.tagName.toLowerCase()} class="${(el.className || '').toString().slice(0, 34)}"> ${t.slice(0, 160)}`);
    if (!안내.includes(t)) 안내.push(t.slice(0, 300));
  }

  return JSON.stringify({ 안내: 안내.slice(0, 6), 표: 표, 단추: 단추.slice(0, 60),
                          라디오: 라디오, 상자: 상자.slice(0, 10) });
}"""

# 글자가 정확히 같은 것을 찾아 누른다
FIND = r"""(args) => {
  const out = [];
  for (const el of document.querySelectorAll('button, a, li, span, div, [role=button], [role=menuitem]')) {
    const t = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    if (t !== args.text) continue;
    let inner = true;
    for (const c of el.children) {
      const ct = (c.innerText || c.textContent || '').trim().replace(/\s+/g, ' ');
      if (ct === args.text) { inner = false; break; }
    }
    if (!inner) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    out.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) });
  }
  return JSON.stringify(out);
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


def 저장():
    OUT.write_text("\n".join(lines), encoding="utf-8")


def 누르기(page, 글자):
    found = json.loads(page.evaluate(FIND, {"text": 글자}))
    if not found:
        return None
    found.sort(key=lambda e: (e["y"], e["x"]))
    t = found[-1]
    page.mouse.click(t["x"], t["y"])
    page.wait_for_timeout(900)
    return t


def 창글자(d):
    """창에 적힌 글자를 표까지 싹 모은다"""
    조각 = list(d["안내"])
    for tb in d["표"]:
        for row in tb["줄"]:
            조각 += row
    return " ".join(조각)


def 채워졌나(d):
    """창에 알맹이가 들어왔는지 본다. 표의 머리줄 말고 아랫줄에 글자가 있어야 한다."""
    if d["라디오"]:
        return True
    글 = 창글자(d)
    if "대상이 없습니다" in 글 or "선택후" in 글:
        return True
    for tb in d["표"]:
        for row in tb["줄"][1:]:
            if any(c.strip() for c in row):
                return True
    return False


def 창읽기(page, 제목, 기다림초=8):
    # 창은 먼저 뜨고 알맹이는 그 뒤에 채워진다. 다 채워질 때까지 기다린다.
    남은 = int(기다림초 * 1000)
    d = json.loads(page.evaluate(POPUP))
    잰시간 = 0
    while not 채워졌나(d) and 남은 > 0:
        page.wait_for_timeout(400)
        남은 -= 400
        잰시간 += 400
        d = json.loads(page.evaluate(POPUP))
    say("")
    say(f"===== {제목} =====")
    if 잰시간:
        say(f"  (알맹이가 채워지기까지 {잰시간}밀리초 기다렸습니다)")
    for t in d["상자"]:
        say("  창: " + t)
    for i, tb in enumerate(d["표"]):
        say(f"  [표{i} {tb['자리']}]")
        for row in tb["줄"]:
            say("    " + " | ".join(row))
    if d["라디오"]:
        say("  사유: " + ", ".join(
            f"[{'O' if r['골라짐'] else ' '}]{r['글자']}" for r in d["라디오"]))
    say("  단추: " + (", ".join(d["단추"]) if d["단추"] else "없음"))
    return d


def 라디오누르기(page, d, code):
    """사유 하나를 진짜 마우스로 누르고, 실제로 옮겨졌는지 다시 읽어 돌려준다."""
    표적 = next((r for r in d["라디오"] if r["코드"] == code), None)
    if not 표적:
        return None, d
    page.mouse.click(표적["x"], 표적["y"])
    page.wait_for_timeout(500)
    d2 = json.loads(page.evaluate(POPUP))
    골라진 = [r for r in d2["라디오"] if r["골라짐"]]
    return (골라진[0]["코드"] if len(골라진) == 1 else None), d2


def 사유창(page, d, code):
    """사유 창이면 사유를 제대로 옮기고 확인한다. 진행해도 되면 True.

    창에는 바라던 사유가 이미 골라진 것처럼 보인다. 그런데 위하고가
    실제로 쓰는 값은 따로 있고 거기엔 4 가 남아 있다. 이미 표시가 있는
    자리를 눌러봐야 '바뀜' 이 일어나지 않아 전달되지 않는다.
    그래서 다른 사유를 한 번 거쳐 갔다가 바라던 사유로 돌아온다.
    두 번 다 '바뀜' 이 일어나므로 위하고가 알아듣는다.
    """
    if not d["라디오"]:
        return True
    있는코드 = {r["코드"] for r in d["라디오"]}
    if code not in 있는코드:
        say(f"  [멈춤] 사유 {code} 가 창에 없습니다. 있는 것: {sorted(있는코드)}")
        say("  화면의 취소(esc) 단추를 눌러주세요.")
        return False

    딴것 = next((c for c in ("4", "3", "0", "1", "2") if c in 있는코드 and c != code), None)
    if 딴것 is None:
        say("  [멈춤] 거쳐 갈 다른 사유가 없습니다.")
        say("  화면의 취소(esc) 단추를 눌러주세요.")
        return False

    처음 = [r["코드"] for r in d["라디오"] if r["골라짐"]]
    say(f"  창이 뜰 때 표시된 사유: {처음 or '없음'}")

    골라진, d = 라디오누르기(page, d, 딴것)
    say(f"  거쳐 가려고 사유 {딴것} 를 눌렀더니 → {골라진 or '읽지 못함'}")
    if 골라진 != 딴것:
        say("  [멈춤] 사유를 눌러도 옮겨지지 않습니다.")
        say("  화면의 취소(esc) 단추를 눌러 닫아주세요. 사유가 잘못 들어가면 안 됩니다.")
        return False

    골라진, d = 라디오누르기(page, d, code)
    say(f"  바라던 사유 {code} 를 눌렀더니 → {골라진 or '읽지 못함'}")
    if 골라진 != code:
        say(f"  [멈춤] 사유 {code} 로 옮기지 못했습니다.")
        say("  화면의 취소(esc) 단추를 눌러 닫아주세요.")
        return False

    say(f"  사유 {code} {사유이름.get(code, '')} 로 제대로 옮겼습니다.")
    if input("\n  이 사유로 확인할까요? (y) >>> ").strip().lower() != "y":
        say("사용자가 중단했습니다. 화면의 취소(esc) 를 눌러주세요.")
        return False
    for 글자 in ("선택(enter)", "선택(Enter)", "확인(Enter)", "확인(enter)", "선택", "확인"):
        if 누르기(page, 글자):
            say(f"  '{글자}' 누름")
            return True
    say("  확인 단추를 못 찾았습니다. 손으로 눌러주세요.")
    return False


print()
print("=" * 72)
print("  과세 -> 불공 일괄변환 (불공제사유까지 한 번에)")
print("=" * 72)
print()

if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    print("  24_불공규칙.bat 을 먼저 돌려주세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = (r.get("사유코드") or "").strip()
        if r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y") and code in 사유이름:
            rules[r["사업자번호"].strip()] = code
print(f"  규칙표 {len(rules)}곳 (사유 3, 4, 5 만)")
print()
print("  전자세금계산서 화면을 띄우고 조회를 마친 상태여야 합니다.")
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "smarta.wehago.com" in pg.url]
        if not pages:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit
        pages.sort(key=lambda pg: "SAAC0103" not in pg.url)
        say(f"위하고 탭 {len(pages)}개를 봅니다.")

        page, rows = None, None
        for pg in pages:
            꼬리 = pg.url.split("/#/")[-1][:60]
            try:
                d = json.loads(pg.evaluate(GRAB))
            except Exception as e:
                say(f"  탭 {꼬리} : 읽기 실패 {str(e)[:80]}")
                continue
            if d.get("ok") and d.get("rows"):
                page, rows = pg, d["rows"]
                say(f"  탭 {꼬리} : 전표 {len(rows)}건")
                break
            say(f"  탭 {꼬리} : {d.get('reason') or '자료 없음'}")
        if page is None:
            say("")
            say("자료가 들어 있는 전자세금계산서 탭을 찾지 못했습니다.")
            say("전자세금계산서 화면에서 조회를 한 번 더 누른 뒤 다시 실행해주세요.")
            raise SystemExit
        page.bring_to_front()

        대상 = collections.defaultdict(list)
        본보기 = collections.defaultdict(list)
        for i, r in enumerate(rows):
            ty = str(r.get("ty_mth2") or "")
            cd = str(r.get("cd_notdedct") or "")
            if ty == 불공 and cd in 사유이름:
                # 규칙표와 어긋나는 줄은 본보기로 쓰지 않는다.
                # 잘못 들어간 줄이 본보기가 되어 잘못을 퍼뜨리면 안 된다.
                규칙 = rules.get(str(r.get("no_bisocial") or ""))
                if 규칙 is None or 규칙 == cd:
                    본보기[cd].append(i)
            elif ty == 과세:
                code = rules.get(str(r.get("no_bisocial") or ""))
                if code:
                    대상[code].append(i)

        say("")
        say(f"불공으로 바꿀 건 {sum(len(v) for v in 대상.values())}건")
        for c in sorted(사유이름):
            say(f"  사유 {c} {사유이름[c]}: 바꿀 줄 {len(대상.get(c, []))}건"
                f" / 본보기로 쓸 수 있는 줄 {len(본보기.get(c, []))}건")
        if not 대상:
            say("바꿀 건이 없습니다.")
            raise SystemExit

        code = input("\n  이번에 처리할 사유 (3/4/5) >>> ").strip()
        if code not in 대상 or not 대상[code]:
            print(f"  사유 {code} 로 바꿀 줄이 없습니다.")
            raise SystemExit
        if not 본보기.get(code):
            print()
            print(f"  화면에 사유 {code} 인 불공 줄이 하나도 없습니다.")
            print("  일괄변경은 본보기 줄을 그대로 베끼는 방식이라 본보기가 꼭 필요합니다.")
            print(f"  아무 줄이나 하나를 손으로 불공 + 사유 {code} 로 바꾼 뒤 다시 실행해주세요.")
            raise SystemExit

        tmpl = 본보기[code][0]
        t = rows[tmpl]
        say("")
        say(f"본보기 줄: {tmpl + 1}번째  {t.get('s_date')}  {t.get('nm_trade')}"
            f"  유형 {t.get('ty_mth2')}  사유 {t.get('cd_notdedct')}")
        say(f"바꿀 줄 {len(대상[code])}건:")
        for i in 대상[code][:40]:
            r = rows[i]
            say(f"  {i + 1:>4}번째  {r.get('s_date')}  {r.get('nm_trade')}"
                f"  {r.get('mn_mnam')}  {r.get('nm_good')}")
        if len(대상[code]) > 40:
            say(f"  ... 그 밖에 {len(대상[code]) - 40}건")

        print()
        시험 = input("  먼저 1건만 해볼까요? (y/n, 처음이면 y) >>> ").strip().lower() != "n"
        묶음 = 대상[code][:1] if 시험 else 대상[code]

        # 1 바꿀 줄 체크 (사람이 하는 차례대로 체크가 먼저다)
        res = json.loads(page.evaluate(CHECK_ROWS, {"rows": 묶음}))
        say("")
        for line in res.get("log", []):
            say("  " + line)
        화면수 = page.evaluate(SELECTED_TEXT)
        say(f"  화면의 선택됨 글자: {화면수 or '못 읽음'}건")
        센것 = [n for n in (res.get("센수"), res.get("하나씩")) if n is not None and n >= 0]
        if 화면수.isdigit():
            센것.append(int(화면수))
        if not 센것 or max(센것) != len(묶음):
            say(f"  [멈춤] {len(묶음)}줄을 체크하려 했는데 센 값이 {센것} 입니다.")
            say("  체크가 제대로 안 들어갔습니다. 진행하지 않습니다.")
            raise SystemExit
        say(f"  {len(묶음)}줄 체크 확인")

        # 2 본보기 줄의 유형 칸을 진짜 마우스로 누른다.
        #   어느 칸을 눌렀는지가 곧 '무엇을 바꿀지' 고르는 것이다.
        res = json.loads(page.evaluate(PREP_TEMPLATE,
                                       {"row": tmpl, "want_ty": 불공, "want_cd": code}))
        if not res.get("ok"):
            say(f"본보기 줄을 준비하지 못했습니다: {res.get('reason')}")
            raise SystemExit
        page.wait_for_timeout(500)
        bd = json.loads(page.evaluate(CELL_BOUNDS, {"row": tmpl}))
        if not bd.get("ok"):
            say(f"유형 칸의 자리를 못 얻었습니다: {bd.get('reason')}")
            raise SystemExit
        x = bd["x"] + bd["w"] / 2
        y = bd["y"] + bd["h"] / 2
        if not (0 < x < 4000 and 0 < y < 3000):
            say(f"유형 칸이 화면 밖입니다 ({x:.0f},{y:.0f}).")
            raise SystemExit
        page.mouse.click(x, y)
        page.wait_for_timeout(500)
        cur = json.loads(page.evaluate(CURRENT))
        if cur.get("itemIndex") != tmpl or cur.get("fieldName") != "ty_mth2":
            say(f"  [멈춤] 유형 칸을 눌렀는데 잡힌 것이 다릅니다: {cur}")
            raise SystemExit
        say(f"  본보기 줄 {res.get('거래처')} 의 유형 칸을 눌렀습니다"
            f" ({x:.0f},{y:.0f} / 잡힌 칸 {cur.get('fieldName')})")

        # 칸을 누르는 사이에 체크가 풀리지 않았는지 다시 본다
        화면수2 = page.evaluate(SELECTED_TEXT)
        if 화면수2.isdigit() and int(화면수2) != len(묶음):
            say(f"  [멈춤] 칸을 누른 뒤 선택됨이 {화면수2}건으로 바뀌었습니다"
                f" ({len(묶음)}건이어야 합니다).")
            raise SystemExit
        say(f"  칸을 누른 뒤에도 선택됨 {화면수2 or '못 읽음'}건")

        첫줄 = rows[묶음[0]]
        print()
        print("  " + "-" * 66)
        print("   화면에서 세 가지를 확인해주세요.")
        print()
        print(f"   1) 본보기 줄  {tmpl + 1}번째  {t.get('s_date')} {t.get('nm_trade')}")
        print(f"      -> 그 줄의 '유형' 칸(불공)을 눌러 두었습니다. 잡혀 있어야 합니다.")
        print(f"   2) 바꿀 줄 {len(묶음)}건 (첫 줄: {묶음[0] + 1}번째 {첫줄.get('nm_trade')})")
        print(f"      -> 체크표시가 들어가 있어야 합니다.")
        print(f"   3) 화면 왼쪽 아래에 '{len(묶음)}건 선택됨' 이 보여야 합니다.")
        print("  " + "-" * 66)
        if input("\n  이대로 맞으면 y, 아니면 Enter >>> ").strip().lower() != "y":
            say("사용자가 중단했습니다. 값은 바꾸지 않았습니다.")
            raise SystemExit

        # 3 일괄변경 > 전체일괄변경
        if not 누르기(page, "일괄변경"):
            say("오른쪽 아래 '일괄변경' 을 못 찾았습니다.")
            raise SystemExit
        say("'일괄변경' 누름")
        if not 누르기(page, "전체일괄변경"):
            say("'전체일괄변경' 을 못 찾았습니다.")
            raise SystemExit
        say("'전체일괄변경' 누름")

        d = 창읽기(page, "전체일괄변경을 누른 뒤")
        글전체 = 창글자(d)
        if "대상이 없습니다" in 글전체 or "선택후" in 글전체:
            say("")
            say("  [멈춤] 위하고가 바꿀 대상을 못 알아봤습니다.")
            say("  화면의 확인을 눌러 닫아주세요. 아무것도 바뀌지 않았습니다.")
            raise SystemExit

        # 4 사유 창이 먼저 뜨는 경우
        if d["라디오"]:
            if not 사유창(page, d, code):
                raise SystemExit
            d = 창읽기(page, "사유를 고른 뒤")

        # 5 마무리 확인창이 있으면 내용과 건수를 대조한다
        글전체 = 창글자(d)
        if d["표"] or "일괄변경 하시겠" in 글전체:
            if "불공" not in 글전체:
                say("  [멈춤] 확인창의 변경내용이 비어 있습니다.")
                say("  무엇을 바꿀지가 위하고에 전달되지 않았습니다.")
                say("  확인하지 않습니다. 화면의 닫기를 눌러주세요.")
                raise SystemExit
            숫자 = [int(n) for tb in d["표"] for row in tb["줄"] for c in row
                    for n in re.findall(r"\b(\d+)\b", c)]
            if 숫자 and len(묶음) not in 숫자:
                say(f"  [멈춤] 확인창의 숫자 {숫자} 가 체크한 {len(묶음)}건과 다릅니다.")
                say("  확인하지 않습니다. 화면의 닫기를 눌러주세요.")
                raise SystemExit
            say(f"  확인창에 불공으로 바꾼다고 적혀 있습니다.")
            if input("\n  확인을 눌러 실제로 바꿀까요? (y) >>> ").strip().lower() != "y":
                say("사용자가 중단했습니다. 화면의 닫기를 눌러주세요.")
                raise SystemExit
            눌렀나 = False
            for 글자 in ("확인(Enter)", "확인(enter)", "확인"):
                if 누르기(page, 글자):
                    say(f"  '{글자}' 누름")
                    눌렀나 = True
                    break
            if not 눌렀나:
                say("  확인 단추를 못 찾았습니다. 손으로 눌러주세요.")
                raise SystemExit

            # 확인을 누른 뒤에 사유 창이 뜨는 경우도 있다
            page.wait_for_timeout(800)
            d = 창읽기(page, "확인을 누른 뒤", 기다림초=3)
            if not 사유창(page, d, code):
                raise SystemExit

        page.wait_for_timeout(1500)

        # 6 결과 대조
        after = json.loads(page.evaluate(GRAB))
        if not after.get("ok"):
            say("바꾼 뒤 목록을 다시 읽지 못했습니다. 화면을 확인해주세요.")
            raise SystemExit
        arows = after["rows"]
        성공, 실패 = 0, []
        for i in 묶음:
            if i >= len(arows):
                실패.append((i, "줄이 사라짐"))
                continue
            r = arows[i]
            if str(r.get("nm_trade") or "") != str(rows[i].get("nm_trade") or ""):
                실패.append((i, "다른 줄로 밀림"))
                continue
            ty, cd = str(r.get("ty_mth2") or ""), str(r.get("cd_notdedct") or "")
            if ty == 불공 and cd == code:
                성공 += 1
            else:
                실패.append((i, f"유형 {ty} 사유 {cd}"))

        say("")
        say("===== 결과 =====")
        say(f"  바뀐 줄 {성공} / {len(묶음)}")
        for i, why in 실패[:20]:
            이름 = arows[i].get("nm_trade") if i < len(arows) else ""
            say(f"  안 바뀜 {i + 1}번째 {이름} : {why}")
        if 실패:
            say("")
            say("  하나라도 어긋나면 나머지는 진행하지 않습니다.")
        elif 시험:
            say("")
            say(f"  1건이 제대로 바뀌었습니다. 다시 실행해서 n 을 고르면"
                f" 남은 {len(대상[code]) - 1}건을 한 번에 바꿉니다.")
        say("")
        say("  전송(F3)은 부르지 않았습니다. 전송은 눈으로 확인하고 직접 하세요.")

except SystemExit:
    pass
except Exception:
    say("")
    say("실패했습니다. 원인:")
    say(traceback.format_exc())

저장()
print()
print("=" * 72)
print(f"  기록 저장됨: {OUT}")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
