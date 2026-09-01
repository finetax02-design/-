"""왜 계정과목이 안 들어갔는지 알아낸다. 한 줄에 대해 단계별로 기록한다.

화면을 보니 차변계정 칸에 '미추천' 이라는 글자가 값으로 들어 있었다.
비어 있는 것이 아니다. '비어 있을 때만 쓴다' 는 조건에 걸려
아무것도 안 했을 수 있다.

그리고 편집기가 열린 채 값이 안 들어간 것으로 보이는데,
계정과목 칸이 목록에서 고르는 편집기라면 자유 입력이 안 먹는다.

확인할 것
  1 미추천 줄의 실제 값 (차변 대변 계정명과 코드)
  2 nm_acctit_cha 컬럼의 편집기 종류와 설정
  3 세 가지 쓰기 방법을 하나씩 시도하며 단계마다 값이 어떻게 변하는지

읽기와 한 줄 시험만 한다. 전송(F3)은 부르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "진단2.txt"
TOP_MARK = "nm_acctit_cha"
STATUS_미추천 = "5"

INSPECT = r"""() => {
  const L = [];
  const log = s => L.push(String(s));
  const show = (v, d) => {
    d = d || 0;
    try {
      if (v === null) return 'null';
      if (v === undefined) return 'undefined';
      const t = typeof v;
      if (t === 'function') return '(함수)';
      if (t !== 'object') return JSON.stringify(v);
      if (Array.isArray(v)) return d > 1 ? `(배열${v.length})` : '[' + v.slice(0, 30).map(x => show(x, d + 1)).join(', ') + ']';
      if (d > 1) return '(객체)';
      return '{' + Object.keys(v).slice(0, 20).map(k => k + ':' + show(v[k], d + 1)).join(', ') + '}';
    } catch (e) { return '(읽기실패)'; }
  };
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };

  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0, g = null;
  while (queue.length && visited < 60000 && !g) {
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
        let cn = [];
        try { cn = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cn.includes('nm_acctit_cha')) { g = v; break; }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  if (!g) return '전표 목록을 못 찾았습니다.';
  window.__g = g;
  try { window.__dp = g.getDataSource(); } catch (e) { window.__dp = null; }
  const src = window.__dp || g;

  // 1) 미추천 줄의 실제 값
  log('===== 1. 미추천 줄의 실제 값 =====');
  let count = 0, rows = [];
  try { count = src.getRowCount(); rows = src.getJsonRows(0, count - 1) || []; } catch (e) { log('행 읽기 오류: ' + e); }
  log(`  전체 ${rows.length}행`);
  const targets = [];
  rows.forEach((r, i) => { if (String(r.ty_jungstat) === '5') targets.push(i); });
  log(`  미추천 ${targets.length}건, 줄번호 앞 10개: ${targets.slice(0, 10).join(', ')}`);
  const F = ['nm_acctit_cha','cd_acctit_cha','key_acctit_cha',
             'nm_acctit_dae','cd_acctit_dae','key_acctit_dae',
             'ty_jungstat','exists_recommend_cha','exists_recommend_dae','yn_bungae'];
  for (const i of targets.slice(0, 3)) {
    log(`\n  --- ${i}번째 줄 ---`);
    for (const f of F) log(`    ${f} = ${show(rows[i][f])}`);
  }
  window.__targets = targets;

  // 2) 계정과목 칸의 편집기 종류
  log('');
  log('===== 2. nm_acctit_cha 컬럼 정의 =====');
  try {
    const col = g.getColumns().find(c => String(c.name || c.fieldName) === 'nm_acctit_cha');
    if (!col) log('  컬럼을 못 찾음');
    else {
      for (const k of ['name','fieldName','editable','readOnly','editor','editorOptions',
                       'lookupDisplay','values','labels','button','buttonVisibility',
                       'lookupSourceId','lookupKeyFields','dataType','type']) {
        try { if (col[k] !== undefined) log(`    ${k} = ${show(col[k])}`); } catch (e) {}
      }
    }
  } catch (e) { log('  오류: ' + String(e).slice(0, 150)); }

  // 3) 편집 관련 상태
  log('');
  log('===== 3. 그리드 편집 상태 =====');
  for (const m of ['isItemEditing','getCurrent','getEditValue']) {
    try { log(`    ${m}() = ${show(g[m]())}`); } catch (e) { log(`    ${m}() 오류: ${String(e).slice(0, 120)}`); }
  }
  try { log(`    editOptions = ${show(g.getEditOptions())}`); } catch (e) {}

  return L.join('\n');
}"""

# 세 가지 방법을 하나씩 시도하며 단계마다 값을 기록한다
TRY = r"""(args) => {
  const { row, field, value, method } = args;
  const g = window.__g, dp = window.__dp;
  const L = [];
  const log = s => L.push(String(s));
  const peek = tag => {
    try {
      const r = (dp || g).getJsonRows(row, row)[0] || {};
      log(`    [${tag}] nm_cha=${JSON.stringify(r.nm_acctit_cha)} cd_cha=${JSON.stringify(r.cd_acctit_cha)}`
          + ` nm_dae=${JSON.stringify(r.nm_acctit_dae)} 상태=${JSON.stringify(r.ty_jungstat)}`);
    } catch (e) { log(`    [${tag}] 읽기 오류`); }
  };

  log(`### 방법 ${method} : ${field} <- "${value}" (${row}번째 줄)`);
  peek('시작');

  try { g.setCurrent({ itemIndex: row, dataRow: row, column: field, fieldName: field });
        log(`    setCurrent 후 현재칸 = ${JSON.stringify(g.getCurrent())}`); }
  catch (e) { log('    setCurrent 오류: ' + String(e).slice(0, 140)); }

  if (method === 'A') {
    try { g.showEditor(); log(`    showEditor / 편집중=${g.isItemEditing()}`); }
    catch (e) { log('    showEditor 오류: ' + String(e).slice(0, 140)); }
    try { g.setEditValue(value, false, false); log(`    setEditValue / 편집값=${JSON.stringify(g.getEditValue())}`); }
    catch (e) { log('    setEditValue 오류: ' + String(e).slice(0, 140)); }
    try { g.commitEditor(true); log('    commitEditor'); }
    catch (e) { log('    commitEditor 오류: ' + String(e).slice(0, 140)); }
  } else if (method === 'B') {
    let ci = -1;
    try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === field); } catch (e) {}
    try { g.setValue(row, field, value); log('    setValue'); }
    catch (e) { log('    setValue 오류: ' + String(e).slice(0, 140)); }
    peek('setValue 직후');
    try { const r = g.onCellEdited(g, row, row, ci); log(`    onCellEdited(g,${row},${row},${ci}) → ${r}`); }
    catch (e) { log('    onCellEdited 오류: ' + String(e).slice(0, 200)); }
  } else if (method === 'C') {
    let ci = -1;
    try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === field); } catch (e) {}
    try { g.setValue(row, field, value); log('    setValue'); }
    catch (e) { log('    setValue 오류: ' + String(e).slice(0, 140)); }
    try {
      const idx = { itemIndex: row, dataRow: row, column: field, fieldName: field, fieldIndex: ci };
      const r = g.onEditCommit(g, idx, null, value);
      log(`    onEditCommit → ${r}`);
    } catch (e) { log('    onEditCommit 오류: ' + String(e).slice(0, 200)); }
    try { const r = g.onCellEdited(g, row, row, ci); log(`    onCellEdited → ${r}`); }
    catch (e) { log('    onCellEdited 오류: ' + String(e).slice(0, 200)); }
  }

  try { if (g.commit) { g.commit(); log('    commit()'); } } catch (e) {}
  peek('끝');
  return L.join('\n');
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  왜 안 들어갔는지 진단")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        page = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if page is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit

        say(page.evaluate(INSPECT))

        print()
        print("  " + "-" * 56)
        print("   이제 한 줄에 세 가지 방법을 하나씩 시도합니다.")
        print("   각 단계마다 값이 어떻게 변하는지 기록합니다.")
        print("  " + "-" * 56)
        row = input("\n  시험할 줄 번호 (위 목록에서 하나, 그냥 Enter = 첫 번째) >>> ").strip()
        value = input("  넣어볼 차변 계정과목 (예: 의약품) >>> ").strip()
        if not value:
            print("  계정과목을 입력하지 않아 여기서 멈춥니다.")
            raise SystemExit

        targets = page.evaluate("() => window.__targets || []")
        if not targets:
            print("  미추천 줄이 없습니다.")
            raise SystemExit
        row = int(row) if row.isdigit() else targets[0]

        for method in ("A", "B", "C"):
            print()
            if input(f"  방법 {method} 를 시도할까요? (y = 진행, Enter = 건너뛰기) >>> ").strip().lower() != "y":
                continue
            say("")
            say(page.evaluate(TRY, {"row": row, "field": "nm_acctit_cha",
                                    "value": value, "method": method}))

        browser.close()
except SystemExit:
    pass
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  이 파일을 보내주세요. 화면도 함께 확인해주시면 좋습니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
