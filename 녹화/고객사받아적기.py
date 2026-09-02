"""고객사를 오갈 때마다 주소를 받아 적어 목록을 만든다.

담당자별로 맡은 업체가 50~80곳이다. 그 목록만 있으면 순회가 된다.
프로그램 속에서는 목록을 못 찾았다. 그래서 평소 일하듯 고객사를 오가면
그때마다 주소를 받아 적어 목록을 쌓는다.

이 창을 켜둔 채로 위하고에서 담당 업체를 하나씩 열면 된다.
한 바퀴 돌고 나면 목록이 다 만들어진다. 그 뒤로는 그 목록을 쓴다.

값은 하나도 바꾸지 않는다. 주소와 화면 위쪽 고객사명만 읽는다.
"""
import collections
import datetime
import time
import csv
import json
import re
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "고객사목록.csv"

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
    if (!own || own.length > 30) continue;
    나온것.push({ x: Math.round(r.x), 글자: own });
  }
  나온것.sort((a, b) => a.x - b.x);
  let 이름 = '', 기수 = '';
  for (const t of 나온것) {
    if (!기수 && /^\d+기$/.test(t.글자)) { 기수 = t.글자; continue; }
    if (!이름 && t.x < 400 && !/^\d/.test(t.글자) && t.글자.length >= 2) 이름 = t.글자;
  }
  return JSON.stringify({ 이름: 이름, 기수: 기수 });
}"""

머리 = ["고객사명", "cd_com", "gisu", "cno", "yminsa", "할것", "처음본때"]


def 주소풀기(url):
    조각 = {}
    for k in ("cd_com", "gisu", "cno", "yminsa"):
        m = re.search(k + r"=([^&#]*)", url)
        조각[k] = m.group(1) if m else ""
    return 조각


def 읽어오기():
    """이미 적어둔 것을 읽는다. 두 번 적지 않으려는 것이다."""
    있는것 = {}
    차례 = []
    if OUT.exists():
        with OUT.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                열쇠 = (r.get("cd_com", ""), r.get("gisu", ""))
                if 열쇠[0]:
                    있는것[열쇠] = r
                    차례.append(열쇠)
    return 있는것, 차례


def 저장(있는것, 차례):
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=머리)
        w.writeheader()
        for 열쇠 in 차례:
            w.writerow({k: 있는것[열쇠].get(k, "") for k in 머리})


print()
print("=" * 72)
print("  고객사 받아 적기")
print("=" * 72)
print()
print("  이 창을 켜둔 채로 위하고에서 담당 업체를 하나씩 열어주세요.")
print("  전자세금계산서 화면까지 들어가시면 그때 받아 적습니다.")
print("  평소 일하시던 대로 하시면 됩니다.")
print()
print("  그만두려면 이 창에서 Ctrl+C 를 누르세요.")
print("  적은 것은 그때까지 다 저장되어 있습니다.")
print()

있는것, 차례 = 읽어오기()
if 차례:
    print(f"  이미 적어둔 고객사 {len(차례)}곳이 있습니다. 이어서 적습니다.")
    print()
input("  준비되었으면 Enter >>> ")
print()

본것 = None
try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        while True:
            try:
                pages = [pg for ctx in browser.contexts for pg in ctx.pages
                         if "smarta.wehago.com" in pg.url and "cd_com=" in pg.url]
            except Exception:
                print("  크롬과 끊어졌습니다. 창을 다시 열고 실행해주세요.")
                break

            for pg in pages:
                조각 = 주소풀기(pg.url)
                열쇠 = (조각["cd_com"],조각["gisu"])
                if not 열쇠[0] or 열쇠 in 있는것:
                    continue
                이름, 기수 = "", ""
                try:
                    h = json.loads(pg.evaluate(HEADER))
                    이름, 기수 = h.get("이름", ""), h.get("기수", "")
                except Exception:
                    pass
                있는것[열쇠] = {
                    "고객사명": 이름 or "(이름을 못 읽음)",
                    "cd_com": 조각["cd_com"], "gisu": 조각["gisu"],
                    "cno": 조각["cno"], "yminsa": 조각["yminsa"],
                    "할것": "Y",
                    "처음본때": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                차례.append(열쇠)
                저장(있는것, 차례)
                print(f"  {len(차례):>3}곳  {이름 or '(이름 못 읽음)'}"
                      f"  {기수 or 조각['gisu'] + '기'}  {조각['cd_com']}")

            time.sleep(2)

except KeyboardInterrupt:
    print()
    print("  그만둡니다.")
except Exception:
    print()
    print("실패했습니다. 원인:")
    traceback.print_exc()

저장(있는것, 차례)
print()
print("=" * 72)
print(f"  고객사 {len(차례)}곳을 적었습니다: {OUT}")
print("  할것 칸을 N 으로 바꾸면 그 고객사는 건너뜁니다.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
