"""미추천 전표 딱 한 건에 계정과목을 써보고, 제대로 들어갔는지 확인한다.

이 단계에서 확인해야 할 것은 '값이 들어가는가' 가 아니라
'위하고가 그 변경을 자기 것으로 인정하는가' 다.
데이터만 몰래 바꾸면 화면에는 보여도 전송할 때 반영되지 않을 수 있다.
그래서 전표상태가 미추천에서 바뀌는지를 눈으로 확인해야 한다.

안전장치
  - 잡은 그리드가 전표 목록이 맞는지 컬럼으로 검증한다
  - 쓰기 전에 그 줄의 거래처와 금액이 예상과 같은지 대조한다
  - 한 건만 쓴다
  - 원래 값을 기억해두고 바로 되돌릴 수 있게 한다
  - 전송(F3)은 절대 누르지 않는다
"""
import collections
import json
import re
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
STATUS_미추천 = "5"
TOP_MARK = "nm_acctit_cha"

NOISE = [re.compile(r"\(오더번호[^)]*\)"), re.compile(r"\(\d[^)]*\)"),
         re.compile(r"\[[^\]]*\]"), re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"),
         re.compile(r"외\s*\d+\s*건"), re.compile(r"\d+")]


def norm_item(name: str) -> str:
    s = str(name or "")
    for pat in NOISE:
        s = pat.sub(" ", s)
    return re.sub(r"[\s\-_/,]+", " ", s).strip().lower()


