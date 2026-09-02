"""불공제사유 라디오를 움직이는 방법을 찾는다. 마지막 선택은 누르지 않는다.

일괄변경까지는 다 된다. 유형도 불공으로 바뀐다.
그런데 사유만 늘 4 로 들어간다. 창에는 5 가 골라진 것처럼 보이는데도 그렇다.
보이는 표시와 위하고가 실제로 쓰는 값이 다른 것이고,
라디오가 '바뀌어야' 그 값이 갱신된다.

좌표를 눌러봤지만 움직이지 않았다. 그래서 이 창에서 쓸 수 있는 방법을
하나씩 다 시험해 본다. 누를 때마다 실제로 옮겨졌는지 읽어 확인한다.

선택(enter)은 절대 누르지 않는다. 끝나면 사람이 취소(esc)를 눌러 닫는다.
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
OUT = HERE / "사유시험.txt"

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



# 본보기 줄이 그대로인지 확인하고 화면에 보이게 한다
PREP_TEMPLATE = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  let src = g;
  try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
  let r = null;
  try { r = src.getJsonRows(args.row, args.row)[0]; } catch (e) {}
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
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

CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  try { if (g.checkAll) g.checkAll(false); } catch (e) {}
  try { g.checkItems(args.rows, true); } catch (e) {
    return JSON.stringify({ ok: false, reason: String(e).slice(0, 100) });
  }
  let n = -1;
  try { n = (g.getCheckedRows() || []).length; } catch (e) {}
  return JSON.stringify({ ok: true, 체크: n });
}"""

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

# 라디오 하나하나를 낱낱이 살핀다
RADIO_INFO = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = el.closest('label') || el.parentElement;
    if (!lab) continue;
    const lr = lab.getBoundingClientRect();
    const t = (lab.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^[0-9A-B][.\s]/.test(t)) continue;
    const ir = el.getBoundingClientRect();
    const cx = Math.round(lr.x + lr.width / 2), cy = Math.round(lr.y + lr.height / 2);
    const 맞은것 = document.elementFromPoint(cx, cy);
    const 리액트 = Object.keys(el).filter(k => k.startsWith('__react'));
    const 리액트라벨 = Object.keys(lab).filter(k => k.startsWith('__react'));
    out.push({
      코드: t[0], 글자: t.slice(0, 24), 골라짐: !!el.checked,
      값: el.value, 이름: el.name, id: el.id, disabled: !!el.disabled,
      라벨자리: `${Math.round(lr.x)},${Math.round(lr.y)} ${Math.round(lr.width)}x${Math.round(lr.height)}`,
      칸자리: `${Math.round(ir.x)},${Math.round(ir.y)} ${Math.round(ir.width)}x${Math.round(ir.height)}`,
      라벨x: cx, 라벨y: cy,
      칸x: Math.round(ir.x + ir.width / 2), 칸y: Math.round(ir.y + ir.height / 2),
      맞은것: 맞은것 ? `${맞은것.tagName.toLowerCase()}.${(맞은것.className||'').toString().slice(0,26)}` : '없음',
      리액트: 리액트.join(',') + ' | 라벨 ' + 리액트라벨.join(','),
    });
  }
  return JSON.stringify(out);
}"""

# 골라진 사유를 읽는다
CHECKED = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = el.closest('label') || el.parentElement;
    if (!lab) continue;
    const t = (lab.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^[0-9A-B][.\s]/.test(t)) continue;
    if (el.checked) out.push(t[0]);
  }
  return JSON.stringify(out);
}"""

