"""편집기를 실제로 열어 계정과목을 입력해본다. 한 건만.

앞선 시험에서 setValue 로 값은 들어갔지만 전표상태가 미추천 그대로였다.
코드를 읽어보니 이유가 분명했다.

  _onCellEdited 안에서 차변계정이 편집되면 filterStoreData 를 부르는데,
  그 함수가 계정코드를 채우고 전표상태를 바꾸고 하단 분개를 만든다.
  setValue 만 부르면 이 흐름이 아예 시작되지 않는다.

filterStoreData 를 직접 부르는 대신 RealGrid 편집기를 실제로 연다.
commitEditor 가 진짜 편집 이벤트를 일으키므로 위하고의
onEditCommit -> onCellEdited -> filterStoreData 가 평소 순서대로 돈다.
인자를 지어낼 필요가 없고, 사람이 타이핑한 것과 같은 경로다.

두 가지를 순서대로 시험한다.
  A 편집기 경로   setCurrent -> showEditor -> setEditValue -> commitEditor
  B 직접 호출     setCurrent -> setValue -> onCellEdited

성공 판정은 오직 하나. 전표상태가 미추천에서 바뀌는가.
전송(F3)은 부르지 않는다.
"""
import collections
import json
import re
import traceback

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
STATUS_미추천 = "5"
TOP_MARK = "nm_acctit_cha"
FIELD = "nm_acctit_cha"

NOISE = [re.compile(r"\(오더번호[^)]*\)"), re.compile(r"\(\d[^)]*\)"),
         re.compile(r"\[[^\]]*\]"), re.compile(r"외\s*\d+\s*건"), re.compile(r"\d+")]


def norm_item(name):
    s = str(name or "")
    for pat in NOISE:
        s = pat.sub(" ", s)
    return re.sub(r"[\s\-_/,]+", " ", s).strip().lower()


GRAB = r"""() => {
  const MARK = '%MARK%';
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const seen = new WeakSet();
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
      if (gridish(v)) {
        let cn = [];
        try { cn = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cn.includes(MARK)) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          let rows = [], count = 0;
          try {
            const src = window.__dp || v;
            count = src.getRowCount();
            rows = src.getJsonRows(0, count - 1) || [];
          } catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 200) }); }
          const has = m => { try { return typeof v[m] === 'function'; } catch (e) { return false; } };
          return JSON.stringify({ ok: true, rowCount: count, rows: rows, cols: cn,
            api: ['setCurrent','getCurrent','showEditor','setEditValue','commitEditor',
                  'hideEditor','cancelEditor','onCellEdited','setValue','commit']
                 .filter(has) });
        }
      }
      if (d < 9) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}""".replace("%MARK%", TOP_MARK)

# A: 편집기를 실제로 열어 입력한다
ROUTE_A = r"""(args) => {
  const { row, field, value, expect } = args;
  const g = window.__g, dp = window.__dp;
  const log = [];
  const read = () => { try { return (dp || g).getJsonRows(row, row)[0] || null; } catch (e) { return null; } };

  const before = read();
  if (!before) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  for (const k of Object.keys(expect)) {
    if (String(before[k] ?? '') !== String(expect[k] ?? '')) {
      return JSON.stringify({ ok: false, reason: `대조 실패: ${k}` });
    }
  }

  try {
    g.setCurrent({ itemIndex: row, dataRow: row, column: field, fieldName: field });
    log.push(`setCurrent(${row}, ${field})`);
    log.push('현재칸: ' + JSON.stringify(g.getCurrent()));
  } catch (e) { log.push('setCurrent 오류: ' + String(e).slice(0, 140)); }

  try { g.showEditor(); log.push('showEditor()'); }
  catch (e) { log.push('showEditor 오류: ' + String(e).slice(0, 140)); }
  try { log.push('편집중? ' + g.isItemEditing()); } catch (e) {}

  try { g.setEditValue(value, false, false); log.push(`setEditValue("${value}")`); }
  catch (e) { log.push('setEditValue 오류: ' + String(e).slice(0, 140)); }

  try { g.commitEditor(true); log.push('commitEditor()'); }
  catch (e) { log.push('commitEditor 오류: ' + String(e).slice(0, 140)); }

  try { if (g.commit) { g.commit(); log.push('commit()'); } } catch (e) {}
  return JSON.stringify({ ok: true, log: log, before: before, after: read() });
}"""

# B: setValue 로 넣고 위하고의 편집 처리 함수를 직접 부른다
ROUTE_B = r"""(args) => {
  const { row, field, value } = args;
  const g = window.__g, dp = window.__dp;
  const log = [];
  const read = () => { try { return (dp || g).getJsonRows(row, row)[0] || null; } catch (e) { return null; } };

  let colIndex = -1;
  try { colIndex = g.getColumns().findIndex(c => String(c.name || c.fieldName) === field); } catch (e) {}

  try {
    g.setCurrent({ itemIndex: row, dataRow: row, column: field, fieldName: field });
    log.push('setCurrent 완료');
  } catch (e) { log.push('setCurrent 오류: ' + String(e).slice(0, 140)); }

  try { g.setValue(row, field, value); log.push(`setValue(${row}, ${field})`); }
  catch (e) { log.push('setValue 오류: ' + String(e).slice(0, 140)); }

  // onCellEdited(그리드, 아이템번호, 데이터행, 컬럼번호)
  try {
    const r = g.onCellEdited(g, row, row, colIndex);
    log.push(`onCellEdited(g, ${row}, ${row}, ${colIndex}) → ${r}`);
  } catch (e) { log.push('onCellEdited 오류: ' + String(e).slice(0, 180)); }

  try { if (g.commit) { g.commit(); log.push('commit()'); } } catch (e) {}
  return JSON.stringify({ ok: true, log: log, after: read() });
}"""

