"""수임처 화면에서 이름으로 찾아 회계를 눌러 고객사를 연다.

주소로는 고객사가 안 바뀐다. 시험해보니 이랬다.
  주소는 바뀌는데 화면은 25초 내내 앞 고객사 그대로였다
  새로고침하니 조은세무법인, 곧 고객사가 아예 풀렸다

고객사는 수임처 화면에서 회계를 눌러야 잡힌다.
그러면 그 누르는 것을 대신하면 된다. 평소 손으로 하시는 그 동작이다.

  1 수임처 화면에서 검색칸에 고객사명을 넣는다
  2 그 이름이 든 줄의 회계 단추를 찾는다
  3 하나뿐인지 확인하고 누른다
  4 새로 열린 화면의 고객사명이 맞는지 대조한다

누르기 전에 무엇을 누를지 보여주고 물어본다.
전표 값은 하나도 바꾸지 않는다.
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
LIST = HERE / "고객사목록.csv"
OUT = HERE / "수임처열기시험.txt"

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




# 화면 위쪽의 고객사명과 기수를 읽는다
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

# 수임처 화면의 검색칸을 찾는다
SEARCH_BOX = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('input')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 60 || r.height < 12) continue;
    const t = (el.type || 'text').toLowerCase();
    if (t !== 'text' && t !== 'search' && t !== '') continue;
    out.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               w: Math.round(r.width), 자리: `${Math.round(r.x)},${Math.round(r.y)}`,
               힌트: el.placeholder || '', 값: el.value || '',
               cls: (el.className || '').toString().slice(0, 40) });
  }
  out.sort((a, b) => b.w - a.w);
  return JSON.stringify(out.slice(0, 8));
}"""

# 검색칸에 이름을 넣는다. 리액트가 알아듣게 네이티브 setter 를 쓴다.
TYPE_IN = r"""(args) => {
  const els = [];
  for (const el of document.querySelectorAll('input')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 60 || r.height < 12) continue;
    const t = (el.type || 'text').toLowerCase();
    if (t !== 'text' && t !== 'search' && t !== '') continue;
    els.push({ el: el, w: r.width });
  }
  if (!els.length) return JSON.stringify({ ok: false, reason: '검색칸이 없음' });
  els.sort((a, b) => b.w - a.w);
  const el = els[0].el;
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

# 그 이름이 든 줄의 회계 단추를 찾는다
FIND_ROW = r"""(args) => {
  const 후보 = [];
  for (const el of document.querySelectorAll('button,a,span,div,[role=button]')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    if (t !== args.단추) continue;
    let 안쪽 = true;
    for (const c of el.children) {
      const ct = (c.innerText || c.textContent || '').trim().replace(/\s+/g, ' ');
      if (ct === args.단추) { 안쪽 = false; break; }
    }
    if (!안쪽) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;

    // 위로 올라가며 그 이름이 든 줄인지 본다
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

# 위쪽 메뉴 검색칸에 글자를 넣는다. 힌트에 '메뉴' 가 든 칸을 고른다.
MENU_TYPE = r"""(args) => {
  let 표적 = null;
  for (const el of document.querySelectorAll('input')) {
    if (el.offsetParent === null) continue;
    const 힌트 = el.placeholder || '';
    if (!/메뉴/.test(힌트)) continue;
    표적 = el;
    break;
  }
  if (!표적) return JSON.stringify({ ok: false, reason: '메뉴 검색칸이 없음' });
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(표적, args.글);
  표적.dispatchEvent(new Event('input', { bubbles: true }));
  표적.dispatchEvent(new Event('change', { bubbles: true }));
  표적.focus();
  const r = 표적.getBoundingClientRect();
  return JSON.stringify({ ok: true, 값: 표적.value,
                          x: Math.round(r.x + r.width / 2),
                          y: Math.round(r.y + r.height / 2) });
}"""

# 검색칸 아래에 떠오른 메뉴 줄들을 있는 그대로 적는다.
# 메뉴 이름의 일부만 표시(하이라이트)되므로 조각을 누르면 엉뚱한 데로 간다.
# 예: 전자세금계산서발급세액공제신고서  <- '전자세금계산서' 만 따로 표시된다
# 그래서 줄 통째의 글자를 보고 골라야 한다.
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
                자리: `${Math.round(r.x)},${Math.round(r.y)}`,
                너비: Math.round(r.width), 높이: Math.round(r.height) });
  }
  // 같은 글자가 여러 겹으로 잡힌다. 줄마다 가장 넓은 것 하나만 남긴다.
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

lines = []


def say(t=""):
    print(str(t)[:500])
    lines.append(str(t))