# 자바스크립트 쪽에서 해볼 수 있는 방법들
DO = r"""(args) => {
  let 표적 = null, 라벨 = null;
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = el.closest('label') || el.parentElement;
    if (!lab) continue;
    const t = (lab.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^[0-9A-B][.\s]/.test(t)) continue;
    if (t[0] === args.code) { 표적 = el; 라벨 = lab; break; }
  }
  if (!표적) return JSON.stringify({ ok: false, reason: '그 사유를 못 찾음' });
  const 말 = [];
  try {
    if (args.how === 'labelclick') 라벨.click();
    else if (args.how === 'inputclick') 표적.click();
    else if (args.how === 'nativeset') {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'checked').set;
      setter.call(표적, true);
      표적.dispatchEvent(new Event('input', { bubbles: true }));
      표적.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (args.how === 'react') {
      const 부르기 = (el, 이름) => {
        for (const k of Object.keys(el)) {
          if (!k.startsWith('__reactProps')) continue;
          const p = el[k];
          if (p && typeof p[이름] === 'function') {
            p[이름]({ target: el, currentTarget: el, type: 이름.slice(2).toLowerCase(),
                      stopPropagation() {}, preventDefault() {}, nativeEvent: {} });
            말.push(`${이름} 를 ${el.tagName.toLowerCase()} 에서 불렀음`);
            return true;
          }
        }
        return false;
      };
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'checked').set;
      setter.call(표적, true);
      if (!부르기(표적, 'onChange')) 말.push('입력칸에 onChange 없음');
      if (!부르기(표적, 'onClick')) 말.push('입력칸에 onClick 없음');
      if (!부르기(라벨, 'onClick')) 말.push('라벨에 onClick 없음');
    }
  } catch (e) { 말.push('오류 ' + String(e).slice(0, 90)); }
  return JSON.stringify({ ok: true, 말: 말 });
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


def 골라진(page):
    return json.loads(page.evaluate(CHECKED))


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
print("  불공제사유 라디오 시험 (선택은 누르지 않습니다)")
print("=" * 72)
print()
print("  전자세금계산서 화면을 띄우고 조회를 마친 상태여야 합니다.")
print("  마지막에 사람이 취소(esc) 단추를 눌러 닫아주셔야 합니다.")
input("\n  준비되었으면 Enter >>> ")

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
                   if str(r.get("ty_mth2")) == 불공 and str(r.get("cd_notdedct")) in 사유이름), None)
        대 = next((i for i, r in enumerate(rows) if str(r.get("ty_mth2")) == 과세), None)
        if 본 is None or 대 is None:
            say("본보기로 쓸 불공 줄이나 바꿀 과세 줄이 없습니다.")
            raise SystemExit
        say(f"본보기 줄: {본 + 1}번째 {rows[본].get('nm_trade')} (사유 {rows[본].get('cd_notdedct')})")
        say(f"바꿀 줄: {대 + 1}번째 {rows[대].get('nm_trade')}")

        r = json.loads(page.evaluate(CHECK_ROWS, {"rows": [대]}))
        say(f"체크 {r.get('체크')}줄")
        json.loads(page.evaluate(PREP_TEMPLATE, {"row": 본}))
        page.wait_for_timeout(500)
        bd = json.loads(page.evaluate(CELL_BOUNDS, {"row": 본}))
        if not bd.get("ok"):
            say(f"유형 칸의 자리를 못 얻었습니다: {bd.get('reason')}")
            raise SystemExit
        page.mouse.click(bd["x"] + bd["w"] / 2, bd["y"] + bd["h"] / 2)
        page.wait_for_timeout(500)
        say("본보기 줄의 유형 칸을 눌렀습니다")

        if not 누르기(page, "일괄변경"):
            say("'일괄변경' 을 못 찾았습니다.")
            raise SystemExit
        if not 누르기(page, "전체일괄변경"):
            say("'전체일괄변경' 을 못 찾았습니다.")
            raise SystemExit
        page.wait_for_timeout(1200)
        if not 누르기(page, "확인(Enter)"):
            say("'확인(Enter)' 을 못 찾았습니다.")
            raise SystemExit
        page.wait_for_timeout(1200)

        info = json.loads(page.evaluate(RADIO_INFO))
        if not info:
            say("사유 창이 안 떴습니다.")
            raise SystemExit
        say("")
        say(f"===== 사유 라디오 {len(info)}개 =====")
        for r in info:
            say(f"  [{'O' if r['골라짐'] else ' '}] {r['글자']}")
            say(f"      값={r['값']} 이름={r['이름']} id={r['id']} 못쓰게됨={r['disabled']}")
            say(f"      라벨 {r['라벨자리']} 가운데({r['라벨x']},{r['라벨y']})"
                f" -> 그 자리에 있는 것: {r['맞은것']}")
            say(f"      입력칸 {r['칸자리']}")
            say(f"      리액트 {r['리액트']}")

        처음 = 골라진(page)
        say("")
        say(f"지금 골라진 것: {처음}")

        방법들 = ["라벨좌표", "입력칸좌표", "labelclick", "inputclick", "nativeset", "react"]
        say("")
        say("===== 방법을 하나씩 시험 (목표: 4 로 옮기기) =====")
        통한것 = None
        for how in 방법들:
            앞 = 골라진(page)
            표적 = next((r for r in info if r["코드"] == "4"), None)
            if not 표적:
                say("  사유 4 가 없습니다.")
                break
            말 = []
            if how == "라벨좌표":
                page.mouse.click(표적["라벨x"], 표적["라벨y"])
            elif how == "입력칸좌표":
                page.mouse.click(표적["칸x"], 표적["칸y"])
            else:
                res = json.loads(page.evaluate(DO, {"code": "4", "how": how}))
                말 = res.get("말", [])
            page.wait_for_timeout(500)
            뒤 = 골라진(page)
            say(f"  {how:<12} {앞} -> {뒤}" + ("   " + " / ".join(말) if 말 else ""))
            if 뒤 == ["4"]:
                통한것 = how
                say(f"  >>> '{how}' 로 사유가 옮겨졌습니다.")
                break

        if 통한것:
            say("")
            say(f"===== '{통한것}' 로 다시 5 로 옮겨보기 =====")
            표적 = next((r for r in info if r["코드"] == "5"), None)
            if 통한것 == "라벨좌표":
                page.mouse.click(표적["라벨x"], 표적["라벨y"])
            elif 통한것 == "입력칸좌표":
                page.mouse.click(표적["칸x"], 표적["칸y"])
            else:
                page.evaluate(DO, {"code": "5", "how": 통한것})
            page.wait_for_timeout(500)
            say(f"  결과: {골라진(page)}")
        else:
            say("")
            say("  어떤 방법으로도 사유가 옮겨지지 않았습니다.")

        say("")
        say("  선택(enter)은 누르지 않았습니다.")
        print()
        print("  " + "-" * 66)
        print("   화면의 취소(esc) 단추를 눌러 창을 닫아주세요.")
        print("  " + "-" * 66)
        input("\n  닫으셨으면 Enter >>> ")

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
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
