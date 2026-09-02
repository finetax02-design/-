"""공제 불공제 판정을 과거 이력에서 분석하고 제안한다. 쓰지는 않는다.

계정과목과 달리 이쪽은 틀리면 부가세 신고가 틀어진다.
그래서 이 단계에서는 아무것도 쓰지 않는다. 무엇을 어떻게 바꿔야 하는지
근거와 함께 제시하고, 판단이 갈리는 곳을 드러내는 것까지만 한다.

하는 일
  1 거래처별로 과세와 불공이 어떻게 갈리는지 집계한다
     항상 과세 / 항상 불공 / 혼재 로 나눈다
  2 혼재 거래처는 언제 무엇이 갈렸는지 건별로 보여준다
     예전에 확인하지 못한 건들이 여기서 드러난다
  3 아직 과세인 건 중 이력이 불공으로 일치하는 것을 제안한다
  4 불공제 사유코드가 어떻게 쓰였는지 정리한다
  5 ty_mth2 칸이 어떤 편집기인지 확인한다 (나중에 쓰기를 만들 때 필요)

전송(F3)은 부르지 않는다. 값을 바꾸지 않는다.
"""
import collections
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent

과세 = "51"
불공 = "54"

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
        let cols = [];
        try { cols = v.getColumns(); } catch (e) {}
        const names = cols.map(c => String(c.name || c.fieldName || ''));
        if (names.includes('nm_acctit_cha')) {
          let src = v;
          try { const dp = v.getDataSource(); if (dp) src = dp; } catch (e) {}
          let rows = [], n = 0;
          try { n = src.getRowCount(); rows = n ? (src.getJsonRows(0, n - 1) || []) : []; }
          catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 150) }); }

          // 나중에 쓰기를 만들 때 필요한 정보
          const info = {};
          for (const f of ['ty_mth2', 'cd_notdedct', 'ty_mth', 'ty_trade']) {
            const c = cols.find(x => String(x.name || x.fieldName) === f);
            info[f] = c ? { editable: c.editable, readOnly: c.readOnly, visible: c.visible,
                            editor: c.editor, editorOptions: c.editorOptions,
                            values: c.values, labels: c.labels, button: c.button } : null;
          }
          return JSON.stringify({ ok: true, rows: rows, colInfo: info });
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""


def label(v):
    return {과세: "과세", 불공: "불공"}.get(str(v), f"기타({v})")


print()
print("=" * 66)
print("  공제 / 불공제 판정 분석 (읽기 전용)")
print("=" * 66)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
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
        print(f"\n  전표 {len(rows)}건")

        print("\n  [ty_mth2 / cd_notdedct 칸 정보 — 나중에 쓰기 만들 때 씁니다]")
        for f, info in data["colInfo"].items():
            print(f"    {f}: {json.dumps(info, ensure_ascii=False)[:200]}")

        # 1. 전체 분포
        print("\n" + "=" * 66)
        print("  1. 전체 분포")
        print("=" * 66)
        dist = collections.Counter(str(r.get("ty_mth2")) for r in rows)
        for k, n in dist.most_common():
            print(f"    {label(k):<8} {n:5d}건 ({n / len(rows) * 100:5.1f}%)")
        nd = collections.Counter(str(r.get("cd_notdedct") or "(없음)") for r in rows)
        print("\n    불공제 사유코드:")
        for k, n in nd.most_common():
            print(f"      {k:<10} {n:5d}건")

        # 2. 거래처별로 갈리는지
        by_biz = collections.defaultdict(list)
        for r in rows:
            biz = str(r.get("no_bisocial") or "")
            if biz:
                by_biz[biz].append(r)

        always_tax, always_no, mixed = [], [], []
        for biz, rs in by_biz.items():
            kinds = set(str(x.get("ty_mth2")) for x in rs)
            if kinds == {과세}:
                always_tax.append((biz, rs))
            elif kinds == {불공}:
                always_no.append((biz, rs))
            else:
                mixed.append((biz, rs))

        print("\n" + "=" * 66)
        print("  2. 거래처별 일관성")
        print("=" * 66)
        print(f"    거래처 {len(by_biz)}곳")
        print(f"      항상 과세 {len(always_tax):4d}곳 / {sum(len(r) for _, r in always_tax):5d}건")
        print(f"      항상 불공 {len(always_no):4d}곳 / {sum(len(r) for _, r in always_no):5d}건")
        print(f"      혼재     {len(mixed):4d}곳 / {sum(len(r) for _, r in mixed):5d}건  ← 확인 필요")

        # 3. 혼재 거래처 상세
        if mixed:
            print("\n" + "=" * 66)
            print("  3. 판정이 갈리는 거래처 — 여기가 확인 대상입니다")
            print("=" * 66)
            for biz, rs in sorted(mixed, key=lambda x: -len(x[1]))[:12]:
                name = rs[0].get("nm_trade")
                c = collections.Counter(str(x.get("ty_mth2")) for x in rs)
                print(f"\n    {name} ({biz})  과세{c.get(과세,0)} / 불공{c.get(불공,0)}")
                for x in sorted(rs, key=lambda y: str(y.get("s_date") or "")):
                    print(f"      {str(x.get('s_date')):<8} {label(x.get('ty_mth2')):<5}"
                          f" 사유={str(x.get('cd_notdedct') or '-'):<4}"
                          f" {str(x.get('nm_good'))[:34]:<36} {x.get('mn_mnam')}")

        # 4. 아직 과세인 건 중 이력이 불공으로 일치하는 것
        print("\n" + "=" * 66)
        print("  4. 불공 전환 제안")
        print("=" * 66)
        no_biz = {biz for biz, _ in always_no}
        reason_of = {}
        for biz, rs in always_no:
            codes = collections.Counter(str(x.get("cd_notdedct") or "") for x in rs if x.get("cd_notdedct"))
            reason_of[biz] = codes.most_common(1)[0][0] if codes else ""

        proposals = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            biz = str(r.get("no_bisocial") or "")
            if biz in no_biz:
                proposals.append({"줄번호": i, "거래처": r.get("nm_trade"), "사업자번호": biz,
                                  "품명": r.get("nm_good"), "공급가액": r.get("mn_mnam"),
                                  "현재": "과세", "제안": "불공",
                                  "제안사유코드": reason_of.get(biz, ""),
                                  "근거": f"이 거래처 과거 {len(dict(always_no)[biz])}건 모두 불공"})
        print(f"    이력이 전부 불공인 거래처의 과세 건: {len(proposals)}건")
        for x in proposals[:20]:
            print(f"      {x['줄번호']:4d}행 {str(x['거래처'])[:20]:<22}"
                  f" {str(x['품명'])[:26]:<28} 사유={x['제안사유코드']}")

        if proposals:
            out = HERE / "불공전환제안.csv"
            with out.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(proposals[0].keys()))
                w.writeheader()
                w.writerows(proposals)
            print(f"\n    저장: {out}")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 66)
print("  아무것도 바꾸지 않았습니다.")
print("  3번의 갈리는 건들과 4번 제안을 먼저 확인해주세요.")
print("=" * 66)
print()
input("  창을 닫으려면 Enter >>> ")
