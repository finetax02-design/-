"""RealGrid 객체를 찾는 마지막 시도 (v4).

v3 까지 실패한 것
  RealGrid.getGridInstance / getActiveGrid  → 없음
  React fiber 를 거슬러 올라가기            → 못 찾음
그리드 객체가 모듈 안에 갇혀 밖에서 안 보이는 상태다.

v4 는 두 가지를 더 해본다.
  A. window 에서 시작해 넓게 훑기 (깊이 6, 노드 3만개 제한)
     v3 은 window 바로 아래만 봤다. 한 겹 안쪽에 있으면 여기서 잡힌다.
  B. 생성 순간 가로채기
     페이지를 새로고침하기 전에 GridView 생성자를 감싸두면
     그리드가 만들어질 때 그 객체를 붙잡을 수 있다. 가장 확실한 방법이다.
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


# 그리드가 만들어질 때 낚아채는 코드. 페이지 스크립트보다 먼저 실행된다.
HOOK = r"""
(() => {
  if (window.__gridHookInstalled) return;
  window.__gridHookInstalled = true;
  window.__grids = [];

  const wrap = (holder, name) => {
    const Orig = holder[name];
    if (typeof Orig !== 'function' || Orig.__wrapped) return false;
    function Patched(...args) {
      const inst = new Orig(...args);
      try { window.__grids.push({ kind: name, id: String(args[0]), inst: inst }); } catch (e) {}
      return inst;
    }
    Patched.__wrapped = true;
    Patched.prototype = Orig.prototype;
    try { Object.setPrototypeOf(Patched, Orig); } catch (e) {}
    for (const k of Object.keys(Orig)) { try { Patched[k] = Orig[k]; } catch (e) {} }
    holder[name] = Patched;
    return true;
  };

  // RealGridJS 는 나중에 로드될 수 있으므로 잠시 지켜본다
  let tries = 0;
  const timer = setInterval(() => {
    let done = 0;
    for (const ns of ['RealGridJS', 'RealGrid']) {
      const holder = window[ns];
      if (!holder) continue;
      for (const cls of ['GridView', 'TreeView', 'LocalDataProvider', 'LocalTreeDataProvider']) {
        if (holder[cls] && wrap(holder, cls)) done++;
      }
    }
    if (done || ++tries > 400) clearInterval(timer);
  }, 50);
})();
"""

DEEP_SCAN = r"""() => {
  const L = [];
  const log = s => L.push(String(s));
  const mask = v => { try { return String(v).replace(/\d/g, '#').slice(0, 14); } catch (e) { return '?'; } };
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    let n = 0;
    for (const m of ['getDataSource','setDataSource','getColumns','setColumns','getItemCount',
                     'getRowCount','setValue','getValues','getJsonRows','getJsonRow']) {
      try { if (typeof o[m] === 'function') n++; } catch (e) {}
    }
    return n >= 2;
  };

  log('===== A-1. RealGrid / RealGridJS 속성 전체 =====');
  for (const ns of ['RealGrid', 'RealGridJS']) {
    try {
      const o = window[ns];
      if (!o) { log(`  window.${ns}: 없음`); continue; }
      const ks = Object.keys(o);
      log(`  window.${ns} (${typeof o}) 속성 ${ks.length}개:`);
      log('    ' + ks.join(', '));
    } catch (e) { log(`  window.${ns} 오류: ${String(e).slice(0, 120)}`); }
  }

  log('');
  log('===== A-2. getGridInstance 여러 방식으로 =====');
  try {
    const args = [undefined, 0, 1, '0', 'GRID_TOP', 'GRID_DOWN', 'gridTopView', 'gridView'];
    for (const a of args) {
      try {
        const g = RealGrid.getGridInstance(a);
        log(`  getGridInstance(${JSON.stringify(a)}) → ${g ? (gridish(g) ? '그리드!' : typeof g) : '없음'}`);
      } catch (e) { log(`  getGridInstance(${JSON.stringify(a)}) 오류: ${String(e).slice(0, 80)}`); }
    }
  } catch (e) { log('  RealGrid 접근 불가'); }

  log('');
  log('===== A-3. window 에서 넓게 훑기 (깊이 6) =====');
  const seen = new WeakSet();
  const hits = [];
  let visited = 0;
  const queue = [{ o: window, path: 'window', d: 0 }];
  const SKIP = /^(window|document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;

  while (queue.length && visited < 30000 && hits.length < 12) {
    const { o, path, d } = queue.shift();
    if (d > 6) continue;
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
      if (gridish(v)) { hits.push({ path: path + '.' + k, obj: v }); log(`  발견: ${path}.${k}`); }
      if (d < 6) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }
  log(`  검사한 객체 ${visited}개, 발견 ${hits.length}개`);

  log('');
  log('===== A-4. 가로채기로 잡힌 그리드 =====');
  const caught = window.__grids || null;
  if (!caught) log('  가로채기가 설치되지 않았습니다 (새로고침 전).');
  else {
    log(`  잡힌 객체 ${caught.length}개`);
    caught.forEach((c, i) => {
      log(`    ${i}: ${c.kind}("${c.id}")  그리드여부=${gridish(c.inst)}`);
      if (gridish(c.inst)) hits.push({ path: `__grids[${i}].inst (${c.kind})`, obj: c.inst });
    });
  }

  log('');
  log('===== B. 찾은 객체 살펴보기 =====');
  if (!hits.length) { log('  없습니다.'); return L.join('\n'); }
  const done = [];
  for (const h of hits) {
    if (done.includes(h.obj)) continue;
    done.push(h.obj);
    log(`\n  --- ${h.path} ---`);
    const g = h.obj;
    try {
      const ms = [];
      let cur = g;
      for (let i = 0; i < 4 && cur; i++) {
        for (const k of Object.getOwnPropertyNames(cur)) {
          try { if (typeof g[k] === 'function' && !ms.includes(k)) ms.push(k); } catch (e) {}
        }
        cur = Object.getPrototypeOf(cur);
      }
      log(`    메서드: ${ms.filter(m => /get|set|commit|refresh|export|update|check|row|column|value|cell/i.test(m)).slice(0, 60).join(', ')}`);
    } catch (e) {}
    try {
      if (typeof g.getColumns === 'function') {
        const cols = g.getColumns();
        log(`    컬럼 ${cols.length}개`);
        cols.slice(0, 45).forEach((c, i) => {
          let nm = '', fd = '', hd = '';
          try { nm = String(c.name || ''); } catch (e) {}
          try { fd = String(c.fieldName || ''); } catch (e) {}
          try { const x = c.header; hd = x == null ? '' : (typeof x === 'object' ? String(x.text || '') : String(x)); } catch (e) {}
          log(`      ${i}: name=${nm}  field=${fd}  header=${hd}`);
        });
      }
    } catch (e) { log(`    컬럼 오류: ${String(e).slice(0, 120)}`); }
    let src = g;
    try { if (typeof g.getDataSource === 'function') { const dp = g.getDataSource(); if (dp) { src = dp; log('    getDataSource() 있음'); } } } catch (e) {}
    try {
      for (const m of ['getRowCount', 'getItemCount']) {
        if (typeof src[m] === 'function') log(`    ${m}() = ${src[m]()}`);
      }
    } catch (e) {}
    try {
      if (typeof src.getJsonRows === 'function') {
        const rows = src.getJsonRows(0, 1);
        if (rows && rows.length) {
          log('    샘플행(마스킹):');
          for (const k of Object.keys(rows[0])) log(`      ${k} = ${mask(rows[0][k])}`);
        }
      } else if (typeof src.getValues === 'function') {
        log('    샘플행(마스킹): ' + (src.getValues(0) || []).map(mask).join(' | '));
      }
    } catch (e) { log(`    샘플 오류: ${String(e).slice(0, 120)}`); }
    try {
      const w = ['setValue','setValues','updateRow','updateRows','setEditable']
        .filter(m => { try { return typeof src[m] === 'function' || typeof g[m] === 'function'; } catch (e) { return false; } });
      log(`    쓰기 메서드: ${w.length ? w.join(', ') : '없음'}`);
    } catch (e) {}
  }
  return L.join('\n');
}"""


print()
print("=" * 62)
print("  RealGrid 객체 탐색 (v4) - 마지막 시도")
print("=" * 62)
print()
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
            say("########## 1차: 새로고침 없이 ##########")
            say(target.evaluate(DEEP_SCAN))

            print()
            print("  " + "-" * 56)
            print("   1차에서 못 찾았다면 '가로채기'를 해봅니다.")
            print("   페이지를 새로고침하므로 조회 결과가 사라집니다.")
            print("   새로고침 후 다시 조회하셔야 합니다.")
            print("  " + "-" * 56)
            if input("\n  진행할까요? (y = 진행, 그냥 Enter = 건너뛰기) >>> ").strip().lower() == "y":
                target.add_init_script(HOOK)
                say("\n\n########## 2차: 가로채기 설치 후 새로고침 ##########")
                target.reload(wait_until="domcontentloaded", timeout=90000)
                print("\n  새로고침했습니다.")
                print("  전자세금계산서 화면에서 다시 조회해 자료가 보이게 하신 뒤")
                input("  Enter 를 눌러주세요 >>> ")
                say(target.evaluate(DEEP_SCAN))

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
