"""미추천 전표에 넣을 계정과목을 제안한다. 쓰지는 않는다.

화면에 이미 학습 데이터와 예측 대상이 함께 있다.
  전표확정 + 확정가능 = 계정과목이 채워진 건  -> 여기서 규칙을 배운다
  미추천                                    -> 여기에 제안한다
따로 파일을 내려받을 필요가 없다.

규칙은 두 단계다.
  L1 사업자등록번호 -> 계정과목   거래 이력이 있는 거래처
  L2 품명 정규화   -> 계정과목   신규 거래처인데 품명이 익숙한 경우

안전장치
  잡은 그리드가 전표 목록이 맞는지 컬럼으로 검증하고, 아니면 아무것도 안 한다.
  이 스크립트는 읽기만 한다. setValue 를 부르지 않는다.
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

# 코드표 (화면 글자에서 확인한 값)
STATUS_미추천 = "5"
STATUS_확정가능 = "1"
STATUS_전표확정 = "2"

TOP_MARK = "nm_acctit_cha"          # 전표 목록임을 확인하는 표식
NEED = ["no_bisocial", "nm_trade", "nm_good", "ty_jungstat",
        "cd_acctit_cha", "nm_acctit_cha", "ty_mth2", "cd_notdedct", "mn_mnam"]

# 품명에서 건마다 달라지는 부분(오더번호, 날짜, 수량)을 지운다
NOISE = [re.compile(r"\(오더번호[^)]*\)"), re.compile(r"\(\d[^)]*\)"),
         re.compile(r"\[[^\]]*\]"), re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"),
         re.compile(r"외\s*\d+\s*건"), re.compile(r"\d+")]


def norm_item(name: str) -> str:
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
  let visited = 0, hit = null, hitPath = '';

  while (queue.length && visited < 60000 && !hit) {
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
      const p = path + '.' + k;
      if (gridish(v)) {
        let cn = [];
        try { cn = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cn.includes(MARK)) { hit = v; hitPath = p; break; }
      }
      if (d < 9) queue.push({ o: v, path: p, d: d + 1 });
    }
  }
  if (!hit) return JSON.stringify({ ok: false, visited: visited });

  // 검증: 전표 목록이 맞는지 다시 확인한다
  let cols = [];
  try { cols = hit.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
  if (!cols.includes(MARK)) return JSON.stringify({ ok: false, reason: '검증실패' });

  let src = hit, count = 0, rows = [];
  try { const dp = hit.getDataSource(); if (dp) src = dp; } catch (e) {}
  try {
    count = typeof src.getRowCount === 'function' ? src.getRowCount() : 0;
    if (count > 0) rows = src.getJsonRows(0, count - 1) || [];
  } catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 200) }); }

  return JSON.stringify({ ok: true, path: hitPath, colCount: cols.length,
                          rowCount: count, rows: rows, visited: visited });
}""".replace("%MARK%", TOP_MARK)


def learn(rows: list[dict]) -> tuple[dict, dict]:
    """계정과목이 채워진 건에서 두 단계 규칙을 배운다."""
    by_biz = collections.defaultdict(collections.Counter)
    by_item = collections.defaultdict(collections.Counter)
    for r in rows:
        acct = r.get("nm_acctit_cha")
        code = r.get("cd_acctit_cha")
        if not acct:
            continue
        pair = f"{code}|{acct}"
        biz = str(r.get("no_bisocial") or "")
        if biz:
            by_biz[biz][pair] += 1
        key = norm_item(r.get("nm_good"))
        if key:
            by_item[key][pair] += 1
    return by_biz, by_item


def predict(row: dict, by_biz: dict, by_item: dict) -> tuple[str, str, str, float]:
    """(계정코드, 계정명, 사용한 단계, 확신도) 를 돌려준다."""
    for source, layer in ((by_biz.get(str(row.get("no_bisocial") or "")), "L1"),
                          (by_item.get(norm_item(row.get("nm_good"))), "L2")):
        if source:
            pair, n = source.most_common(1)[0]
            code, _, name = pair.partition("|")
            return code, name, layer, n / sum(source.values())
    return "", "", "L3", 0.0


print()
print("=" * 62)
print("  미추천 전표 계정과목 제안 (쓰기 없음)")
print("=" * 62)
print()
print("  [중요] 전표 목록(위쪽)에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print()
print("  이 스크립트는 값을 쓰지 않습니다. 제안만 만듭니다.")
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
            print(f"\n  전표 목록 그리드를 잡지 못했습니다. ({data.get('reason', '못찾음')})")
            print("  전표 목록에서 줄을 한 번 클릭하신 뒤 다시 실행해주세요.")
            raise SystemExit

        rows = data["rows"]
        print(f"\n  그리드 확인됨 (컬럼 {data['colCount']}개) / 행 {len(rows)}개")
        print(f"  경로: {data['path'][:70]}")

        by_status = collections.Counter(str(r.get("ty_jungstat")) for r in rows)
        print(f"\n  전표상태: 미추천 {by_status[STATUS_미추천]}건 / "
              f"확정가능 {by_status[STATUS_확정가능]}건 / 전표확정 {by_status[STATUS_전표확정]}건")

        learn_rows = [r for r in rows if str(r.get("ty_jungstat")) != STATUS_미추천]
        target_rows = [r for r in rows if str(r.get("ty_jungstat")) == STATUS_미추천]
        by_biz, by_item = learn(learn_rows)
        print(f"  학습: {len(learn_rows)}건에서 거래처 {len(by_biz)}곳, 품명 {len(by_item)}종")

        if not target_rows:
            print("\n  미추천 건이 없습니다. 제안할 것이 없습니다.")
            raise SystemExit

        results = []
        tally = collections.Counter()
        for r in target_rows:
            code, name, layer, conf = predict(r, by_biz, by_item)
            tally[layer] += 1
            results.append({
                "거래처": r.get("nm_trade"), "사업자번호": r.get("no_bisocial"),
                "품명": r.get("nm_good"), "공급가액": r.get("mn_mnam"),
                "제안_계정코드": code, "제안_계정명": name,
                "단계": layer, "확신도": f"{conf:.2f}",
            })

        n = len(target_rows)
        print(f"\n  미추천 {n}건 제안 결과")
        print(f"    L1 사업자번호 규칙 : {tally['L1']:3d}건 ({tally['L1'] / n * 100:5.1f}%)")
        print(f"    L2 품명 규칙       : {tally['L2']:3d}건 ({tally['L2'] / n * 100:5.1f}%)")
        print(f"    L3 판단 못함       : {tally['L3']:3d}건 ({tally['L3'] / n * 100:5.1f}%)")

        out = HERE / "제안.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
        print(f"\n  저장: {out}")
        print("  이 파일을 열어서 제안이 맞는지 눈으로 확인해주세요.")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 62)
print("  값은 하나도 바꾸지 않았습니다.")
print("  제안.csv 에는 실제 거래처명이 있으니 보내지 마시고,")
print("  위에 표시된 건수와 비율만 알려주세요.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
