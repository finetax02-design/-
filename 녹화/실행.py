"""미추천 전표의 빈 계정과목을 채워 전송 가능 상태로 만든다.

한 건 시험으로 전 과정이 검증됐다.
  대상 칸으로 커서 이동 -> F2 로 코드도움 팝업
  -> 839개 계정과목 마스터에서 코드로 줄 찾기 -> 그 줄 지정
  -> 확인 버튼 클릭 -> 값 반영, 전표상태 미추천에서 확정가능으로

넣을 계정은 같은 화면의 과거 이력에서 배운다.
  1 같은 사업자등록번호의 과거 계정
  2 같은 품명의 과거 계정
  3 대변만, 이 고객사에서 가장 많이 쓰는 대변 계정
차변을 판단하지 못하면 그 줄은 손대지 않는다.

안전장치
  - 그리드를 컬럼으로 검증한다
  - 칸마다 거래처명과 공급가액을 대조하고 다르면 건너뛴다
  - 쓰기 전후 코드를 비교해 실제로 바뀌었을 때만 성공으로 센다
  - 먼저 한 건만 하고 확인한 뒤에 나머지로 넘어간다
  - 실패하면 즉시 멈춘다
  - 전송(F3)은 절대 누르지 않는다
"""
import collections
import csv
import json
import re
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
STATUS_미추천 = "5"

NOISE = [re.compile(r"\(오더번호[^)]*\)"), re.compile(r"\(\d[^)]*\)"),
         re.compile(r"\[[^\]]*\]"), re.compile(r"외\s*\d+\s*건"), re.compile(r"\d+")]


def norm_item(name):
    s = str(name or "")
    for pat in NOISE:
        s = pat.sub(" ", s)
    return re.sub(r"[\s\-_/,]+", " ", s).strip().lower()


GRIDS = r"""(args) => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const rowsOf = g => {
    let src = g;
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try { const n = src.getRowCount(); return { count: n, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] }; }
    catch (e) { return { count: 0, rows: [] }; }
  };
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
  const out = { main: null, popup: null };
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
        try { cols = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cols.includes('nm_acctit_cha')) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          out.main = args.withMain ? rowsOf(v) : { count: rowsOf(v).count, rows: [] };
        } else if (cols.includes('cd_acctit') && cols.includes('nm_acctit')) {
          window.__pop = v;
          out.popup = args.withPopup ? rowsOf(v) : { count: rowsOf(v).count, rows: [] };
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify(out);
}"""

