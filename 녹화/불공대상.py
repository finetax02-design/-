"""불공으로 바꿔야 할 건을 목록으로 뽑는다. 화면은 건드리지 않는다.

불공제 사유 라디오를 프로그램으로 누르는 것은 여섯 번 시도해 모두 실패했다.
실제 마우스에만 반응하는 부품으로 보인다.

그래서 판정은 프로그램이 하고 화면 조작은 사람이 하는 쪽으로 간다.
규칙표에 따라 어느 줄을 어떤 사유로 바꿔야 하는지 목록으로 준다.
화면에 보이는 순서대로 정렬해두어 위에서 아래로 훑으며 처리하면 된다.

읽기만 한다. 값을 바꾸지 않는다.
"""
import collections
import csv
import json
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"

과세 = "51"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

GRAB = r"""() => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
  while (queue.length && visited < 60000) {
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
        let names = [];
        try { names = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (names.includes('nm_acctit_cha')) {
          let src = v;
          try { const dp = v.getDataSource(); if (dp) src = dp; } catch (e) {}
          try { const n = src.getRowCount();
                return JSON.stringify({ ok: true, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] }); }
          catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 120) }); }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

print()
print("=" * 74)
print("  불공 전환 대상 목록 (읽기 전용)")
print("=" * 74)
print()
if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    print("  24_불공규칙.bat 을 먼저 실행해주세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = (r.get("사유코드") or "").strip()
        if r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y") and code in 사유이름:
            rules[r["사업자번호"].strip()] = code

print(f"  규칙표: 불공 적용 거래처 {len(rules)}곳")
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 진행하세요.")
print("  값을 바꾸지 않습니다.")
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
        page.bring_to_front()

        data = json.loads(page.evaluate(GRAB))
        if not data.get("ok"):
            print(f"\n  {data.get('reason')}")
            raise SystemExit
        rows = data["rows"]
        if not rows:
            print("\n  화면에 자료가 없습니다. 조회를 먼저 해주세요.")
            raise SystemExit

        targets = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            code = rules.get(str(r.get("no_bisocial") or ""))
            if code:
                targets.append({
                    "화면순서": i + 1,
                    "일자": r.get("s_date"),
                    "거래처": r.get("nm_trade"),
                    "품명": r.get("nm_good"),
                    "공급가액": r.get("mn_mnam"),
                    "바꿀사유": code,
                    "사유이름": 사유이름[code],
                })

        print(f"\n  전표 {len(rows)}건 / 불공으로 바꿀 건 {len(targets)}건")
        if not targets:
            print("  바꿀 건이 없습니다.")
            raise SystemExit

        by_code = collections.Counter(t["바꿀사유"] for t in targets)
        print("  사유별: " + ", ".join(f"{k} {사유이름[k]} {v}건" for k, v in sorted(by_code.items())))
        print()
        print(f"  {'순서':>5}  {'일자':<7}{'거래처':<22}{'품명':<28}{'금액':>13}  사유")
        print("  " + "-" * 88)
        for t in targets:
            amt = f"{int(t['공급가액']):,}" if str(t["공급가액"] or "").lstrip("-").isdigit() else str(t["공급가액"])
            print(f"  {t['화면순서']:>5}  {str(t['일자'] or ''):<7}{str(t['거래처'])[:20]:<22}"
                  f"{str(t['품명'])[:26]:<28}{amt:>13}  {t['바꿀사유']} {t['사유이름']}")

        out = HERE / f"불공대상_{datetime.now():%Y%m%d_%H%M}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(targets[0].keys()))
            w.writeheader()
            w.writerows(targets)
        print()
        print(f"  저장: {out}")
        print()
        print("  화면에 보이는 순서대로 정렬돼 있습니다.")
        print("  위에서 아래로 훑으며 유형을 불공으로 바꾸고 사유를 고르시면 됩니다.")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 74)
print("  아무것도 바꾸지 않았습니다.")
print("=" * 74)
print()
input("  창을 닫으려면 Enter >>> ")
