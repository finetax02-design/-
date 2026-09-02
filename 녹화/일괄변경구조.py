"""일괄변경 화면의 생김새만 살펴본다. 아무것도 바꾸지 않는다.

전체일괄변경을 눌렀더니 이런 안내가 떴다.

    [품명] [유형] [차변계정] [대변계정] [관리] [전표상태] 선택후, 실행하세요.

무엇을 바꿀지 먼저 고르는 단계가 따로 있다는 뜻이다.
그 화면이 어떻게 생겼는지 알아야 유형을 골라 실행할 수 있다.

누르기 전과 뒤의 화면을 견줘 새로 생긴 것만 뽑아 적는다.
값은 하나도 바꾸지 않는다.
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
OUT = HERE / "일괄변경구조.txt"

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


# 본보기 줄을 현재 줄로 만든다
SET_CURRENT = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'nm_trade', fieldName: 'nm_trade' }); }
  catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 90) }); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  return JSON.stringify({ ok: true });
}"""

CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  try { if (g.checkAll) g.checkAll(false); else if (g.resetCheckables) g.resetCheckables(false); } catch (e) {}
  try { g.checkItems(args.rows, true); } catch (e) {
    return JSON.stringify({ ok: false, reason: String(e).slice(0, 120) });
  }
  let after = [];
  try { after = g.getCheckedItemIndices() || []; } catch (e) {}
  return JSON.stringify({ ok: after.length === args.rows.length, 체크: after.length });
}"""

# 화면에 보이는 것을 전부 훑어 적는다. 앞뒤를 견주어 새로 생긴 것을 가려내려는 것이다.
SNAP = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
    if (el.offsetParent === null && el.tagName !== 'BODY') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 3 || r.height < 3) continue;
    if (r.y > innerHeight + 50 || r.x > innerWidth + 50) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
    own = own.trim().replace(/\s+/g, ' ').slice(0, 40);
    const cls = (el.className || '').toString().slice(0, 46);
    const key = [el.tagName, cls, el.id, Math.round(r.x), Math.round(r.y),
                 Math.round(r.width), Math.round(r.height), own].join('|');
    out.push({ key: key, tag: el.tagName.toLowerCase(), cls: cls, id: el.id || '',
               typ: el.type || '', name: el.name || '', 글자: own,
               x: Math.round(r.x), y: Math.round(r.y),
               w: Math.round(r.width), h: Math.round(r.height) });
  }
  return JSON.stringify(out);
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
    out.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 50) });
  }
  return JSON.stringify(out);
}"""

lines = []


def say(t=""):
    print(str(t)[:500])
    lines.append(str(t))


def 저장():
    OUT.write_text("\n".join(lines), encoding="utf-8")


def 찍기(page):
    return {e["key"]: e for e in json.loads(page.evaluate(SNAP))}


def 새로생긴것(앞, 뒤, 제목):
    새것 = [e for k, e in 뒤.items() if k not in 앞]
    새것.sort(key=lambda e: (e["y"], e["x"]))
    say("")
    say(f"===== {제목} : 새로 생긴 것 {len(새것)}개 =====")
    if not 새것:
        say("  화면이 그대로입니다. 아무것도 안 열렸습니다.")
        return 새것
    for e in 새것:
        꼬리 = ""
        if e["typ"]:
            꼬리 += f" type={e['typ']}"
        if e["name"]:
            꼬리 += f" name={e['name']}"
        if e["id"]:
            꼬리 += f" id={e['id']}"
        say(f"  ({e['x']:>4},{e['y']:>4}) {e['w']:>4}x{e['h']:<3} "
            f"<{e['tag']} class=\"{e['cls']}\">{꼬리}  글자[{e['글자']}]")
    return 새것


def 누르기(page, 글자):
    found = json.loads(page.evaluate(FIND, {"text": 글자}))
    if not found:
        return None
    found.sort(key=lambda e: (e["y"], e["x"]))
    t = found[-1]
    page.mouse.click(t["x"], t["y"])
    page.wait_for_timeout(900)
    return t