PREP = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  // 엉뚱한 줄을 건드리지 않도록 먼저 대조한다
  let r;
  try { r = (dp || g).getJsonRows(args.row, args.row)[0]; } catch (e) { r = null; }
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(r.nm_trade ?? '') !== String(args.trade ?? '')
      || String(r.mn_mnam ?? '') !== String(args.amount ?? '')) {
    return JSON.stringify({ ok: false, reason: '대조 실패' });
  }
  const codeField = args.field === 'nm_acctit_cha' ? 'cd_acctit_cha' : 'cd_acctit_dae';
  if (r[codeField]) return JSON.stringify({ ok: false, reason: '이미 채워져 있음' });
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: args.field, fieldName: args.field }); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setCurrent ' + String(e).slice(0, 90) }); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  return JSON.stringify({ ok: true });
}"""

GOTO = r"""(args) => {
  const p = window.__pop;
  if (!p) return JSON.stringify({ ok: false, reason: '팝업 그리드 없음' });
  try { p.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'nm_acctit', fieldName: 'nm_acctit' }); }
  catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 120) }); }
  try { if (p.setFocusToGrid) p.setFocusToGrid(); } catch (e) {}
  let shown = null;
  try {
    let src = p;
    try { const dp = p.getDataSource(); if (dp) src = dp; } catch (e) {}
    const r = src.getJsonRows(args.row, args.row)[0];
    shown = r ? `${r.cd_acctit} ${r.nm_acctit}` : null;
  } catch (e) {}
  return JSON.stringify({ ok: true, shown: shown });
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    return JSON.stringify({ nm_cha: r.nm_acctit_cha, cd_cha: r.cd_acctit_cha,
                            nm_dae: r.nm_acctit_dae, cd_dae: r.cd_acctit_dae,
                            status: r.ty_jungstat });
  } catch (e) { return JSON.stringify({ error: String(e).slice(0, 100) }); }
}"""


def learn(rows):
    """계정과목이 채워진 건에서 사업자번호별 품명별 계정코드를 배운다."""
    biz = {"cha": collections.defaultdict(collections.Counter),
           "dae": collections.defaultdict(collections.Counter)}
    item = {"cha": collections.defaultdict(collections.Counter),
            "dae": collections.defaultdict(collections.Counter)}
    common = {"cha": collections.Counter(), "dae": collections.Counter()}
    for r in rows:
        for side, cf, nf in (("cha", "cd_acctit_cha", "nm_acctit_cha"),
                             ("dae", "cd_acctit_dae", "nm_acctit_dae")):
            code = r.get(cf)
            if not code:
                continue
            pair = f"{code}|{r.get(nf)}"
            common[side][pair] += 1
            if r.get("no_bisocial"):
                biz[side][str(r["no_bisocial"])][pair] += 1
            key = norm_item(r.get("nm_good"))
            if key:
                item[side][key][pair] += 1
    return biz, item, common


def guess(rec, side, biz, item, common, use_common):
    for src, why in ((biz[side].get(str(rec.get("no_bisocial") or "")), "거래처"),
                     (item[side].get(norm_item(rec.get("nm_good"))), "품명")):
        if src:
            pair, n = src.most_common(1)[0]
            code, _, name = pair.partition("|")
            return code, name, why, n / sum(src.values())
    if use_common and common[side]:
        pair, n = common[side].most_common(1)[0]
        code, _, name = pair.partition("|")
        return code, name, "최빈값", n / sum(common[side].values())
    return None, None, "없음", 0.0


print()
print("=" * 64)
print("  미추천 전표 자동분개")
print("=" * 64)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  전송(F3)은 절대 누르지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

log_rows = []
try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        page = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if page is None:
            print("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit
        page.bring_to_front()

        data = json.loads(page.evaluate(GRIDS, {"withMain": True, "withPopup": False}))
        if not data.get("main") or not data["main"]["rows"]:
            print("\n  전표 목록을 못 찾았습니다. 줄을 클릭하고 다시 실행해주세요.")
            raise SystemExit
        rows = data["main"]["rows"]
        print(f"\n  전표 목록 {len(rows)}행")

        learned = [r for r in rows if str(r.get("ty_jungstat")) != STATUS_미추천]
        biz, item, common = learn(learned)
        print(f"  학습 {len(learned)}건")
        if common["dae"]:
            pair, n = common["dae"].most_common(1)[0]
            print(f"  이 고객사에서 가장 많은 대변: {pair.split('|')[1]} ({n}건)")

        plan = []
        skipped = []
        for i, r in enumerate(rows):
            if str(r.get("ty_jungstat")) != STATUS_미추천:
                continue
            cha_code, cha_name, cha_why, _ = guess(r, "cha", biz, item, common, use_common=False)
            if not cha_code and not r.get("cd_acctit_cha"):
                skipped.append((i, r, "차변 판단 불가"))
                continue
            for side, field, code, name, why in (
                    ("차변", "nm_acctit_cha", cha_code, cha_name, cha_why),
                    ("대변", "nm_acctit_dae", *guess(r, "dae", biz, item, common, use_common=True)[:3])):
                cf = "cd_acctit_cha" if field == "nm_acctit_cha" else "cd_acctit_dae"
                if r.get(cf):
                    continue     # 이미 채워져 있다
                if not code:
                    skipped.append((i, r, f"{side} 판단 불가"))
                    continue
                plan.append({"row": i, "rec": r, "side": side, "field": field,
                             "code": code, "name": name, "why": why})

        print(f"\n  처리 대상 {len(plan)}칸 / 건너뜀 {len(skipped)}칸")
        by_why = collections.Counter(x["why"] for x in plan)
        print("  판단 근거: " + ", ".join(f"{k} {v}칸" for k, v in by_why.items()))
        print()
        for x in plan[:25]:
            print(f"    {x['row']:4d}행 {x['side']}  {str(x['rec'].get('nm_trade'))[:18]:<20}"
                  f" → {x['code']} {x['name']}  ({x['why']})")
        for i, r, why in skipped[:10]:
            print(f"    {i:4d}행 --   {str(r.get('nm_trade'))[:18]:<20} 건너뜀: {why}")
        if not plan:
            print("\n  처리할 칸이 없습니다.")
            raise SystemExit

        popup_rows = []

        def fill(x):
            """한 칸을 채운다. 성공하면 True."""
            r = x["rec"]
            before = json.loads(page.evaluate(STATE, {"row": x["row"]}))
            prep = json.loads(page.evaluate(PREP, {
                "row": x["row"], "field": x["field"],
                "trade": r.get("nm_trade"), "amount": r.get("mn_mnam")}))
            if not prep.get("ok"):
                print(f"      건너뜀: {prep.get('reason')}")
                return False, before, None

            page.keyboard.press("F2")
            page.wait_for_timeout(1300)

            global popup_rows
            if not popup_rows:
                pop = json.loads(page.evaluate(GRIDS, {"withMain": False, "withPopup": True})).get("popup")
                if not pop or not pop["rows"]:
                    print("      팝업을 못 읽었습니다.")
                    page.keyboard.press("Escape")
                    return False, before, None
                popup_rows = pop["rows"]
                print(f"      (계정과목 마스터 {len(popup_rows)}개 확보)")
            else:
                page.evaluate(GRIDS, {"withMain": False, "withPopup": False})

            hit = next((i for i, pr in enumerate(popup_rows)
                        if str(pr.get("cd_acctit")) == str(x["code"])), None)
            if hit is None:
                print(f"      코드 {x['code']} 를 마스터에서 못 찾음")
                page.keyboard.press("Escape")
                return False, before, None

            go = json.loads(page.evaluate(GOTO, {"row": hit}))
            if not go.get("ok"):
                print(f"      팝업 이동 실패: {go.get('reason')}")
                page.keyboard.press("Escape")
                return False, before, None

            done = False
            for sel in ("button:has-text('확인(enter)')", "button:has-text('확인')"):
                try:
                    loc = page.locator(sel).last
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=4000)
                        done = True
                        break
                except Exception:
                    pass
            if not done:
                page.keyboard.press("Enter")
            page.wait_for_timeout(1200)

            after = json.loads(page.evaluate(STATE, {"row": x["row"]}))
            key = "cd_cha" if x["field"] == "nm_acctit_cha" else "cd_dae"
            return before.get(key) != after.get(key), before, after

        print()
        print("  " + "-" * 58)
        first = plan[0]
        print(f"   먼저 한 칸만 합니다: {first['row']}행 {first['side']}")
        print(f"   {first['rec'].get('nm_trade')} → {first['code']} {first['name']}")
        print("  " + "-" * 58)
        if input("\n  진행할까요? (y) >>> ").strip().lower() != "y":
            raise SystemExit

        ok, before, after = fill(first)
        print(f"\n  결과: {json.dumps(after, ensure_ascii=False) if after else '(없음)'}")
        print(f"  → {'성공' if ok else '값이 바뀌지 않았습니다'}")
        if after and str(after.get("status")) != STATUS_미추천:
            print("  → 전표상태도 풀렸습니다!")
        log_rows.append({**{k: first[k] for k in ("row", "side", "code", "name", "why")},
                         "거래처": first["rec"].get("nm_trade"), "성공": ok})

        if not ok:
            print("\n  실패했으므로 나머지는 진행하지 않습니다.")
        elif len(plan) > 1:
            print()
            if input(f"  나머지 {len(plan) - 1}칸도 진행할까요? (y) >>> ").strip().lower() == "y":
                good = 1
                for x in plan[1:]:
                    print(f"    {x['row']:4d}행 {x['side']} → {x['code']} {x['name']}")
                    ok2, _, after2 = fill(x)
                    good += 1 if ok2 else 0
                    log_rows.append({**{k: x[k] for k in ("row", "side", "code", "name", "why")},
                                     "거래처": x["rec"].get("nm_trade"), "성공": ok2})
                    if not ok2:
                        print("      실패. 여기서 멈춥니다.")
                        break
                print(f"\n  채운 칸: {good} / {len(plan)}")

        if log_rows:
            out = HERE / f"처리기록_{datetime.now():%Y%m%d_%H%M}.csv"
            with out.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()))
                w.writeheader()
                w.writerows(log_rows)
            print(f"\n  처리 기록: {out}")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 64)
print("  전송(F3)은 누르지 않았습니다.")
print("  화면에서 확인하시고 직접 전송하세요.")
print("=" * 64)
print()
input("  창을 닫으려면 Enter >>> ")
