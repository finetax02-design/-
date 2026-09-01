"""미추천 전표의 차변과 대변 계정과목을 채워 전표상태를 풀어준다.

앞선 시험에서 차변만 채웠더니 전표상태가 미추천 그대로였다.
위하고 코드가 차변과 대변을 둘 다 확인하기 때문이다.

  (cd_acctit_cha 가 비었거나 cd_acctit_dae 가 비었으면)
      ty_jungstat 을 5(미추천)로 되돌린다

그래서 양쪽을 다 채운다.

계정 결정
  차변  1 같은 사업자번호의 과거 차변  2 같은 품명의 과거 차변
  대변  1 같은 사업자번호의 과거 대변  2 같은 품명의 과거 대변  3 기본값

대변 기본값을 외상매입금으로 두되, 고객사에 따라 미지급금이 맞는 곳도 있어
과거 이력을 먼저 본다. 3번으로 떨어진 건은 결과에 표시한다.

쓰기는 RealGrid 편집기를 실제로 여는 방식이다.
위하고의 onCellEdited -> filterStoreData 가 평소 순서대로 돈다.

전송(F3)은 절대 부르지 않는다.
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
STATUS_미추천 = "5"
TOP_MARK = "nm_acctit_cha"
DEFAULT_DAE = "외상매입금"      # 이력이 없을 때 쓸 대변 기본값

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
          try {
            const src = window.__dp || v;
            const count = src.getRowCount();
            return JSON.stringify({ ok: true, rowCount: count,
                                    rows: src.getJsonRows(0, count - 1) || [] });
          } catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 200) }); }
        }
      }
      if (d < 9) queue.push({ o: v, path: path + '.' + k, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}""".replace("%MARK%", TOP_MARK)

# 한 줄의 차변과 대변을 편집기로 채운다
FILL = r"""(args) => {
  const { row, cha, dae, expect } = args;
  const g = window.__g, dp = window.__dp;
  const log = [];
  const read = () => { try { return (dp || g).getJsonRows(row, row)[0] || null; } catch (e) { return null; } };

  const before = read();
  if (!before) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  // 엉뚱한 줄을 건드리지 않도록 대조한다
  for (const k of Object.keys(expect)) {
    if (String(before[k] ?? '') !== String(expect[k] ?? '')) {
      return JSON.stringify({ ok: false, reason: `대조 실패: ${k}`, before: before });
    }
  }

  const write = (field, value) => {
    if (!value) return;
    try {
      g.setCurrent({ itemIndex: row, dataRow: row, column: field, fieldName: field });
      g.showEditor();
      g.setEditValue(value, false, false);
      g.commitEditor(true);
      log.push(`${field} = ${value}`);
    } catch (e) { log.push(`${field} 오류: ${String(e).slice(0, 140)}`); }
  };

  if (!before.cd_acctit_cha) write('nm_acctit_cha', cha);
  if (!before.cd_acctit_dae) write('nm_acctit_dae', dae);
  try { if (g.commit) g.commit(); } catch (e) {}

  return JSON.stringify({ ok: true, log: log, before: before, after: read() });
}"""

RESTORE = r"""(args) => {
  const g = window.__g;
  const log = [];
  for (const item of args.items) {
    for (const f of Object.keys(item.original)) {
      try { g.setValue(item.row, f, item.original[f]); } catch (e) { log.push(`${item.row}.${f} 오류`); }
    }
    log.push(`${item.row}번째 줄 되돌림`);
  }
  try { if (g.commit) g.commit(); } catch (e) {}
  return JSON.stringify({ log: log });
}"""

KEEP = ["nm_acctit_cha", "cd_acctit_cha", "nm_acctit_dae", "cd_acctit_dae", "ty_jungstat"]


def learn(rows, field):
    by_biz = collections.defaultdict(collections.Counter)
    by_item = collections.defaultdict(collections.Counter)
    for r in rows:
        v = r.get(field)
        if not v:
            continue
        if r.get("no_bisocial"):
            by_biz[str(r["no_bisocial"])][v] += 1
        key = norm_item(r.get("nm_good"))
        if key:
            by_item[key][v] += 1
    return by_biz, by_item


def guess(row, by_biz, by_item, fallback=None):
    for src, layer in ((by_biz.get(str(row.get("no_bisocial") or "")), "거래처"),
                       (by_item.get(norm_item(row.get("nm_good"))), "품명")):
        if src:
            v, n = src.most_common(1)[0]
            return v, layer, n / sum(src.values())
    return (fallback, "기본값", 0.0) if fallback else (None, "없음", 0.0)


print()
print("=" * 62)
print("  미추천 전표 자동분개 (차변 + 대변)")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  전송(F3)은 절대 부르지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

