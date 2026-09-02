"""유형 칸을 진짜로 클릭할 방법을 찾는다. 아무것도 바꾸지 않는다.

setCurrent 로 파란 테두리는 옮겼는데 일괄변경의 변경내용이 비어 있었다.
위하고가 '어느 칸이 골라졌는지' 를 자기 상태에 기억해 두는데,
setCurrent 는 그 기억을 만드는 이벤트를 일으키지 않는 것으로 보인다.
setValue 로 값을 바꿔도 전표상태가 안 따라와 onCellEdited 를 직접
불러야 했던 것과 같은 일이다.

진짜 마우스로 칸을 클릭하면 된다. 캔버스라 칸의 화면 좌표를 알아내야 한다.
RealGrid 에 칸의 자리를 알려주는 함수가 있는지, 없으면 어떤 이벤트를
직접 부를 수 있는지 살펴본다.

읽기만 한다. 값은 하나도 바꾸지 않는다.
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
OUT = HERE / "셀클릭시험.txt"

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



# 그리드가 가진 함수 이름을 훑는다. 자리를 알려주는 것과 이벤트를 가려낸다.
METHODS = r"""() => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false });
  const names = new Set();
  let o = g;
  for (let d = 0; d < 6 && o; d++) {
    for (const k of Object.getOwnPropertyNames(o)) names.add(k);
    o = Object.getPrototypeOf(o);
  }
  const 자리 = [], 이벤트 = [], 고르기 = [], 보이기 = [];
  for (const k of names) {
    let t = '';
    try { t = typeof g[k]; } catch (e) { continue; }
    if (/^(rect|bound)/i.test(k) || /(Rect|Bounds|Position)$/.test(k)) {
      if (t === 'function') 자리.push(k);
    }
    if (/^on[A-Z]/.test(k)) 이벤트.push(k + (t === 'function' ? '()' : ':' + t));
    if (t === 'function' && /select|current|focus/i.test(k)) 고르기.push(k);
    if (t === 'function' && /show|scroll|top|display|view/i.test(k)) 보이기.push(k);
  }
  const 뽑기 = a => a.sort().slice(0, 60);
  return JSON.stringify({ ok: true, 자리: 뽑기(자리), 이벤트: 뽑기(이벤트),
                          고르기: 뽑기(고르기), 보이기: 뽑기(보이기) });
}"""

# 줄이 화면에 보이도록 하고, 유형 칸의 화면 좌표를 알아낸다.
CELL_RECT = r"""(args) => {
  const g = window.__g;
  const L = [];
  // 먼저 그 줄이 화면에 보이게 한다
  for (const m of ['showItem', 'scrollToItem', 'setTopItem', 'showCell']) {
    try {
      if (typeof g[m] === 'function') {
        if (m === 'showCell') g[m](args.row, 'ty_mth2');
        else g[m](args.row);
        L.push(m + ' 로 줄을 보이게 함');
        break;
      }
    } catch (e) { L.push(m + ' 오류 ' + String(e).slice(0, 60)); }
  }
  // 칸의 자리를 물어본다. 이름이 프로그램마다 달라 여러 가지로 물어본다.
  let rect = null, 쓴법 = '';
  const 시도 = [
    ['getCellRect', [args.row, 'ty_mth2']],
    ['getCellBounds', [args.row, 'ty_mth2']],
    ['getCellRect', [{ itemIndex: args.row, column: 'ty_mth2' }]],
    ['getItemRect', [args.row]],
    ['getItemBounds', [args.row]],
  ];
  for (const [m, a] of 시도) {
    try {
      if (typeof g[m] !== 'function') continue;
      const v = g[m].apply(g, a);
      if (v && typeof v === 'object' && ('x' in v || 'left' in v)) {
        rect = { x: v.x !== undefined ? v.x : v.left, y: v.y !== undefined ? v.y : v.top,
                 w: v.width !== undefined ? v.width : (v.right - v.left),
                 h: v.height !== undefined ? v.height : (v.bottom - v.top) };
        쓴법 = m + '(' + a.map(x => JSON.stringify(x)).join(', ') + ')';
        break;
      }
      L.push(m + ' 가 돌려준 것: ' + JSON.stringify(v).slice(0, 80));
    } catch (e) { L.push(m + ' 오류 ' + String(e).slice(0, 60)); }
  }
  // 그리드가 놓인 자리를 알아야 화면 좌표로 옮길 수 있다
  let box = null;
  const el = document.getElementById('GRID_TOP');
  if (el) { const r = el.getBoundingClientRect();
            box = { x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height) }; }
  return JSON.stringify({ rect: rect, 쓴법: 쓴법, box: box, log: L });
}"""

# 지금 무엇이 골라져 있는지 읽는다. 손으로 클릭한 뒤와 견주려는 것이다.
STATE = r"""() => {
  const g = window.__g;
  const out = {};
  for (const m of ['getCurrent', 'getSelection', 'getSelections', 'getSelectedRows',
                   'getCurrentColumn', 'getCurrentField', 'getFocusedColumn']) {
    try { if (typeof g[m] === 'function') out[m] = JSON.stringify(g[m]()).slice(0, 200); }
    catch (e) { out[m] = '오류 ' + String(e).slice(0, 50); }
  }
  return JSON.stringify(out);
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


print()
print("=" * 72)
print("  유형 칸 클릭 방법 찾기 (아무것도 바꾸지 않습니다)")
print("=" * 72)
print()
print("  전자세금계산서 화면을 띄우고 조회를 마친 상태여야 합니다.")
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "smarta.wehago.com" in pg.url]
        pages.sort(key=lambda pg: "SAAC0103" not in pg.url)
        page, rows = None, None
        for pg in pages:
            try:
                d = json.loads(pg.evaluate(GRAB))
            except Exception:
                continue
            if d.get("ok") and d.get("rows"):
                page, rows = pg, d["rows"]
                break
        if page is None:
            say("자료가 들어 있는 전자세금계산서 탭을 찾지 못했습니다.")
            raise SystemExit
        page.bring_to_front()
        say(f"전표 {len(rows)}건")

        본 = next((i for i, r in enumerate(rows)
                   if str(r.get("ty_mth2")) == 불공 and str(r.get("cd_notdedct")) in 사유이름), 0)
        say(f"본보기 줄: {본 + 1}번째 {rows[본].get('nm_trade')}"
            f" (유형 {rows[본].get('ty_mth2')} 사유 {rows[본].get('cd_notdedct')})")

        say("")
        say("===== 그리드가 가진 함수 =====")
        m = json.loads(page.evaluate(METHODS))
        for 이름 in ("자리", "고르기", "보이기", "이벤트"):
            say(f"  [{이름}] " + ", ".join(m.get(이름, [])))

        say("")
        say("===== 칸의 화면 좌표 =====")
        cr = json.loads(page.evaluate(CELL_RECT, {"row": 본}))
        for line in cr["log"]:
            say("  " + line)
        say(f"  그리드 자리: {cr['box']}")
        if cr["rect"]:
            say(f"  칸 자리: {cr['rect']}  ({cr['쓴법']})")
        else:
            say("  칸 자리를 알려주는 함수를 못 찾았습니다.")

        say("")
        say("===== 지금 골라진 것 (setCurrent 전) =====")
        for k, v in json.loads(page.evaluate(STATE)).items():
            say(f"  {k}: {v}")

        print()
        print("  " + "-" * 66)
        print(f"   이제 손으로 해주세요.")
        print(f"   {본 + 1}번째 줄({rows[본].get('nm_trade')})의 '유형' 칸을")
        print("   마우스로 한 번 클릭해주세요. 다른 칸 말고 유형 칸입니다.")
        print("  " + "-" * 66)
        input("\n  클릭하셨으면 Enter >>> ")

        say("")
        say("===== 손으로 클릭한 뒤 =====")
        for k, v in json.loads(page.evaluate(STATE)).items():
            say(f"  {k}: {v}")
        cr2 = json.loads(page.evaluate(CELL_RECT, {"row": 본}))
        if cr2["rect"]:
            say(f"  칸 자리: {cr2['rect']}  ({cr2['쓴법']})")

        # 좌표를 알아냈다면 그 자리를 마우스로 눌러보고 같은 상태가 되는지 본다
        if cr2["rect"] and cr2["box"]:
            r, b = cr2["rect"], cr2["box"]
            # 그리드 안쪽 좌표인지 화면 좌표인지 몰라 두 가지로 헤아려 본다
            후보 = [(b["x"] + r["x"] + r["w"] / 2, b["y"] + r["y"] + r["h"] / 2),
                    (r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)]
            say("")
            say("===== 그 자리를 눌러보기 =====")
            for x, y in 후보:
                if not (0 < x < 3000 and 0 < y < 2000):
                    say(f"  ({x:.0f},{y:.0f}) 는 화면 밖이라 건너뜁니다")
                    continue
                say(f"  ({x:.0f},{y:.0f}) 를 눌러봅니다")
                page.mouse.click(x, y)
                page.wait_for_timeout(600)
                st = json.loads(page.evaluate(STATE))
                say("    getCurrent: " + str(st.get("getCurrent"))[:160])

except SystemExit:
    pass
except Exception:
    say("")
    say("실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 72)
print(f"  기록 저장됨: {OUT}")
print("  값은 하나도 바꾸지 않았습니다.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
