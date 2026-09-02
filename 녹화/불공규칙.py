"""거래처별 불공제 규칙표를 과거 이력에서 뽑는다. 값은 쓰지 않는다.

세법 판단은 사람이 하고 실행만 자동화한다는 구조를 위해,
먼저 거래처별로 '이 거래처는 불공인가, 사유는 무엇인가' 를 표로 만든다.
그 표를 검토하고 확정하면 다음 단계에서 그 표대로만 실행한다.

혼재 거래처를 제안에서 빼면 안 된다는 것을 확인했다.
한승메디칼이 1~3월 과세 4~6월 불공이었던 이유는 판단이 갈려서가 아니라
1~3월에는 화면에서 과세로 전송한 뒤 신고 전에 수기로 불공으로 바꿨고,
4월부터는 화면에서 불공 안분을 체크해 전송했기 때문이다.
판단은 처음부터 일관되게 불공이었고 처리 시점만 달랐다.
오히려 이런 거래처가 자동화의 핵심 대상이다.

자동화 대상 사유코드는 셋이다.
  3 비영업용승용차유지   4 면세사업관련   5 공통매입세액안분

전송(F3)은 부르지 않는다.
"""
import collections
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"

과세 = "51"
불공 = "54"

# 자동화 대상 사유코드
사유 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}
대상코드 = set(사유)

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
          try {
            const n = src.getRowCount();
            return JSON.stringify({ ok: true, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] });
          } catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 150) }); }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

print()
print("=" * 70)
print("  거래처별 불공제 규칙표 만들기 (읽기 전용)")
print("=" * 70)
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

        by_biz = collections.defaultdict(list)
        for r in rows:
            biz = str(r.get("no_bisocial") or "")
            if biz:
                by_biz[biz].append(r)

        table = []
        for biz, rs in by_biz.items():
            kinds = collections.Counter(str(x.get("ty_mth2")) for x in rs)
            n_tax, n_no = kinds.get(과세, 0), kinds.get(불공, 0)
            codes = collections.Counter(str(x.get("cd_notdedct") or "").strip()
                                        for x in rs if str(x.get("cd_notdedct") or "").strip())
            code = codes.most_common(1)[0][0] if codes else ""

            if n_no and not n_tax:
                verdict, note = "불공", "과거 전부 불공"
            elif n_no and n_tax:
                # 앞선 기간에는 화면에서 과세로 보내고 나중에 수기로 고쳤을 수 있다.
                # 판단이 갈린 것이 아니라 처리 시점이 달랐던 경우다.
                verdict, note = "불공", f"혼재 (과세{n_tax}/불공{n_no}) — 확인 권장"
            else:
                verdict, note = "과세", "과거 전부 과세"

            table.append({
                "사업자번호": biz,
                "거래처명": rs[0].get("nm_trade"),
                "총건수": len(rs), "과세": n_tax, "불공": n_no,
                "판정": verdict,
                "사유코드": code if verdict == "불공" else "",
                "사유이름": 사유.get(code, "") if verdict == "불공" else "",
                "적용": "Y" if verdict == "불공" and code in 대상코드 else "N",
                "메모": note,
            })

        table.sort(key=lambda x: (x["판정"] != "불공", -x["불공"], -x["총건수"]))

        no_rows = [t for t in table if t["판정"] == "불공"]
        mixed = [t for t in no_rows if "혼재" in t["메모"]]
        need = [t for t in no_rows if t["적용"] == "N"]

        print()
        print("=" * 70)
        print("  거래처별 판정")
        print("=" * 70)
        print(f"    거래처 {len(table)}곳")
        print(f"      불공 판정 {len(no_rows):4d}곳   (그중 혼재 {len(mixed)}곳)")
        print(f"      과세 판정 {len(table) - len(no_rows):4d}곳")
        print(f"      사유코드가 3·4·5 가 아니라 적용 보류: {len(need)}곳")

        print()
        print(f"  {'거래처명':<26}{'과세':>5}{'불공':>5}  {'판정':<5}{'사유':<16}{'적용':<5}메모")
        print("  " + "-" * 84)
        for t in no_rows[:40]:
            sayu = f"{t['사유코드']} {t['사유이름']}".strip() or "(없음)"
            print(f"  {str(t['거래처명'])[:24]:<26}{t['과세']:>5}{t['불공']:>5}"
                  f"  {t['판정']:<5}{sayu:<16}{t['적용']:<5}{t['메모']}")

        if mixed:
            print()
            print("=" * 70)
            print("  혼재 거래처 — 앞 기간에 수기로 고치셨던 건들일 가능성")
            print("=" * 70)
            for t in mixed:
                print(f"\n    {t['거래처명']}  과세{t['과세']} / 불공{t['불공']}  "
                      f"사유 {t['사유코드']} {t['사유이름']}")
                for r in sorted(by_biz[t["사업자번호"]], key=lambda y: str(y.get("s_date") or "")):
                    mark = "과세" if str(r.get("ty_mth2")) == 과세 else "불공"
                    print(f"      {str(r.get('s_date')):<8} {mark}  사유={str(r.get('cd_notdedct') or '-'):<3}"
                          f" {str(r.get('nm_good'))[:30]:<32} {r.get('mn_mnam')}")

        with RULES.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
            w.writeheader()
            w.writerows(table)

        print()
        print("=" * 70)
        print("  규칙표를 저장했습니다")
        print("=" * 70)
        print(f"  {RULES}")
        print()
        print("  엑셀로 열어서 확인하고 고치시면 됩니다.")
        print("    적용    Y = 자동으로 불공 전환,  N = 손대지 않음")
        print("    사유코드  3 비영업용승용차유지 / 4 면세사업관련 / 5 공통매입세액안분")
        print()
        print("  메모에 '혼재' 라고 적힌 곳을 특히 봐주세요.")
        print("  앞 기간에 수기로 고치셨던 거래처일 수 있습니다.")
        print("  맞으면 적용을 Y 로 두시고, 아니면 N 으로 바꾸시면 됩니다.")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 70)
print("  아무것도 바꾸지 않았습니다.")
print("=" * 70)
print()
input("  창을 닫으려면 Enter >>> ")