def 살펴보기(page):
    try:
        h = json.loads(page.evaluate(HEADER))
    except Exception as e:
        return {"이름": "", "기수": "", "기간": ""}
    return h


print()
print("=" * 72)
print("  수임처 화면에서 고객사 열기 시험")
print("=" * 72)
print()

if not LIST.exists():
    print(f"  고객사목록이 없습니다: {LIST}")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

목록 = []
with LIST.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if r.get("cd_com"):
            목록.append(r)
print(f"  고객사목록 {len(목록)}곳")
print()
for n, r in enumerate(목록, 1):
    print(f"  {n:>3}) {r['고객사명']}  {r['gisu']}기")
print()
골 = input("  열어 볼 고객사 번호 >>> ").strip()
if not 골.isdigit() or not (1 <= int(골) <= len(목록)):
    print("  그만둡니다.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit
표적 = 목록[int(골) - 1]

print()
print("  " + "-" * 66)
print("   위하고 수임처 화면(담당 수임처 목록이 보이는 화면)을")
print("   띄워두신 뒤에 진행해주세요.")
print("  " + "-" * 66)
input("\n  띄우셨으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        모든탭 = [pg for ctx in browser.contexts for pg in ctx.pages]
        수임처탭 = [pg for pg in 모든탭 if "www.wehago.com" in pg.url]
        if not 수임처탭:
            say("수임처 화면 탭(www.wehago.com)을 찾지 못했습니다.")
            raise SystemExit
        page = 수임처탭[0]
        page.bring_to_front()
        say(f"수임처 탭: {page.url[:110]}")
        say(f"열어 볼 고객사: {표적['고객사명']}  {표적['gisu']}기  {표적['cd_com']}")

        say("")
        say("===== 검색칸 =====")
        for b in json.loads(page.evaluate(SEARCH_BOX)):
            say(f"  ({b['자리']}) 너비 {b['w']}  힌트[{b['힌트']}]  값[{b['값']}]  {b['cls']}")

        r = json.loads(page.evaluate(TYPE_IN, {"글": 표적["고객사명"]}))
        if not r.get("ok"):
            say(f"검색칸에 못 넣었습니다: {r.get('reason')}")
            raise SystemExit
        say("")
        say(f"검색칸에 [{r['값']}] 를 넣었습니다.")
        page.mouse.click(r["x"], r["y"])
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)

        후보 = json.loads(page.evaluate(FIND_ROW,
                                        {"이름": 표적["고객사명"], "단추": "회계"}))
        say("")
        say(f"===== 그 이름이 든 줄의 회계 단추 {len(후보)}개 =====")
        for c in 후보:
            say(f"  ({c['자리']})  줄: {c['줄']}")

        if len(후보) != 1:
            say("")
            say(f"  [멈춤] 회계 단추가 {len(후보)}개입니다. 하나일 때만 누릅니다.")
            say("  이름이 여러 줄에 걸리거나 검색이 안 된 것입니다.")
            raise SystemExit

        print()
        print("  " + "-" * 66)
        print(f"   누를 줄: {후보[0]['줄'][:60]}")
        print("  " + "-" * 66)
        if input("\n  이 줄의 회계를 누를까요? (y) >>> ").strip().lower() != "y":
            say("사용자가 중단했습니다.")
            raise SystemExit

        전탭 = len([pg for ctx in browser.contexts for pg in ctx.pages])
        page.mouse.click(후보[0]["x"], 후보[0]["y"])
        say("")
        say("회계를 눌렀습니다. 화면이 뜰 때까지 지켜봅니다.")

        찾음 = None
        for 지난 in range(0, 40, 3):
            page.wait_for_timeout(3000)
            탭들 = [pg for ctx in browser.contexts for pg in ctx.pages]
            # 처음 열릴 때 주소는 cd_com 이 아니라 cNum, taxAccounts 로 적힌다.
            #   ...?wehagoT&cNum=5583734&taxNum=9009&taxAccounts=4&taxDate=...
            맞는탭 = [pg for pg in 탭들
                      if "smarta.wehago.com" in pg.url
                      and (표적["cd_com"] in pg.url
                           or f"cNum={표적['cno']}" in pg.url)]
            say(f"  {지난 + 3:>3}초  탭 {len(탭들)}개 (처음 {전탭}개)"
                f"  그 고객사 화면 {len(맞는탭)}개")
            if 맞는탭:
                찾음 = 맞는탭[0]
                break

        if not 찾음:
            say("")
            say("  그 고객사의 화면이 안 뜹니다. 지금 열린 위하고 탭:")
            for pg in [pg for ctx in browser.contexts for pg in ctx.pages]:
                if "wehago.com" in pg.url:
                    say("    " + pg.url[:120])
            raise SystemExit

        찾음.bring_to_front()
        찾음.wait_for_timeout(4000)
        h = 살펴보기(찾음)
        say("")
        say("===== 열린 화면 =====")
        say(f"  주소: {찾음.url[:130]}")
        say(f"  고객사명 [{h['이름']}]  {h['기수']}  {h['기간']}")
        맞나 = h["이름"] and (표적["고객사명"] in h["이름"] or h["이름"] in 표적["고객사명"])
        say(f"  목록의 이름과 {'맞습니다' if 맞나 else '다릅니다'} (목록: {표적['고객사명']})")
        if not 맞나:
            say("")
            say("  고객사가 제대로 안 잡혔습니다. 여기서 멈춥니다.")
            raise SystemExit

        say("")
        say("===== 전자세금계산서 화면까지 가보기 =====")
        r = json.loads(찾음.evaluate(MENU_TYPE, {"글": "전자세금계산서"}))
        if not r.get("ok"):
            say(f"  메뉴 검색칸을 못 찾았습니다: {r.get('reason')}")
            say("  지금 화면에 보이는 입력칸:")
            for b in json.loads(찾음.evaluate(SEARCH_BOX)):
                say(f"    ({b['자리']}) 너비 {b['w']}  힌트[{b['힌트']}]  값[{b['값']}]")
            raise SystemExit
        say(f"  메뉴 검색칸에 [{r['값']}] 를 넣었습니다.")
        찾음.wait_for_timeout(2000)

        줄들 = json.loads(찾음.evaluate(MENU_ITEMS, {"ix": r["x"], "iy": r["y"]}))
        say(f"  검색칸({r['x']},{r['y']}) 아래에 떠오른 것 {len(줄들)}개:")
        for c in 줄들:
            say(f"    ({c['자리']}) {c['너비']}x{c['높이']}  [{c['글자']}]")

        딱맞는것 = [c for c in 줄들 if c["글자"] == "전자세금계산서"]
        if not 딱맞는것:
            say("")
            say("  [멈춤] 글자가 딱 '전자세금계산서' 인 줄이 없습니다.")
            say("  위 목록에서 어느 것을 눌러야 하는지 알려주세요.")
            raise SystemExit
        say(f"  글자가 딱 맞는 줄 {len(딱맞는것)}개. 위에서부터 눌러봅니다.")

        도착 = False
        for 번째, c in enumerate(딱맞는것, 1):
            if 도착:
                break
            say(f"  [{번째}] ({c['자리']}) [{c['글자']}] 를 눌러봅니다.")
            찾음.mouse.click(c["x"], c["y"])
            for 지난 in range(0, 15, 3):
                찾음.wait_for_timeout(3000)
                # 주소는 안 바뀌기도 한다. 전표 목록이 잡히는지로 본다.
                try:
                    d = json.loads(찾음.evaluate(GRAB))
                    잡혔나 = bool(d.get("ok"))
                    건수 = len(d.get("rows") or [])
                except Exception:
                    잡혔나, 건수 = False, -1
                say(f"      {지난 + 3:>3}초  전표목록 {'잡힘' if 잡혔나 else '못 잡음'}"
                    f"  {건수}건  주소 {찾음.url.split('/#/')[-1][:44]}")
                if 잡혔나:
                    도착 = True
                    break
            if not 도착 and 번째 < len(딱맞는것):
                r2 = json.loads(찾음.evaluate(MENU_TYPE, {"글": "전자세금계산서"}))
                if r2.get("ok"):
                    찾음.wait_for_timeout(1500)

        say("")
        if 도착:
            h2 = 살펴보기(찾음)
            say(f"  고객사명 [{h2['이름']}]  {h2['기수']}  {h2['기간']}")
            say("===== 됩니다 =====")
            say("  수임처에서 회계를 눌러 고객사를 열고,")
            say("  메뉴로 전자세금계산서까지 갈 수 있습니다.")
            say("  화면도 봐주세요. 전자세금계산서 화면이 맞는지.")
        else:
            say("===== 전자세금계산서까지는 아직 =====")
            say(f"  지금 주소: {찾음.url[:130]}")
            say("  화면을 보시고 어디에 멈춰 있는지 알려주세요.")

        say("")
        say("  [알림] 고객사를 열 때마다 탭이 하나씩 늘어납니다.")
        say("  순회할 때는 한 고객사를 마치면 그 탭을 닫아야 합니다.")

        browser.close()

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
print("  전표 값은 하나도 바꾸지 않았습니다.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
