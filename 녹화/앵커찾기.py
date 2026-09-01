"""항상 같은 그리드를 잡을 수 있는 안정된 경로(앵커)를 찾는다.

지금까지 그리드에 닿은 경로는 window.Grids.CellIndex.$_temp._grid 였는데,
이름 그대로 '마지막에 건드린 그리드' 를 담는 임시 자리다.
실행할 때마다 전표 목록이 잡히기도 하고 분개 그리드가 잡히기도 한다.
이대로는 자동화를 만들 수 없다. 엉뚱한 그리드에 값을 쓰게 된다.

window.tags 가 그리드 등록부로 보이므로 그 구조를 훑고,
전체 탐색 깊이도 9까지 늘려 두 그리드에 닿는 모든 경로를 모은다.
그중 $_temp 를 거치지 않는 경로가 있으면 그게 우리가 쓸 앵커다.

같이 코드표도 만든다. getDisplayValuesOfRow 는 배열이 아니라
필드 이름으로 찾는 객체를 돌려준다는 것을 이번에 확인했다.

읽기만 한다. 값을 바꾸지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "앵커.txt"

TOP_MARK = "nm_acctit_cha"    # 전표 목록에만 있는 컬럼
DOWN_MARK = "no_acctper1"     # 분개 그리드에만 있는 컬럼
WANTED = ["ty_jungstat", "ty_mth", "ty_mth2", "cd_notdedct", "ty_trade", "gj_gubun", "yn_bungae"]

SCRIPT = r"""() => {
  const TOP = '%TOP%', DOWN = '%DOWN%';
  const WANTED = %WANTED%;
  const L = [];
  const log = s => L.push(String(s));

  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const colNames = g => {
    try { return g.getColumns().map(c => String(c.name || c.fieldName || '')); }
    catch (e) { return []; }
  };

  // 1) window.tags 구조 살펴보기
  log('===== window.tags 구조 =====');
  try {
    const t = window.tags;
    if (!t) log('  없음');
    else {
      log(`  타입 ${typeof t}, 길이 ${t.length !== undefined ? t.length : '(없음)'}`);
      const ks = Object.keys(t).slice(0, 30);
      log(`  키: ${ks.join(', ')}`);
      for (const k of ks) {
        try {
          const e = t[k];
          if (!e || typeof e !== 'object') continue;
          const sub = Object.keys(e).slice(0, 12);
          log(`    tags.${k}: ${sub.join(', ')}`);
          const owner = e._owner;
          if (owner) {
            const oc = colNames(owner);
            log(`      _owner: 그리드여부=${gridish(owner)} 컬럼${oc.length}개`
                + (oc.includes(TOP) ? ' ← 전표 목록!' : oc.includes(DOWN) ? ' ← 분개!' : ''));
          }
        } catch (e) {}
      }
    }
  } catch (e) { log(`  오류: ${String(e).slice(0, 150)}`); }

  // 2) 깊이 9까지 훑어 두 그리드에 닿는 모든 경로 모으기
  log('');
  log('===== 그리드에 닿는 경로 (깊이 9) =====');
  const seen = new WeakSet();
  const paths = { top: [], down: [] };
  const objs = { top: null, down: null };
  const queue = [{ o: window, path: 'window', d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;

  while (queue.length && visited < 60000) {
    const { o, path, d } = queue.shift();
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
      const p = path + '.' + k;
      if (gridish(v)) {
        const cn = colNames(v);
        if (cn.includes(TOP)) { paths.top.push(p); objs.top = objs.top || v; }
        else if (cn.includes(DOWN)) { paths.down.push(p); objs.down = objs.down || v; }
      }
      if (d < 9) queue.push({ o: v, path: p, d: d + 1 });
    }
  }
  log(`  객체 ${visited}개 검사`);
  for (const kind of ['top', 'down']) {
    const label = kind === 'top' ? '전표 목록' : '분개';
    log(`\n  [${label}] 경로 ${paths[kind].length}개`);
    if (!paths[kind].length) { log('    없음 — 지금 화면에서는 닿지 않습니다.'); continue; }
    const stable = paths[kind].filter(p => !p.includes('$_temp'));
    paths[kind].slice(0, 12).forEach(p => log(`    ${p.includes('$_temp') ? '(임시)' : '(안정)'} ${p}`));
    log(`    → $_temp 를 안 거치는 경로: ${stable.length}개`);
  }

  // 3) 전표 목록에서 코드표 만들기
  log('');
  log('===== 코드표 (전표 목록) =====');
  const g = objs.top;
  if (!g) log('  전표 목록 그리드를 못 잡아 건너뜁니다.');
  else {
    let src = g, count = 0, rows = [];
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try {
      count = typeof src.getRowCount === 'function' ? src.getRowCount() : 0;
      if (count > 0) rows = src.getJsonRows(0, count - 1) || [];
    } catch (e) { log(`  행 읽기 오류: ${String(e).slice(0, 150)}`); }
    log(`  행 ${rows.length}개`);

    // getDisplayValuesOfRow 는 필드 이름으로 찾는 객체를 돌려준다
    const disp = i => {
      for (const m of ['getDisplayValuesOfRow', 'getDisplayValues']) {
        try { const v = g[m](i); if (v && typeof v === 'object') return v; } catch (e) {}
      }
      return null;
    };
    for (const field of WANTED) {
      const map = {};
      for (let i = 0; i < rows.length; i++) {
        const raw = rows[i][field];
        const key = (raw === null || raw === undefined || raw === '') ? '(빈값)' : String(raw);
        if (map[key]) { map[key].n++; continue; }
        const d = disp(i);
        let label = '(못읽음)';
        if (d) { const x = d[field]; label = (x === null || x === undefined) ? '(빈값)' : String(x); }
        map[key] = { label: label, n: 1 };
      }
      if (!Object.keys(map).length) continue;
      log(`\n  [${field}]`);
      for (const k of Object.keys(map).sort()) log(`      ${k.padEnd(10)} → "${map[k].label}"   (${map[k].n}건)`);
    }
  }

  return L.join('\n');
}""".replace("%TOP%", TOP_MARK).replace("%DOWN%", DOWN_MARK).replace("%WANTED%", json.dumps(WANTED))

lines: list[str] = []


def say(t: str = "") -> None:
    print(t[:300])
    lines.append(t)


print()
print("=" * 62)
print("  안정된 그리드 경로 찾기 + 코드표")
print("=" * 62)
print()
print("  [중요] 전자세금계산서 화면에서 조회해 자료가 보이게 하시고,")
print("         전표 목록(위쪽)에서 아무 줄이나 한 번 클릭해주세요.")
print("         그래야 위아래 그리드가 모두 살아 있습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
        else:
            say(target.evaluate(SCRIPT))
        browser.close()
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  경로와 코드표만 담겨 있어 보내주셔도 안전합니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