# 그리드를 찾아 검증하고 전체 행을 읽어온다
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
        if (cn.includes(MARK)) { window.__wehagoGrid = v; return JSON.stringify(readAll(v, path)); }
      }
      if (d < 9) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, visited: visited });

  function readAll(g, path) {
    let src = g;
    try { const dp = g.getDataSource(); if (dp) { src = dp; window.__wehagoDP = dp; } } catch (e) {}
    let count = 0, rows = [];
    try {
      count = typeof src.getRowCount === 'function' ? src.getRowCount() : 0;
      if (count > 0) rows = src.getJsonRows(0, count - 1) || [];
    } catch (e) { return { ok: false, reason: String(e).slice(0, 200) }; }
    const methods = [];
    for (const m of ['setValue', 'setValues', 'commit', 'updateRow']) {
      try { if (typeof g[m] === 'function') methods.push('grid.' + m); } catch (e) {}
      try { if (src !== g && typeof src[m] === 'function') methods.push('dp.' + m); } catch (e) {}
    }
    return { ok: true, path: path, rowCount: count, rows: rows, methods: methods };
  }
}""".replace("%MARK%", TOP_MARK)

# 한 줄에 값을 쓴다. 위하고 자신의 setValue 를 먼저 쓰고 안 되면 데이터원본을 쓴다.
WRITE = r"""(args) => {
  const { row, expect, sets } = args;
  const g = window.__wehagoGrid, dp = window.__wehagoDP;
  const log = [];
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 참조가 사라졌습니다' });

  const readRow = () => {
    try {
      const src = dp || g;
      const r = src.getJsonRows(row, row);
      return (r && r[0]) ? r[0] : null;
    } catch (e) { return null; }
  };

  // 대조: 엉뚱한 줄을 건드리지 않는다
  const before = readRow();
  if (!before) return JSON.stringify({ ok: false, reason: '그 줄을 읽지 못했습니다' });
  for (const k of Object.keys(expect)) {
    if (String(before[k] === undefined ? '' : before[k]) !== String(expect[k] === undefined ? '' : expect[k])) {
      return JSON.stringify({ ok: false, reason: `대조 실패: ${k} 가 예상과 다릅니다`, before: before });
    }
  }

  const original = {};
  for (const f of Object.keys(sets)) original[f] = before[f] === undefined ? null : before[f];

  // 위하고 자신의 setValue 를 먼저 시도한다.
  // 데이터만 직접 바꾸면 위하고가 변경을 인식하지 못할 수 있다.
  for (const f of Object.keys(sets)) {
    let done = false;
    for (const [label, obj] of [['grid', g], ['dp', dp]]) {
      if (!obj || done) continue;
      try {
        if (typeof obj.setValue === 'function') {
          obj.setValue(row, f, sets[f]);
          log.push(`${label}.setValue(${row}, ${f}) 호출됨`);
          done = true;
        }
      } catch (e) { log.push(`${label}.setValue(${f}) 오류: ${String(e).slice(0, 120)}`); }
    }
    if (!done) log.push(`${f}: 쓸 방법이 없습니다`);
  }
  for (const [label, obj] of [['grid', g], ['dp', dp]]) {
    try { if (obj && typeof obj.commit === 'function') { obj.commit(); log.push(`${label}.commit() 호출됨`); } }
    catch (e) { log.push(`${label}.commit() 오류: ${String(e).slice(0, 120)}`); }
  }
  try { if (typeof g.refresh === 'function') g.refresh(); } catch (e) {}

  return JSON.stringify({ ok: true, log: log, original: original, after: readRow() });
}"""

RESTORE = r"""(args) => {
  const { row, original } = args;
  const g = window.__wehagoGrid, dp = window.__wehagoDP;
  const log = [];
  for (const f of Object.keys(original)) {
    for (const [label, obj] of [['grid', g], ['dp', dp]]) {
      if (!obj) continue;
      try { if (typeof obj.setValue === 'function') { obj.setValue(row, f, original[f]); log.push(`${label}.setValue(${f}) 되돌림`); break; } }
      catch (e) { log.push(`${label} 오류: ${String(e).slice(0, 100)}`); }
    }
  }
  for (const obj of [g, dp]) { try { if (obj && obj.commit) obj.commit(); } catch (e) {} }
  try { if (g && g.refresh) g.refresh(); } catch (e) {}
  return JSON.stringify({ log: log });
}"""


def learn(rows):
    by_biz = collections.defaultdict(collections.Counter)
    by_item = collections.defaultdict(collections.Counter)
    for r in rows:
        if not r.get("nm_acctit_cha"):
            continue
        pair = f"{r.get('cd_acctit_cha')}|{r.get('nm_acctit_cha')}|{r.get('cd_acctit_dae')}|{r.get('nm_acctit_dae')}"
        if r.get("no_bisocial"):
            by_biz[str(r["no_bisocial"])][pair] += 1
        key = norm_item(r.get("nm_good"))
        if key:
            by_item[key][pair] += 1
    return by_biz, by_item


print()
print("=" * 62)
print("  쓰기 시험 - 딱 한 건")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  전송(F3)은 이 프로그램이 절대 누르지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            print("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit

        data = json.loads(target.evaluate(GRAB))
        if not data.get("ok"):
            print(f"\n  전표 목록을 잡지 못했습니다. ({data.get('reason', '못찾음')})")
            print("  전표 목록에서 줄을 클릭하신 뒤 다시 실행해주세요.")
            raise SystemExit

        rows = data["rows"]
        print(f"\n  그리드 확인됨 / 행 {len(rows)}개")
        print(f"  쓰기 가능 메서드: {', '.join(data['methods']) or '없음'}")

        by_biz, by_item = learn([r for r in rows if str(r.get("ty_jungstat")) != STATUS_미추천])

        # 미추천 중 사업자번호 규칙으로 확신할 수 있는 첫 건을 고른다
        pick = None
        for i, r in enumerate(rows):
            if str(r.get("ty_jungstat")) != STATUS_미추천:
                continue
            hist = by_biz.get(str(r.get("no_bisocial") or ""))
            if not hist:
                continue
            pair, n = hist.most_common(1)[0]
            if n / sum(hist.values()) < 1.0:      # 이력이 갈리는 거래처는 시험 대상에서 제외
                continue
            cd_cha, nm_cha, cd_dae, nm_dae = pair.split("|")
            pick = (i, r, cd_cha, nm_cha, n)
            break

        if pick is None:
            print("\n  시험에 쓸 만한 미추천 건이 없습니다.")
            raise SystemExit

        i, r, cd_cha, nm_cha, n = pick
        print()
        print("  " + "-" * 56)
        print(f"   대상: {len(rows)}행 중 {i}번째 줄")
        print(f"   거래처 : {r.get('nm_trade')}")
        print(f"   품명   : {r.get('nm_good')}")
        print(f"   공급가액: {r.get('mn_mnam')}")
        print(f"   현재 차변계정: {r.get('nm_acctit_cha') or '(비어있음)'}")
        print()
        print(f"   넣을 값: cd_acctit_cha = {cd_cha}")
        print(f"            nm_acctit_cha = {nm_cha}")
        print(f"   근거: 같은 사업자번호 과거 {n}건이 모두 이 계정")
        print("  " + "-" * 56)
        print()
        if input("  이 한 건에만 써볼까요? (y = 진행) >>> ").strip().lower() != "y":
            print("  아무것도 하지 않았습니다.")
            raise SystemExit

        res = json.loads(target.evaluate(WRITE, {
            "row": i,
            "expect": {"nm_trade": r.get("nm_trade"), "mn_mnam": r.get("mn_mnam")},
            "sets": {"cd_acctit_cha": cd_cha, "nm_acctit_cha": nm_cha},
        }))
        if not res.get("ok"):
            print(f"\n  쓰지 못했습니다: {res.get('reason')}")
            raise SystemExit

        for line in res["log"]:
            print(f"    {line}")
        after = res.get("after") or {}
        print()
        print("  쓴 뒤 그 줄의 값:")
        for f in ("cd_acctit_cha", "nm_acctit_cha", "ty_jungstat"):
            print(f"    {f} = {after.get(f)}")

        print()
        print("  " + "=" * 56)
        print("   [꼭 확인] 위하고 화면을 봐주세요.")
        print("     1. 그 줄의 차변계정에 값이 보이나요?")
        print("     2. 전표상태가 '미추천' 에서 바뀌었나요?")
        print()
        print("   2번이 핵심입니다. 값만 보이고 상태가 그대로면")
        print("   위하고가 이 변경을 자기 것으로 인정하지 않은 것이라")
        print("   전송해도 반영되지 않습니다.")
        print("  " + "=" * 56)
        print()

        if input("  원래대로 되돌릴까요? (y = 되돌리기, 그냥 Enter = 그대로 두기) >>> ").strip().lower() == "y":
            back = json.loads(target.evaluate(RESTORE, {"row": i, "original": res["original"]}))
            for line in back["log"]:
                print(f"    {line}")
            print("  되돌렸습니다.")
        else:
            print("  그대로 두었습니다. 화면에서 직접 지우실 수 있습니다.")

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
