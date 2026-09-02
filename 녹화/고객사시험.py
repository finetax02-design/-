"""고객사를 주소로 바꿀 수 있는지, 목록을 읽을 수 있는지 살핀다.

값은 하나도 바꾸지 않는다. 읽기만 한다.

두 가지를 본다.
  1 지금 주소에서 고객사와 기수가 어떻게 적혀 있는가
  2 로그인 첫 화면(고객사 고르는 화면)에서 목록을 읽을 수 있는가

이 결과에 따라 고객사 순회를 어떻게 만들지 정한다.
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
OUT = HERE / "고객사시험.txt"

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



# 화면 위쪽에 뜬 고객사명을 읽는다. 주소와 화면이 맞는지 대조하려는 것이다.
HEADER = r"""() => {
  const 보임 = el => {
    if (el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2 && r.y < 200;
  };
  const out = [];
  for (const el of document.querySelectorAll('span,div,button,a,strong')) {
    if (!보임(el)) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
    own = own.trim().replace(/\s+/g, ' ');
    if (!own || own.length > 30) continue;
    const r = el.getBoundingClientRect();
    if (r.y > 120) continue;
    out.push(`(${Math.round(r.x)},${Math.round(r.y)}) ${own}`);
  }
  return JSON.stringify(out.slice(0, 40));
}"""

# 고객사 고르는 화면에서 목록처럼 보이는 것을 찾는다.
COMPANY_LIST = r"""() => {
  const 보임 = el => {
    if (el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  };
  const 결과 = { 그리드: [], 표: [], 줄: [], 링크: [] };

  // 그리드에 담겨 있을 수 있다. 열 이름을 보면 안다.
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  let visited = 0;
  while (queue.length && visited < 40000) {
    const { o, d } = queue.shift();
    if (d > 8) continue;
    let keys = [];
    try { keys = Object.keys(o); } catch (e) { continue; }
    for (const k of keys) {
      let v;
      try { v = o[k]; } catch (e) { continue; }
      if (!v || (typeof v !== 'object' && typeof v !== 'function')) continue;
      try { if (v.nodeType || v === window) continue; } catch (e) { continue; }
      try { if (seen.has(v)) continue; seen.add(v); } catch (e) { continue; }
      visited++;
      if (gridish(v)) {
        let names = [];
        try { names = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        let n = 0, 맛보기 = [];
        try {
          let src = v;
          try { const dp = v.getDataSource(); if (dp) src = dp; } catch (e) {}
          n = src.getRowCount() || 0;
          if (n) 맛보기 = src.getJsonRows(0, Math.min(2, n - 1)) || [];
        } catch (e) {}
        결과.그리드.push({ 열: names.slice(0, 20), 건수: n,
                          맛보기: JSON.stringify(맛보기).slice(0, 400) });
      }
      if (d < 8) queue.push({ o: v, d: d + 1 });
    }
  }

  // 그냥 표나 목록일 수도 있다.
  for (const tb of document.querySelectorAll('table')) {
    if (!보임(tb)) continue;
    const rows = [];
    for (const tr of tb.rows) rows.push([...tr.cells].map(c => (c.innerText || '').trim()));
    if (rows.length > 1) 결과.표.push(rows.slice(0, 6));
  }
  for (const ul of document.querySelectorAll('ul,ol')) {
    if (!보임(ul)) continue;
    const items = [...ul.children]
      .map(li => (li.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40))
      .filter(Boolean);
    if (items.length >= 3) 결과.줄.push(items.slice(0, 8));
  }
  // 주소에 고객사가 들어 있는 링크
  for (const a of document.querySelectorAll('a[href]')) {
    const h = a.getAttribute('href') || '';
    if (!/cd_com=/.test(h)) continue;
    결과.링크.push(((a.innerText || '').trim().slice(0, 24)) + '  ' + h.slice(0, 120));
  }
  결과.표 = 결과.표.slice(0, 3);
  결과.줄 = 결과.줄.slice(0, 6);
  결과.링크 = 결과.링크.slice(0, 20);
  return JSON.stringify(결과);
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


def 주소풀기(url):
    조각 = {}
    for k in ("cd_com", "gisu", "searchData", "cno", "yminsa"):
        m = re.search(k + r"=([^&#]*)", url)
        if m:
            조각[k] = m.group(1)
    return 조각


print()
print("=" * 72)
print("  고객사 순회가 될지 살펴보기 (아무것도 바꾸지 않습니다)")
print("=" * 72)
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "wehago.com" in pg.url]
        if not pages:
            say("위하고 탭을 찾지 못했습니다.")
            raise SystemExit

        say(f"위하고 탭 {len(pages)}개")
        for pg in pages:
            say("")
            say("  주소: " + pg.url[:150])
            조각 = 주소풀기(pg.url)
            if 조각:
                say("  주소에 담긴 것: " + ", ".join(f"{k}={v}" for k, v in 조각.items()))
            else:
                say("  주소에 고객사가 안 들어 있습니다.")

        표 = next((pg for pg in pages if "SAAC0103" in pg.url), pages[0])
        표.bring_to_front()
        say("")
        say("===== 지금 화면 위쪽에 뜬 글자 =====")
        for t in json.loads(표.evaluate(HEADER)):
            say("  " + t)
        say("")
        say("  이 가운데 고객사명이 있으면 주소와 대조할 수 있습니다.")

        d = json.loads(표.evaluate(GRAB))
        if d.get("ok"):
            say(f"  지금 화면의 전표 {len(d['rows'])}건")

        print()
        print("  " + "-" * 66)
        print("   이제 고객사를 고르는 첫 화면으로 가주세요.")
        print("   (로그인 뒤 고객사를 검색해 고르는 그 화면입니다)")
        print("   목록이 보이는 상태로 두시면 됩니다.")
        print("  " + "-" * 66)
        input("\n  그 화면을 띄우셨으면 Enter >>> ")

        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "wehago.com" in pg.url]
        say("")
        say("===== 고객사 고르는 화면 =====")
        for pg in pages:
            say("")
            say("  주소: " + pg.url[:150])
            try:
                r = json.loads(pg.evaluate(COMPANY_LIST))
            except Exception as e:
                say(f"  읽기 실패 {str(e)[:80]}")
                continue
            for g in r["그리드"][:4]:
                say(f"  [그리드] {g['건수']}건  열: {', '.join(g['열'])}")
                say(f"           맛보기 {g['맛보기']}")
            for t in r["표"]:
                say("  [표]")
                for row in t:
                    say("    " + " | ".join(row))
            for l in r["줄"]:
                say("  [목록] " + " / ".join(l))
            for a in r["링크"]:
                say("  [링크] " + a)
            if not any(r.values()):
                say("  목록처럼 보이는 것을 못 찾았습니다.")

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
