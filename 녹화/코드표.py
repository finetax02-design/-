"""전표상태 유형 불공제코드의 코드표를 컬럼 정의에서 뽑아낸다 (v2).

v1 은 행마다 getDisplayValues 로 화면 글자를 읽으려 했으나 전부 실패했고,
오류를 삼켜서 이유도 안 남았다.

v2 는 접근을 바꾼다. RealGrid 는 코드 컬럼에 values/labels 쌍을 갖고 있거나
드롭다운 편집기에 선택지 목록을 달아둔다. 컬럼 정의를 통째로 들여다보면
행을 훑지 않고도 코드표가 나온다.
getDisplayValues 도 여전히 시도하되, 이번에는 오류를 그대로 적는다.

읽기만 한다. 값을 바꾸지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "코드표.txt"

WANTED = ["ty_jungstat", "ty_mth", "ty_mth2", "cd_notdedct", "ty_trade", "gj_gubun", "yn_bungae"]

SCRIPT = r"""() => {
  const WANTED = %WANTED%;
  const L = [];
  const log = s => L.push(String(s));

  // 값을 안전하게 글자로 만든다. 배열과 얕은 객체는 펼쳐서 보여준다.
  const show = (v, depth) => {
    depth = depth || 0;
    try {
      if (v === null) return 'null';
      if (v === undefined) return 'undefined';
      const t = typeof v;
      if (t === 'function') return '(함수)';
      if (t !== 'object') return String(v).slice(0, 120);
      if (Array.isArray(v)) {
        if (depth > 1) return `(배열 ${v.length}개)`;
        return '[' + v.slice(0, 40).map(x => show(x, depth + 1)).join(', ') + (v.length > 40 ? ', ...' : '') + ']';
      }
      if (depth > 1) return '(객체)';
      const ks = Object.keys(v).slice(0, 25);
      return '{' + ks.map(k => k + ': ' + show(v[k], depth + 1)).join(', ') + '}';
    } catch (e) { return '(읽기실패)'; }
  };

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
  log(`객체 ${visited}개 검사, 그리드 ${found.length}개`);

  for (const f of found) {
    const g = f.obj;
    let cols;
    try { cols = g.getColumns(); } catch (e) { continue; }
    if (!cols || cols.length < 5) continue;

    log('');
    log('='.repeat(58));
    log(`그리드 (컬럼 ${cols.length}개)  ${f.path.slice(0, 70)}`);

    // 1) 컬럼 정의 안에 코드표가 있는지
    log('');
    log('--- 컬럼 정의 ---');
    for (const col of cols) {
      let name = '';
      try { name = String(col.name || col.fieldName || ''); } catch (e) {}
      if (!WANTED.includes(name)) continue;
      log(`\n  [${name}]`);
      let ks = [];
      try { ks = Object.keys(col); } catch (e) {}
      log(`    속성: ${ks.join(', ')}`);
      // 코드표가 들어있을 만한 자리를 집중해서 본다
      for (const k of ['values', 'labels', 'lookupDisplay', 'valueCallback', 'labelCallback',
                       'editor', 'renderer', 'header', 'displayCallback', 'styleCallback',
                       'dataType', 'fieldName', 'lookupSource']) {
        try { if (col[k] !== undefined) log(`    ${k} = ${show(col[k])}`); } catch (e) {}
      }
    }

    // 2) 화면 글자 읽기를 다시 시도하되 오류를 남긴다
    log('');
    log('--- 화면 글자 읽기 시도 ---');
    for (const m of ['getDisplayValues', 'getDisplayValuesOfRow']) {
      for (const arg of [0, 1]) {
        try {
          const v = g[m](arg);
          log(`  ${m}(${arg}) → ${v === undefined ? 'undefined' : (v === null ? 'null' : show(v))}`);
        } catch (e) {
          log(`  ${m}(${arg}) 오류: ${String(e).slice(0, 160)}`);
        }
      }
    }
    try {
      const names = cols.map(c => String(c.name || ''));
      for (const field of WANTED) {
        const i = names.indexOf(field);
        if (i < 0) continue;
        try { log(`  getValue(0, "${field}") = ${show(g.getValue ? g.getValue(0, field) : undefined)}`); } catch (e) {}
      }
    } catch (e) {}

    // 3) 데이터원본의 필드 정의
    log('');
    log('--- 데이터원본 필드 정의 ---');
    try {
      const dp = g.getDataSource();
      if (dp && typeof dp.getFields === 'function') {
        const fs = dp.getFields();
        for (const fd of fs) {
          let n = '';
          try { n = String(fd.fieldName || fd.name || ''); } catch (e) {}
          if (WANTED.includes(n)) log(`  ${n}: ${show(fd)}`);
        }
      } else { log('  getFields 없음'); }
    } catch (e) { log(`  오류: ${String(e).slice(0, 150)}`); }
  }

  return L.join('\n');
}""".replace("%WANTED%", json.dumps(WANTED))

lines: list[str] = []


def say(t: str = "") -> None:
    print(t[:300])
    lines.append(t)


print()
print("=" * 62)
print("  코드 뜻 알아내기 (v2 - 컬럼 정의에서)")
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
print("  코드와 화면 문구만 담겨 있어 보내주셔도 안전합니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