print()
print("=" * 72)
print("  일괄변경 화면 살펴보기 (아무것도 바꾸지 않습니다)")
print("=" * 72)
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

        # 불공 줄 하나를 본보기로, 과세 줄 하나를 바꿀 줄로 삼는다 (시늉만)
        본 = next((i for i, r in enumerate(rows)
                   if str(r.get("ty_mth2")) == 불공 and str(r.get("cd_notdedct")) in 사유이름), None)
        대 = next((i for i, r in enumerate(rows) if str(r.get("ty_mth2")) == 과세), None)
        if 본 is None or 대 is None:
            say("본보기로 쓸 불공 줄이나 바꿀 과세 줄이 화면에 없습니다.")
            raise SystemExit
        json.loads(page.evaluate(SET_CURRENT, {"row": 본}))
        say(f"본보기 줄: {본 + 1}번째 {rows[본].get('nm_trade')}"
            f" (사유 {rows[본].get('cd_notdedct')})")
        r = json.loads(page.evaluate(CHECK_ROWS, {"rows": [대]}))
        say(f"바꿀 줄: {대 + 1}번째 {rows[대].get('nm_trade')} / 체크 {r.get('체크')}개")

        앞 = 찍기(page)

        t = 누르기(page, "일괄변경")
        if not t:
            say("'일괄변경' 을 화면에서 못 찾았습니다.")
            raise SystemExit
        say(f"'일괄변경' 누름 ({t['x']},{t['y']})")
        뒤 = 찍기(page)
        새것 = 새로생긴것(앞, 뒤, "일괄변경을 누른 뒤")

        print()
        print("  " + "-" * 66)
        print("   화면에 메뉴가 열렸나요? 열렸다면 무엇이 보이는지 봐주세요.")
        print("   여기서 '전체일괄변경' 을 눌러보겠습니다.")
        print("  " + "-" * 66)
        input("\n  진행하려면 Enter >>> ")

        앞2 = 찍기(page)
        t = 누르기(page, "전체일괄변경")
        if not t:
            say("'전체일괄변경' 을 못 찾았습니다.")
        else:
            say(f"'전체일괄변경' 누름 ({t['x']},{t['y']})")
            뒤2 = 찍기(page)
            새로생긴것(앞2, 뒤2, "전체일괄변경을 누른 뒤")

        print()
        print("  " + "-" * 66)
        print("   안내창이 떴으면 화면에서 '확인' 을 눌러 닫아주세요.")
        print("   그 다음 '무엇을 바꿀지 고르는 곳' 이 화면 어디에 있는지")
        print("   찾아서 손으로 열어주세요. (유형을 고르는 곳입니다)")
        print("  " + "-" * 66)
        input("\n  그 화면을 띄운 채로 Enter >>> ")

        앞3 = 찍기(page)
        say("")
        say("===== 지금 화면에 보이는 것 중 고를 만한 것 =====")
        for e in sorted(앞3.values(), key=lambda e: (e["y"], e["x"])):
            글 = e["글자"]
            if e["typ"] in ("checkbox", "radio") or 글 in (
                    "품명", "유형", "차변계정", "대변계정", "관리", "전표상태",
                    "실행", "적용", "확인", "닫기", "취소", "선택"):
                꼬리 = f" type={e['typ']}" if e["typ"] else ""
                꼬리 += f" name={e['name']}" if e["name"] else ""
                꼬리 += f" id={e['id']}" if e["id"] else ""
                say(f"  ({e['x']:>4},{e['y']:>4}) {e['w']:>4}x{e['h']:<3} "
                    f"<{e['tag']} class=\"{e['cls']}\">{꼬리}  글자[{글}]")

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
print("  값은 하나도 바꾸지 않았습니다.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
