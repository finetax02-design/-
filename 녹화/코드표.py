"""전표상태 유형 불공제코드가 실제로 무슨 뜻인지 알아낸다.

읽어온 값은 ty_jungstat=1,2,5 처럼 숫자다. 어느 것이 미추천이고 어느 것이
전표확정인지 모르면 엉뚱한 건을 건드리게 된다.

RealGrid 는 화면에 그려지는 글자를 getDisplayValues 로 돌려준다.
같은 행의 원래 값과 화면 글자를 짝지으면 코드표가 나온다.
추측하지 않고 화면이 말하는 대로 적는다.

읽기만 한다. 값을 바꾸지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "코드표.txt"

# 뜻을 알아내야 하는 컬럼
WANTED = ["ty_jungstat", "ty_mth", "ty_mth2", "cd_notdedct", "ty_trade", "gj_gubun", "yn_bungae"]

SCRIPT = r"""() => {
  const WANTED = %WANTED%;
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };

  const seen = new WeakSet();
  const found = [];
  const queue = [{ o: window, path: 'window', d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
  while (queue.length && visited < 40000) {
    const { o, path, d } = queue.shift();
    if (d > 7) continue;
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
      if (gridish(v)) found.push({ path: path + '.' + k, obj: v });
      if (d < 7) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }

  const out = { grids: [], visited: visited };
  for (const f of found) {
    const g = f.obj;
    let cols = [];
    try { cols = g.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) { continue; }
    if (cols.length < 5) continue;

    let src = g, count = 0, rows = [];
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try {
      count = typeof src.getRowCount === 'function' ? src.getRowCount() : 0;
      if (count > 0 && typeof src.getJsonRows === 'function') rows = src.getJsonRows(0, count - 1) || [];
    } catch (e) {}

    const info = { path: f.path, colCount: cols.length, rowCount: count, maps: {}, sampleDisplay: null };

    // 컬럼 이름 -> 화면에 보이는 위치를 찾기 위해 헤더도 같이 모은다
    let headers = [];
    try {
      headers = g.getColumns().map(c => {
        try { const h = c.header; return h == null ? '' : (typeof h === 'object' ? String(h.text || '') : String(h)); }
        catch (e) { return ''; }
      });
    } catch (e) {}

    // 각 행의 화면 글자를 가져온다
    const display = i => {
      for (const m of ['getDisplayValues', 'getDisplayValuesOfRow']) {
        try { const v = g[m](i); if (v && v.length) return v; } catch (e) {}
      }
      return null;
    };

    // 관심 컬럼마다, 값이 다른 행을 하나씩 찾아 화면 글자와 짝짓는다
    for (const field of WANTED) {
      const idx = cols.indexOf(field);
      if (idx < 0) continue;
      const map = {};
      for (let i = 0; i < rows.length && i < 400; i++) {
        const raw = rows[i][field];
        const key = (raw === null || raw === undefined || raw === '') ? '(빈값)' : String(raw);
        if (map[key]) { map[key].count++; continue; }
        const d = display(i);
        map[key] = { label: d ? String(d[idx] === undefined ? '' : d[idx]) : '(화면글자 못읽음)', count: 1 };
      }
      if (Object.keys(map).length) info.maps[field] = { header: headers[idx] || '', values: map };
    }

    if (rows.length) {
      const d = display(0);
      if (d) {
        info.sampleDisplay = {};
        cols.forEach((c, i) => { if (WANTED.includes(c)) info.sampleDisplay[c] = String(d[i]); });
      }
    }
    out.grids.push(info);
  }
  return JSON.stringify(out);
}""".replace("%WANTED%", json.dumps(WANTED))

lines: list[str] = []


def say(t: str = "") -> None:
    print(t[:300])
    lines.append(t)


print()
print("=" * 62)
print("  코드 뜻 알아내기")
print("=" * 62)
print()
print("  전자세금계산서 화면에 자료가 보이는 상태여야 합니다.")
print()
print("  [부탁] 가능하면 전표상태를 '전체' 로 조회해서")
print("         미추천 / 확정가능 / 전표확정 이 섞여 있게 해주세요.")
print("         한 종류만 있으면 그 코드만 알 수 있습니다.")
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
            data = json.loads(target.evaluate(SCRIPT))
            say(f"객체 {data['visited']}개 검사, 그리드 {len(data['grids'])}개\n")
            for g in data["grids"]:
                say("=" * 58)
                say(f"그리드: 컬럼 {g['colCount']}개 / 행 {g['rowCount']}개")
                say(f"  경로: {g['path'][:80]}")
                if not g["maps"]:
                    say("  관심 컬럼 없음")
                    continue
                for field, m in g["maps"].items():
                    say(f"\n  [{field}]  화면 컬럼명: {m['header']}")
                    for code, v in sorted(m["values"].items()):
                        say(f"      {code:<10} → \"{v['label']}\"   ({v['count']}건)")
                if g["sampleDisplay"]:
                    say(f"\n  첫 행 화면값: {json.dumps(g['sampleDisplay'], ensure_ascii=False)}")
                say("")
        browser.close()
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  이 파일은 코드와 화면 글자만 담고 있어 보내주셔도 됩니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
