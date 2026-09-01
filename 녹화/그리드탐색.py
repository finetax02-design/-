"""페이지 안의 RealGrid 객체를 찾아 다룰 수 있는지 확인한다 (v2).

v1 은 탐색 결과를 객체로 돌려주다가 변환에 실패했다. RealGrid 의 컬럼
정보에는 그대로 넘길 수 없는 값이 섞여 있다. 그래서 v2 는 브라우저 쪽에서
결과를 전부 글자로 만들어 한 덩어리로 넘긴다. 어떤 값이 들어와도 깨지지 않는다.

탐색 범위도 넓혔다. RealGrid 객체가 전역에 없으면 Vue/React 내부와
그리드 요소에 붙은 참조까지 뒤진다.

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


# 브라우저 안에서 실행되며, 결과를 글자 하나로 만들어 돌려준다.
PROBE = r"""() => {
  const L = [];
  const log = s => L.push(String(s));
  const mask = v => {
    if (v === null || v === undefined) return '(빈값)';
    try { return String(v).replace(/\d/g, '#').slice(0, 12); } catch (e) { return '(변환실패)'; }
  };
  const safe = (label, fn) => {
    try { return fn(); } catch (e) { log(`  [${label}] 오류: ${String(e).slice(0, 150)}`); return null; }
  };

  const GRID_METHODS = ['getDataSource','setDataSource','getItemCount','getColumns',
                        'getJsonRows','getRowCount','setValue','getValues','getValue',
                        'setEditable','commit','refresh'];
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    let hits = 0;
    for (const m of GRID_METHODS) { try { if (typeof o[m] === 'function') hits++; } catch (e) {} }
    return hits >= 2;
  };

  log('===== 1. RealGrid 전역 이름 =====');
  for (const n of ['RealGrid','RealGridJS','realgrid','RealGrid2','GridView']) {
    safe(n, () => {
      const t = typeof window[n];
      log(`  window.${n} : ${t}`);
      if (t === 'object' || t === 'function') {
        const ks = Object.keys(window[n]).slice(0, 25);
        log(`      속성: ${ks.join(', ')}`);
      }
    });
  }

  log('');
  log('===== 2. window 안의 그리드 같은 객체 =====');
  const found = [];
  let keys = [];
  safe('window키', () => { keys = Object.keys(window); });
  log(`  window 속성 ${keys.length}개 검사`);
  for (const k of keys) {
    safe('scan:' + k, () => {
      const v = window[k];
      if (gridish(v)) {
        found.push({ path: 'window.' + k, obj: v });
        const ms = GRID_METHODS.filter(m => { try { return typeof v[m] === 'function'; } catch (e) { return false; } });
        log(`  window.${k}  →  ${ms.join(', ')}`);
      }
    });
  }
  if (!found.length) log('  없음');

  log('');
  log('===== 3. 그리드 요소에 붙은 내부 참조 =====');
  for (const id of ['GRID_TOP','GRID_DOWN']) {
    safe('el:' + id, () => {
      const el = document.getElementById(id);
      if (!el) { log(`  ${id}: 요소 없음`); return; }
      const ks = Object.keys(el).filter(k => k.startsWith('_') || k.startsWith('$'));
      log(`  ${id}: ${ks.length ? ks.slice(0, 20).join(', ') : '(내부 참조 없음)'}`);
      for (const k of ks) {
        safe('elref', () => {
          const v = el[k];
          if (gridish(v)) { found.push({ path: `#${id}.${k}`, obj: v }); log(`      → ${k} 가 그리드!`); }
          // Vue 컴포넌트면 그 안의 속성도 한 겹 본다
          if (v && typeof v === 'object') {
            for (const inner of ['ctx','proxy','setupState','data','$data','$refs']) {
              const iv = v[inner];
              if (iv && typeof iv === 'object') {
                for (const ik of Object.keys(iv).slice(0, 60)) {
                  if (gridish(iv[ik])) {
                    found.push({ path: `#${id}.${k}.${inner}.${ik}`, obj: iv[ik] });
                    log(`      → ${k}.${inner}.${ik} 가 그리드!`);
                  }
                }
              }
            }
          }
        });
      }
    });
  }

  log('');
  log('===== 4. 찾은 객체에서 실제로 꺼내보기 =====');
  if (!found.length) log('  꺼내볼 객체가 없습니다.');
  for (const f of found) {
    log(`\n  --- ${f.path} ---`);
    const g = f.obj;
    safe('columns', () => {
      if (typeof g.getColumns !== 'function') { log('    getColumns 없음'); return; }
      const cols = g.getColumns();
      log(`    컬럼 ${cols.length}개`);
      cols.slice(0, 40).forEach((c, i) => {
        let name = '', head = '';
        try { name = String(c.name || c.fieldName || ''); } catch (e) {}
        try {
          const h = c.header;
          head = h == null ? '' : (typeof h === 'object' ? String(h.text || '') : String(h));
        } catch (e) {}
        log(`      ${i}: name=${name}  header=${head}`);
      });
    });
    let src = g;
    safe('datasource', () => {
      if (typeof g.getDataSource === 'function') {
        const dp = g.getDataSource();
        if (dp) { src = dp; log('    getDataSource() 있음'); }
      }
    });
    safe('rowcount', () => {
      for (const m of ['getRowCount','getItemCount']) {
        if (typeof src[m] === 'function') { log(`    ${m}() = ${src[m]()}`); }
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
        const vals = src.getValues(0);
        log('    샘플행(마스킹): ' + (vals || []).map(mask).join(' | '));
      }
    });
    safe('writable', () => {
      const w = ['setValue','setValues','updateRow','setEditable']
        .filter(m => typeof src[m] === 'function' || typeof g[m] === 'function');
      log(`    쓰기 메서드: ${w.length ? w.join(', ') : '없음'}`);
    });
  }

  return L.join('\n');
}"""


print()
print("=" * 62)
print("  RealGrid 객체 탐색 (v2)")
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
print("  이 파일을 보내주세요.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
