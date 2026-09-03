"""주소로 고객사를 옮길 수 있는지 시험한다. 값은 하나도 바꾸지 않는다.

위하고는 주소가 # 뒤로 붙는 방식이라 주소만 갈아도 화면이 안 바뀔 수 있다.
고객사목록에서 한 곳을 골라 그리로 옮겨보고,
화면 위쪽 고객사명과 전표 건수를 읽어 정말 옮겨졌는지 확인한다.

옮기는 방법을 두 가지로 해본다.
  1 주소를 바로 갈아끼운다
  2 갈아끼운 뒤 새로고침한다

크롬에 붙는 시간을 짧게 한다. 오래 붙어 있으면 크롬이 멎는다.
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
OUT = HERE / "고객사이동시험.txt"

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
  return JSON.stringify({ 이름: 이름, 기수: 기수, 기간: 기간, 제목: document.title });
}"""

lines = []


def say(t=""):
    print(str(t)[:500])
    lines.append(str(t))


def 살펴보기(page):
    try:
        h = json.loads(page.evaluate(HEADER))
    except Exception as e:
        return {"이름": "", "기수": "", "기간": "", "제목": f"읽기 실패 {str(e)[:60]}"}, -1
    건수 = -1
    try:
        d = json.loads(page.evaluate(GRAB))
        if d.get("ok"):
            건수 = len(d["rows"])
        elif "자료가 없음" in (d.get("reason") or ""):
            건수 = 0
    except Exception:
        pass
    return h, 건수


print()
print("=" * 72)
print("  주소로 고객사를 옮길 수 있는지 시험 (아무것도 바꾸지 않습니다)")
print("=" * 72)
print()

if not LIST.exists():
    print(f"  고객사목록이 없습니다: {LIST}")
    print("  38_고객사받아적기.bat 을 먼저 돌려주세요.")
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
골 = input("  옮겨가 볼 고객사 번호 >>> ").strip()
if not 골.isdigit() or not (1 <= int(골) <= len(목록)):
    print("  그만둡니다.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit
표적 = 목록[int(골) - 1]

주소 = ("https://smarta.wehago.com/#/smarta/account/SAAC0103?sao"
        f"&cno={표적['cno']}&cd_com={표적['cd_com']}&gisu={표적['gisu']}"
        f"&yminsa={표적['yminsa']}")
print()
print(f"  옮겨갈 곳: {표적['고객사명']}  {표적['gisu']}기")
print(f"  주소: {주소}")
print()
print("  기간(searchData)은 일부러 붙이지 않았습니다. 화면 기본값으로 열립니다.")
if input("  옮겨가 볼까요? (y) >>> ").strip().lower() != "y":
    print("  그만둡니다.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

def 기다리며보기(page, 바라는이름, 초=25):
    """화면이 그 고객사로 바뀔 때까지 지켜본다. 바뀌는 데 시간이 걸린다."""
    끝 = 초
    본것 = []
    while True:
        h, 건수 = 살펴보기(page)
        본것.append((초 - 끝, h["이름"], h["기수"], 건수))
        맞나 = h["이름"] and (바라는이름 in h["이름"] or h["이름"] in 바라는이름)
        if 맞나 or 끝 <= 0:
            return h, 건수, 맞나, 본것
        page.wait_for_timeout(2500)
        끝 -= 2.5


try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        # 이미 고객사 화면이 떠 있는 탭이라야 한다.
        # 아무 탭이나 끌고 가면 고객사가 안 잡히고 세무법인 이름만 나온다.
        살아있는탭 = [pg for pg in pages
                     if "smarta.wehago.com" in pg.url and "cd_com=" in pg.url]
        if not 살아있는탭:
            say("고객사 화면이 떠 있는 탭이 없습니다.")
            say("")
            say("  아무 탭이나 주소로 끌고 가면 고객사가 안 잡힙니다.")
            say("  위하고에서 아무 고객사나 하나 열어 전자세금계산서 화면까지")
            say("  들어가신 뒤에 다시 실행해주세요.")
            raise SystemExit
        page = 살아있는탭[0]
        page.bring_to_front()

        h, 건수 = 살펴보기(page)
        say("===== 옮기기 전 =====")
        say(f"  주소: {page.url[:130]}")
        say(f"  고객사명 [{h['이름']}]  {h['기수']}  {h['기간']}")
        say(f"  전표 {건수}건" if 건수 >= 0 else "  전표를 못 읽음")
        if 표적["고객사명"] in (h["이름"] or ""):
            say("")
            say("  [멈춤] 지금 열려 있는 고객사와 옮겨갈 고객사가 같습니다.")
            say("  다른 고객사를 골라 다시 해주세요. 그래야 바뀌는지 알 수 있습니다.")
            raise SystemExit

        say("")
        say("===== 1) 주소만 갈아끼우기 (같은 탭 안에서) =====")
        page.evaluate("(u) => { window.location.href = u; }", 주소)
        h1, 건수1, 맞나1, 본것1 = 기다리며보기(page, 표적["고객사명"])
        for 지난, 이름, 기수, 건 in 본것1:
            say(f"  {지난:>4.0f}초  이름[{이름}]  {기수}  전표 {건}건")
        say(f"  주소: {page.url[:130]}")
        say(f"  목록의 이름과 {'맞습니다' if 맞나1 else '다릅니다'}"
            f" (목록: {표적['고객사명']})")

        맞나2 = False
        if not 맞나1:
            say("")
            say("===== 2) 새로고침까지 해보기 =====")
            page.reload(wait_until="domcontentloaded", timeout=40000)
            h2, 건수2, 맞나2, 본것2 = 기다리며보기(page, 표적["고객사명"], 초=30)
            for 지난, 이름, 기수, 건 in 본것2:
                say(f"  {지난:>4.0f}초  이름[{이름}]  {기수}  전표 {건}건")
            say(f"  주소: {page.url[:130]}")
            say(f"  목록의 이름과 {'맞습니다' if 맞나2 else '다릅니다'}")

        say("")
        if 맞나1 or 맞나2:
            say("===== 됩니다 =====")
            say("  주소로 고객사를 옮길 수 있습니다."
                + ("  (주소만 갈아끼우면 됩니다)" if 맞나1 else "  (새로고침까지 해야 합니다)"))
        else:
            say("===== 안 됩니다 =====")
            say("  주소로는 고객사가 안 바뀝니다.")
            say("  수임처 화면에서 고르는 절차를 거쳐야 하는 것으로 보입니다.")

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
print("  화면도 봐주세요. 정말 그 고객사로 바뀌었는지, 조회를 눌러야 하는지.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
