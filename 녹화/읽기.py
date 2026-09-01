"""위하고 전표 목록을 통째로 읽어 CSV 로 저장한다.

탐색 결과 RealGrid 객체에 도달하는 경로를 찾았다.
다만 window.Grids.CellIndex.$_temp._grid 는 '마지막에 건드린 그리드' 를
가리키는 임시 참조여서 그때그때 달라진다. 경로를 외워 쓰면 안 된다.

그래서 window 를 훑어 그리드 후보를 모두 모은 뒤,
컬럼 이름으로 어느 그리드인지 알아낸다.
  상단(전표 목록) : nm_acctit_cha 를 가진 그리드
  하단(분개)      : no_acctper1 을 가진 그리드

읽기만 한다. 값을 바꾸지 않는다.
CSV 는 이 폴더에만 저장되며 밖으로 나가지 않는다.
"""
import csv
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CDP = "http://localhost:9222"

# 어느 그리드인지 알아내는 표식 컬럼
TOP_MARK = "nm_acctit_cha"    # 차변계정 - 전표 목록에만 있다
DOWN_MARK = "no_acctper1"     # 추천율 - 분개 그리드에만 있다

FIND_AND_READ = r"""() => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };

  // window 에서 그리드 후보를 모은다
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

  // 컬럼 이름으로 어느 그리드인지 가린다
  const describe = g => {
    let names = [];
    try { names = g.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
    return names;
  };

  const result = { candidates: [], top: null, down: null, visited: visited };
  for (const f of found) {
    const names = describe(f.obj);
    if (!names.length) continue;
    const kind = names.includes('%TOP%') ? 'top'
               : names.includes('%DOWN%') ? 'down' : '';
    result.candidates.push({ path: f.path, cols: names.length, kind: kind });
    if (!kind) continue;

    let rows = [], count = 0;
    try {
      let src = f.obj;
      try { const dp = f.obj.getDataSource(); if (dp) src = dp; } catch (e) {}
      count = typeof src.getRowCount === 'function' ? src.getRowCount()
            : typeof src.getItemCount === 'function' ? src.getItemCount() : 0;
      if (count > 0 && typeof src.getJsonRows === 'function') {
        rows = src.getJsonRows(0, count - 1) || [];
      }
    } catch (e) {
      result[kind + 'Error'] = String(e).slice(0, 200);
    }
    const payload = { path: f.path, columns: names, rowCount: count, rows: rows };
    if (!result[kind] || rows.length > (result[kind].rows || []).length) result[kind] = payload;
  }
  return JSON.stringify(result);
}""".replace("%TOP%", TOP_MARK).replace("%DOWN%", DOWN_MARK)


def save_csv(name: str, rows: list[dict]) -> Path | None:
    if not rows:
        return None
    fields: list[str] = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    path = HERE / name
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def summarize(rows: list[dict]) -> None:
    """숫자만 세어 보여준다. 거래처명이나 금액은 출력하지 않는다."""
    def tally(field: str) -> dict:
        out: dict = {}
        for r in rows:
            v = r.get(field)
            key = "(빈값)" if v in (None, "") else str(v)
            out[key] = out.get(key, 0) + 1
        return out

    print(f"    전표상태(ty_jungstat): {tally('ty_jungstat')}")
    print(f"    유형(ty_mth)         : {tally('ty_mth')}")
    print(f"    불공제코드(cd_notdedct): {tally('cd_notdedct')}")
    blank = sum(1 for r in rows if not r.get("nm_acctit_cha"))
    print(f"    차변계정 비어있는 건   : {blank}건  ← 미추천 후보")


print()
print("=" * 62)
print("  위하고 전표 목록 읽기")
print("=" * 62)
print()
print("  전자세금계산서 화면에 자료가 보이는 상태여야 합니다.")
print("  값을 바꾸지 않고 읽기만 합니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    import json

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        target = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if target is None:
            print("smarta.wehago.com 탭을 찾지 못했습니다.")
            print("열린 탭: " + ", ".join(pg.url[:80] for pg in pages))
        else:
            data = json.loads(target.evaluate(FIND_AND_READ))
            print(f"\n  객체 {data['visited']}개 검사, 그리드 후보 {len(data['candidates'])}개")
            for c in data["candidates"]:
                mark = {"top": " ← 전표 목록", "down": " ← 분개"}.get(c["kind"], "")
                print(f"    컬럼{c['cols']:3d}  {c['path'][:70]}{mark}")

            for kind, label, fname in (("top", "전표 목록", "전표목록.csv"),
                                       ("down", "분개", "분개.csv")):
                g = data.get(kind)
                print()
                if not g:
                    print(f"  [{label}] 못 찾았습니다.")
                    if data.get(kind + "Error"):
                        print(f"    오류: {data[kind + 'Error']}")
                    continue
                print(f"  [{label}] {g['path'][:70]}")
                print(f"    컬럼 {len(g['columns'])}개 / 행 {g['rowCount']}개 / 읽어온 행 {len(g['rows'])}개")
                if kind == "top" and g["rows"]:
                    summarize(g["rows"])
                saved = save_csv(fname, g["rows"])
                if saved:
                    print(f"    저장: {saved}")

        browser.close()
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 62)
print("  CSV 는 이 폴더에만 저장됩니다. 보내실 필요 없습니다.")
print("  위에 표시된 건수만 알려주시면 됩니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
