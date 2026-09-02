"""수임처 목록이 프로그램 속 어디에 담겨 있는지 찾는다. 읽기만 한다.

화면 글자로는 이름과 사업자번호만 보이고 cd_com 이 없다.
그런데 화면에 그리려면 프로그램 속 어딘가에는 그 자료가 있어야 한다.
window 아래를 훑어 cd_com 같은 것이 든 것을 찾는다.

고객사마다 cd_com, gisu, cno 가 다르므로 이 셋이 다 들어 있어야 쓸 만하다.

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
OUT = HERE / "수임처찾기.txt"

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




# window 아래를 훑어 고객사 자료처럼 보이는 것을 찾는다
FIND_LIST = r"""() => {
  const 찾는열쇠 = ['cd_com', 'cdCom', 'cdcom', 'CD_COM'];
  const 곁들이 = ['gisu', 'cno', 'nm_com', 'nmCom', 'no_bisocial', 'sangho', 'name'];
  const 결과 = [];
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0, 길: 'window' }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto|__g|__pop)$/;
  let visited = 0;

  const 열쇠있나 = o => {
    if (!o || typeof o !== 'object') return false;
    for (const k of 찾는열쇠) if (k in o) return true;
    return false;
  };

  while (queue.length && visited < 80000 && 결과.length < 12) {
    const { o, d, 길 } = queue.shift();
    if (d > 8) continue;
    let keys = [];
    try { keys = Object.keys(o); } catch (e) { continue; }
    for (const k of keys) {
      if (d === 0 && SKIP.test(k)) continue;
      let v;
      try { v = o[k]; } catch (e) { continue; }
      if (!v || typeof v !== 'object') continue;
      try { if (v.nodeType || v === window) continue; } catch (e) { continue; }
      try { if (seen.has(v)) continue; seen.add(v); } catch (e) { continue; }
      visited++;
      const 이길 = 길 + '.' + k;

      // 배열인데 안에 든 것이 고객사처럼 생겼는가
      if (Array.isArray(v) && v.length >= 2 && 열쇠있나(v[0])) {
        const 샘 = v.slice(0, 3).map(x => {
          const 뽑기 = {};
          for (const kk of 찾는열쇠.concat(곁들이)) if (x && kk in x) 뽑기[kk] = x[kk];
          return 뽑기;
        });
        결과.push({ 길: 이길, 종류: '배열', 건수: v.length,
                    열쇠: Object.keys(v[0]).slice(0, 24),
                    맛보기: JSON.stringify(샘).slice(0, 500) });
        continue;
      }
      // 낱개 하나가 고객사처럼 생겼는가 (지금 고른 고객사일 수 있다)
      if (!Array.isArray(v) && 열쇠있나(v)) {
        const 뽑기 = {};
        for (const kk of 찾는열쇠.concat(곁들이)) if (kk in v) 뽑기[kk] = v[kk];
        결과.push({ 길: 이길, 종류: '낱개', 건수: 1,
                    열쇠: Object.keys(v).slice(0, 24),
                    맛보기: JSON.stringify(뽑기).slice(0, 300) });
        continue;
      }
      if (d < 8) queue.push({ o: v, d: d + 1, 길: 이길 });
    }
  }
  return JSON.stringify({ 본것: visited, 결과: 결과 });
}"""

# 브라우저가 갖고 있는 저장소도 본다. 고객사 목록이 여기 있을 수 있다.
STORAGE = r"""() => {
  const out = [];
  for (const [이름, 통] of [['localStorage', localStorage], ['sessionStorage', sessionStorage]]) {
    let keys = [];
    try { keys = Object.keys(통); } catch (e) { continue; }
    for (const k of keys) {
      let v = '';
      try { v = 통.getItem(k) || ''; } catch (e) { continue; }
      if (!/cd_com|cdCom|gisu|cno/.test(v)) continue;
      out.push(`${이름}.${k}  (${v.length}글자)  ${v.slice(0, 260)}`);
    }
  }
  return JSON.stringify(out.slice(0, 12));
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


print()
print("=" * 72)
print("  수임처 목록이 어디 있는지 찾기 (아무것도 바꾸지 않습니다)")
print("=" * 72)
print()
print("  수임처 목록이 보이는 화면을 띄워두시면 더 잘 찾습니다.")
input("\n  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "wehago.com" in pg.url]
        if not pages:
            say("위하고 탭을 찾지 못했습니다.")
            raise SystemExit

        for pg in pages:
            say("")
            say("=" * 64)
            say("탭: " + pg.url[:140])
            조각 = {}
            for k in ("cd_com", "gisu", "cno", "yminsa"):
                m = re.search(k + r"=([^&#]*)", pg.url)
                if m:
                    조각[k] = m.group(1)
            if 조각:
                say("  주소에 담긴 것: " + ", ".join(f"{k}={v}" for k, v in 조각.items()))

            try:
                r = json.loads(pg.evaluate(FIND_LIST))
            except Exception as e:
                say(f"  훑기 실패 {str(e)[:90]}")
                continue
            say(f"  {r['본것']}개를 훑어 {len(r['결과'])}군데를 찾았습니다.")
            for x in r["결과"]:
                say("")
                say(f"  [{x['종류']} {x['건수']}건] {x['길']}")
                say(f"    열쇠: {', '.join(x['열쇠'])}")
                say(f"    맛보기: {x['맛보기']}")

            try:
                s = json.loads(pg.evaluate(STORAGE))
            except Exception:
                s = []
            if s:
                say("")
                say("  [브라우저 저장소]")
                for t in s:
                    say("    " + t)

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