RESTORE = r"""(args) => {
  const { row, original } = args;
  const g = window.__g;
  const log = [];
  for (const f of Object.keys(original)) {
    try { g.setValue(row, f, original[f]); log.push(`${f} 되돌림`); }
    catch (e) { log.push(`${f} 오류: ${String(e).slice(0, 100)}`); }
  }
  try { if (g.commit) g.commit(); } catch (e) {}
  return JSON.stringify({ log: log });
}"""

KEEP = ["nm_acctit_cha", "cd_acctit_cha", "nm_acctit_dae", "cd_acctit_dae", "ty_jungstat"]


def report(tag, res, target):
    print(f"\n  [{tag}] 실행 기록")
    for line in res.get("log", []):
        print(f"    {line}")
    after = res.get("after") or {}
    print(f"\n  [{tag}] 결과")
    for f in KEEP:
        print(f"    {f} = {after.get(f)}")
    ok = str(after.get("ty_jungstat")) != STATUS_미추천
    print(f"\n  → 전표상태 {'바뀜! 성공' if ok else '미추천 그대로 (실패)'}")
    return ok, after


print()
print("=" * 62)
print("  편집기 경로 시험 - 한 건")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  전송(F3)은 부르지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        page = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if page is None:
            print("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit

        data = json.loads(page.evaluate(GRAB))
        if not data.get("ok"):
            print(f"\n  {data.get('reason')}")
            print("  전표 목록에서 줄을 클릭하신 뒤 다시 실행해주세요.")
            raise SystemExit

        rows = data["rows"]
        print(f"\n  그리드 확인됨 / 행 {len(rows)}개")
        print(f"  쓸 수 있는 API: {', '.join(data['api'])}")

        by_biz = collections.defaultdict(collections.Counter)
        for r in rows:
            if r.get("nm_acctit_cha") and r.get("no_bisocial"):
                by_biz[str(r["no_bisocial"])][r["nm_acctit_cha"]] += 1

        pick = None
        for i, r in enumerate(rows):
            if str(r.get("ty_jungstat")) != STATUS_미추천:
                continue
            hist = by_biz.get(str(r.get("no_bisocial") or ""))
            if hist and len(hist) == 1:
                pick = (i, r, hist.most_common(1)[0][0], sum(hist.values()))
                break
        if pick is None:
            print("\n  시험에 쓸 만한 미추천 건이 없습니다.")
            raise SystemExit

        i, r, acct, n = pick
        original = {f: r.get(f) for f in KEEP}
        print()
        print("  " + "-" * 56)
        print(f"   대상: {i}번째 줄")
        print(f"   거래처 : {r.get('nm_trade')}")
        print(f"   품명   : {r.get('nm_good')}")
        print(f"   현재 차변계정: {r.get('nm_acctit_cha') or '(비어있음)'}")
        print(f"   현재 전표상태: {r.get('ty_jungstat')} (5=미추천)")
        print(f"\n   넣을 값: {FIELD} = {acct}")
        print(f"   근거: 같은 사업자번호 과거 {n}건이 모두 이 계정")
        print("  " + "-" * 56)
        print()
        if input("  A안(편집기 경로)을 시험할까요? (y = 진행) >>> ").strip().lower() != "y":
            print("  아무것도 하지 않았습니다.")
            raise SystemExit

        res = json.loads(page.evaluate(ROUTE_A, {
            "row": i, "field": FIELD, "value": acct,
            "expect": {"nm_trade": r.get("nm_trade"), "mn_mnam": r.get("mn_mnam")},
        }))
        if not res.get("ok"):
            print(f"\n  A안 실패: {res.get('reason')}")
        else:
            ok, _ = report("A안 편집기", res, r)
            if not ok:
                print()
                if input("  B안(직접 호출)도 시험할까요? (y = 진행) >>> ").strip().lower() == "y":
                    res_b = json.loads(page.evaluate(ROUTE_B, {"row": i, "field": FIELD, "value": acct}))
                    report("B안 직접호출", res_b, r)

        print()
        print("  " + "=" * 56)
        print("   [꼭 확인] 위하고 화면에서 그 줄을 봐주세요.")
        print("     1. 차변계정에 값이 보이나요?")
        print("     2. 차변 계정코드도 같이 채워졌나요?")
        print("     3. 전표상태가 '미추천' 에서 바뀌었나요?")
        print("     4. 아래쪽 분개 줄이 만들어졌나요?")
        print("  " + "=" * 56)
        print()
        if input("  원래대로 되돌릴까요? (y = 되돌리기) >>> ").strip().lower() == "y":
            back = json.loads(page.evaluate(RESTORE, {"row": i, "original": original}))
            for line in back["log"]:
                print(f"    {line}")
            print("  되돌렸습니다. 화면에서도 확인해주세요.")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 62)
print("  전송(F3)은 누르지 않았습니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