done: list[dict] = []
page = None
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
        learned = [r for r in rows if str(r.get("ty_jungstat")) != STATUS_미추천]
        cha_biz, cha_item = learn(learned, "nm_acctit_cha")
        dae_biz, dae_item = learn(learned, "nm_acctit_dae")

        targets = [(i, r) for i, r in enumerate(rows)
                   if str(r.get("ty_jungstat")) == STATUS_미추천]
        print(f"\n  전체 {len(rows)}건 / 학습 {len(learned)}건 / 미추천 {len(targets)}건")

        plan = []
        for i, r in targets:
            cha, cha_by, _ = guess(r, cha_biz, cha_item)
            dae, dae_by, _ = guess(r, dae_biz, dae_item, fallback=DEFAULT_DAE)
            if not cha:
                continue        # 차변을 모르면 손대지 않는다
            plan.append({"row": i, "rec": r, "cha": cha, "cha_by": cha_by,
                         "dae": dae, "dae_by": dae_by})

        skipped = len(targets) - len(plan)
        by_dae = collections.Counter(p["dae_by"] for p in plan)
        print(f"  처리 가능 {len(plan)}건 / 차변 판단 불가로 건너뜀 {skipped}건")
        print(f"  대변 결정 근거: " + ", ".join(f"{k} {v}건" for k, v in by_dae.items()))
        if not plan:
            print("\n  처리할 건이 없습니다.")
            raise SystemExit

        def run_one(item):
            r = item["rec"]
            res = json.loads(page.evaluate(FILL, {
                "row": item["row"], "cha": item["cha"], "dae": item["dae"],
                "expect": {"nm_trade": r.get("nm_trade"), "mn_mnam": r.get("mn_mnam")},
            }))
            if not res.get("ok"):
                print(f"    실패: {res.get('reason')}")
                return None
            after = res.get("after") or {}
            ok = str(after.get("ty_jungstat")) != STATUS_미추천
            done.append({"row": item["row"],
                         "original": {f: r.get(f) for f in KEEP}})
            return ok, after, res["log"]

        # 먼저 한 건만
        first = plan[0]
        r = first["rec"]
        print()
        print("  " + "-" * 56)
        print(f"   먼저 한 건만 해봅니다 ({first['row']}번째 줄)")
        print(f"   거래처 : {r.get('nm_trade')}")
        print(f"   품명   : {r.get('nm_good')}")
        print(f"   차변 → {first['cha']}  ({first['cha_by']} 기준)")
        print(f"   대변 → {first['dae']}  ({first['dae_by']} 기준)")
        print("  " + "-" * 56)
        print()
        if input("  진행할까요? (y) >>> ").strip().lower() != "y":
            raise SystemExit

        out = run_one(first)
        if out is None:
            raise SystemExit
        ok, after, log = out
        for line in log:
            print(f"    {line}")
        print()
        for f in KEEP:
            print(f"    {f} = {after.get(f)}")
        print(f"\n  → 전표상태 {'바뀜! 성공' if ok else '미추천 그대로'}")
        print()
        print("  화면에서 확인해주세요:")
        print("    차변/대변 계정, 계정코드, 전표상태, 아래쪽 분개 줄")
        print()

        if not ok:
            print("  전표상태가 안 바뀌었으니 나머지는 진행하지 않습니다.")
        elif len(plan) > 1:
            if input(f"  나머지 {len(plan) - 1}건도 진행할까요? (y) >>> ").strip().lower() == "y":
                good = 1
                for item in plan[1:]:
                    out = run_one(item)
                    if out is None:
                        print(f"    {item['row']}번째 줄에서 멈춥니다.")
                        break
                    ok2, after2, _ = out
                    good += 1 if ok2 else 0
                    mark = "O" if ok2 else "X"
                    print(f"    [{mark}] {item['row']:4d}번째  {str(item['rec'].get('nm_trade'))[:18]:<20}"
                          f" 차변={item['cha']}  대변={item['dae']}")
                print(f"\n  전표상태가 풀린 건: {good} / {len(plan)}")

        if done:
            out_csv = HERE / "처리내역.csv"
            with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["줄번호"] + KEEP)
                for d in done:
                    w.writerow([d["row"]] + [d["original"].get(k) for k in KEEP])
            print(f"\n  되돌리기용 원래값 저장: {out_csv}")
            print()
            if input("  전부 되돌릴까요? (y = 되돌리기) >>> ").strip().lower() == "y":
                back = json.loads(page.evaluate(RESTORE, {"items": done}))
                print(f"    {len(back['log'])}건 되돌렸습니다.")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 62)
print("  전송(F3)은 누르지 않았습니다.")
print("  화면에서 확인하시고 직접 전송하세요.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
