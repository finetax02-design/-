"""RealGrid 객체를 공식 API 로 꺼내 다룰 수 있는지 확인한다 (v3).

v2 로 알아낸 것
  window.RealGrid 는 함수이고 getGridInstance / getActiveGrid / exportGrid 를 갖고 있다.
  GRID_TOP / GRID_DOWN 요소에는 React 내부 참조가 붙어 있다.

v2 는 window 속성만 훑느라 정작 getGridInstance 를 불러보지 않았다.
v3 은 그 API 를 직접 호출하고, 안 되면 React 내부를 타고 들어가 찾는다.

거래처명과 금액은 마스킹한다.
"""
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "그리드탐색.txt"
CDP = "http://localhost:9222"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text[:400])
    lines.append(text)


PROBE = r"""() => {
  const L = [];
  const log = s => L.push(String(s));
  const mask = v => {
    if (v === null || v === undefined) return '(빈값)';
    try { return String(v).replace(/\d/g, '#').slice(0, 14); } catch (e) { return '(변환실패)'; }
  };
  const safe = (label, fn) => {
    try { return fn(); } catch (e) { log(`    [${label}] 오류: ${String(e).slice(0, 160)}`); return null; }
  };
  const methodsOf = o => {
    const out = [];
    let cur = o;
    for (let d = 0; d < 4 && cur; d++) {
      for (const k of Object.getOwnPropertyNames(cur)) {
        try { if (typeof o[k] === 'function' && !out.includes(k)) out.push(k); } catch (e) {}
      }
      cur = Object.getPrototypeOf(cur);
    }
    return out;
  };
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    let n = 0;
    for (const m of ['getDataSource','getColumns','getItemCount','getRowCount','setValue','getValues','getJsonRows']) {
      try { if (typeof o[m] === 'function') n++; } catch (e) {}
    }
    return n >= 2;
  };

  const found = [];

  log('===== 1. RealGrid 공식 API 로 꺼내기 =====');
  safe('getGridInstance', () => {
    if (typeof RealGrid.getGridInstance !== 'function') { log('  getGridInstance 없음'); return; }
    for (const id of ['GRID_TOP','GRID_DOWN','GRID_TOP_line','gridTop','gridDown']) {
      safe('inst:' + id, () => {
        const g = RealGrid.getGridInstance(id);
        log(`  getGridInstance("${id}") → ${g ? (gridish(g) ? '그리드 객체!' : typeof g) : '없음'}`);
        if (gridish(g)) found.push({ path: `RealGrid.getGridInstance("${id}")`, obj: g });
      });
    }
  });
  safe('getActiveGrid', () => {
    const g = RealGrid.getActiveGrid();
    log(`  getActiveGrid() → ${g ? (gridish(g) ? '그리드 객체!' : typeof g) : '없음'}`);
    if (gridish(g)) found.push({ path: 'RealGrid.getActiveGrid()', obj: g });
  });
  safe('exportGrid', () => {
    log(`  exportGrid: ${typeof RealGrid.exportGrid}`);
  });

  log('');
  log('===== 2. React 내부를 타고 찾기 =====');
  for (const id of ['GRID_TOP','GRID_DOWN']) {
    safe('react:' + id, () => {
      const el = document.getElementById(id);
      if (!el) { log(`  ${id}: 요소 없음`); return; }
      const key = Object.keys(el).find(k => k.startsWith('__react'));
      if (!key) { log(`  ${id}: React 참조 없음`); return; }
      let node = el[key];
      let hit = false;
      for (let d = 0; d < 25 && node; d++) {
        for (const slot of ['stateNode','memoizedProps','memoizedState']) {
          safe('slot', () => {
            const s = node[slot];
            if (!s || typeof s !== 'object') return;
            if (gridish(s)) { found.push({ path: `#${id} react.${slot}(깊이${d})`, obj: s }); log(`  ${id}: ${slot} 깊이${d} 에서 발견`); hit = true; }
            for (const k of Object.keys(s).slice(0, 80)) {
              try {
                if (gridish(s[k])) {
                  found.push({ path: `#${id} react.${slot}.${k}(깊이${d})`, obj: s[k] });
                  log(`  ${id}: ${slot}.${k} 깊이${d} 에서 발견`);
                  hit = true;
                }
              } catch (e) {}
            }
          });
        }
        node = node.return || node._owner || null;
      }
      if (!hit) log(`  ${id}: React 경로에서는 못 찾음`);
    });
  }

  log('');
  log('===== 3. 꺼낸 객체 살펴보기 =====');
  if (!found.length) { log('  찾지 못했습니다.'); return L.join('\n'); }

  const seen = [];
  for (const f of found) {
    if (seen.includes(f.obj)) { log(`\n  --- ${f.path} (위와 같은 객체) ---`); continue; }
    seen.push(f.obj);
    log(`\n  --- ${f.path} ---`);
    const g = f.obj;

    safe('methods', () => {
      const ms = methodsOf(g).filter(m => /get|set|commit|refresh|export|update|value|row|column|cell|check/i.test(m));
      log(`    메서드 ${ms.length}개: ${ms.slice(0, 60).join(', ')}`);
    });

    safe('columns', () => {
      if (typeof g.getColumns !== 'function') { log('    getColumns 없음'); return; }
      const cols = g.getColumns();
      log(`    컬럼 ${cols.length}개`);
      cols.slice(0, 45).forEach((c, i) => {
        let name = '', head = '', field = '';
        try { name = String(c.name || ''); } catch (e) {}
        try { field = String(c.fieldName || ''); } catch (e) {}
        try {
          const h = c.header;
          head = h == null ? '' : (typeof h === 'object' ? String(h.text || '') : String(h));
        } catch (e) {}
        log(`      ${i}: name=${name}  field=${field}  header=${head}`);
      });
    });

    let src = g;
    safe('datasource', () => {
      if (typeof g.getDataSource === 'function') {
        const dp = g.getDataSource();
        if (dp) {
          src = dp;
          log('    getDataSource() 있음');
          const ms = methodsOf(dp).filter(m => /get|set|row|value|json|update|commit/i.test(m));
          log(`      데이터원본 메서드: ${ms.slice(0, 50).join(', ')}`);
        }
      }
    });

    safe('rowcount', () => {
      for (const m of ['getRowCount','getItemCount']) {
        if (typeof src[m] === 'function') log(`    ${m}() = ${src[m]()}`);
      }
    });

    safe('sample', () => {
      if (typeof src.getJsonRows === 'function') {
        const rows = src.getJsonRows(0, 1);
        if (rows && rows.length) {
          log('    샘플행(마스킹):');
          for (const k of Object.keys(rows[0])) log(`      ${k} = ${mask(rows[0][k])}`);
          return;
        }
      }
      if (typeof src.getValues === 'function') {
        log('    샘플행(마스킹): ' + (src.getValues(0) || []).map(mask).join(' | '));
      }
    });

    safe('writable', () => {
      const w = ['setValue','setValues','updateRow','updateRows','setEditable','checkAll','setCheckedRows']
        .filter(m => { try { return typeof src[m] === 'function' || typeof g[m] === 'function'; } catch (e) { return false; } });
      log(`    쓰기 메서드: ${w.length ? w.join(', ') : '없음'}`);
    });
  }

  return L.join('\n');
}"""


print()
print("=" * 62)
print("  RealGrid 객체 탐색 (v3)")
print("=" * 62)
print()
print("  크롬열기.bat 으로 띄운 크롬에서")
print("  전자세금계산서 화면에 자료가 보이는 상태여야 합니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            say("열린 탭: " + ", ".join(pg.url[:80] for pg in pages))
        else:
            say(f"대상 탭: {target.url[:130]}\n")
            say(target.evaluate(PROBE))
        browser.close()
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
