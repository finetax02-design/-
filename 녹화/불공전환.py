"""규칙표대로 과세를 불공으로 바꾸고 사유코드를 지정한다.

시험으로 방법이 확인됐다.
  setValue(ty_mth2, '54') + onCellEdited  ->  유형이 불공으로 바뀌고
  불공제 사유 라디오 팝업이 뜬다 (LUXRa0 ~ LUXRaB, 코드와 1:1 대응)
  0 토지의 자본적 지출관련   3 비영업용 소형승용차   4 면세사업과 관련된 분
  5 공통매입세액 안분계산서   9 접대비 관련 ...

주의: 팝업을 esc 로 닫으면 취소가 아니라 기본값 4 가 들어간다.
위하고 코드의 tyMth54 기본값이 "4" 이기 때문이다.
그러므로 팝업이 뜨면 반드시 원하는 사유를 고르고 확인까지 해야 한다.
중간에 멈추면 엉뚱한 사유가 남는다.

규칙표에 적용 Y 이고 사유코드가 3 4 5 인 거래처만 처리한다.
전송(F3)은 부르지 않는다.
"""
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
불공 = "54"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}
허용사유 = set(사유이름)

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
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          let src = window.__dp || v;
          try { const n = src.getRowCount();
                return JSON.stringify({ ok: true, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] }); }
          catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 150) }); }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

TO_불공 = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  let r;
  try { r = (dp || g).getJsonRows(args.row, args.row)[0]; } catch (e) { r = null; }
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  // 엉뚱한 줄을 건드리지 않는다
  if (String(r.nm_trade ?? '') !== String(args.trade ?? '')
      || String(r.mn_mnam ?? '') !== String(args.amount ?? '')) {
    return JSON.stringify({ ok: false, reason: '대조 실패' });
  }
  if (String(r.ty_mth2) !== '51') {
    return JSON.stringify({ ok: false, reason: '과세가 아님 (' + r.ty_mth2 + ')' });
  }
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'ty_mth2', fieldName: 'ty_mth2' }); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setCurrent ' + String(e).slice(0, 80) }); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  try { g.setValue(args.row, 'ty_mth2', '54'); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setValue ' + String(e).slice(0, 80) }); }
  let ci = -1;
  try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === 'ty_mth2'); } catch (e) {}
  try { g.onCellEdited(g, args.row, args.row, ci); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'onCellEdited ' + String(e).slice(0, 120) }); }
  return JSON.stringify({ ok: true });
}"""

# 사유 라디오를 고른다. 값이 아니라 옆에 적힌 글자로 찾아 확인까지 한다.
PICK_사유 = r"""(args) => {
  const want = String(args.code);
  const L = [];
  const radios = [...document.querySelectorAll('input[type=radio]')]
    .filter(el => el.offsetParent !== null || el.closest('[class*=dialog]'));
  L.push(`라디오 ${radios.length}개`);
  if (!radios.length) return JSON.stringify({ ok: false, reason: '라디오를 못 찾음', log: L });

  // 라디오 옆의 글자를 찾아 '5.공통매입세액' 처럼 코드로 시작하는 것을 고른다
  const textOf = el => {
    for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
      const t = (n.innerText || '').trim();
      if (t && t.length < 60) return t;
    }
    return '';
  };
  let target = null;
  for (const el of radios) {
    const t = textOf(el);
    if (t.startsWith(want + '.') || t.startsWith(want + ' ')) { target = el; L.push(`글자로 찾음: "${t}"`); break; }
  }
  if (!target) {
    // 글자로 못 찾으면 값 규칙으로 (LUXRa5 등)
    target = radios.find(el => String(el.value).endsWith(want));
    if (target) L.push(`값으로 찾음: ${target.value}`);
  }
  if (!target) return JSON.stringify({ ok: false, reason: `사유 ${want} 를 못 찾음`, log: L });

  try { target.click(); L.push('라디오 클릭'); }
  catch (e) { L.push('클릭 오류: ' + String(e).slice(0, 100)); }
  try {
    const lab = target.closest('label') || target.parentElement;
    if (lab && lab !== target) { lab.click(); L.push('라벨도 클릭'); }
  } catch (e) {}
  L.push('선택됨=' + target.checked);
  return JSON.stringify({ ok: true, log: L, checked: target.checked, value: target.value });
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    return JSON.stringify({ ty_mth2: r.ty_mth2, cd_notdedct: r.cd_notdedct,
                            status: r.ty_jungstat, trade: r.nm_trade });
  } catch (e) { return JSON.stringify({ error: String(e).slice(0, 100) }); }
}"""

print()
print("=" * 68)
print("  규칙표대로 과세 → 불공 전환")
print("=" * 68)
print()
print("  [주의] 사유 팝업이 뜬 뒤 중간에 멈추면 기본값 4(면세사업관련)가")
print("         들어갑니다. esc 는 취소가 아닙니다.")
print("         시작하면 각 건마다 사유 선택까지 끝냅니다.")
print()

if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = (r.get("사유코드") or "").strip()
        if (r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y")
                and code in 허용사유):
            rules[r["사업자번호"].strip()] = {"code": code, "name": r.get("거래처명")}
print(f"  규칙표: 불공 적용 거래처 {len(rules)}곳 (사유 3·4·5 만)")
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 진행하세요.")
print()
input("  준비되었으면 Enter >>> ")

done = []
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

        targets = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            rule = rules.get(str(r.get("no_bisocial") or ""))
            if rule:
                targets.append({"row": i, "rec": r, "code": rule["code"]})
        print(f"\n  전표 {len(rows)}건 / 전환 대상 {len(targets)}건")
        by_code = {}
        for t in targets:
            by_code[t["code"]] = by_code.get(t["code"], 0) + 1
        print("  사유별: " + ", ".join(f"{k} {사유이름[k]} {v}건" for k, v in sorted(by_code.items())))
        print()
        for t in targets[:25]:
            print(f"    {t['row']:4d}행 {str(t['rec'].get('nm_trade'))[:20]:<22}"
                  f" {str(t['rec'].get('nm_good'))[:24]:<26} 사유={t['code']} {사유이름[t['code']]}")
        if not targets:
            print("\n  전환할 건이 없습니다.")
            raise SystemExit

        def convert(t):
            r = t["rec"]
            before = json.loads(page.evaluate(STATE, {"row": t["row"]}))
            res = json.loads(page.evaluate(TO_불공, {
                "row": t["row"], "trade": r.get("nm_trade"), "amount": r.get("mn_mnam")}))
            if not res.get("ok"):
                print(f"      건너뜀: {res.get('reason')}")
                return False, before, None
            page.wait_for_timeout(1200)

            pick = json.loads(page.evaluate(PICK_사유, {"code": t["code"]}))
            for line in pick.get("log", []):
                print(f"      {line}")
            if not pick.get("ok"):
                print(f"      사유 선택 실패: {pick.get('reason')}")

            clicked = False
            for sel in ("button:has-text('확인(enter)')", "button:has-text('확인')"):
                try:
                    loc = page.locator(sel).last
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=4000)
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                page.keyboard.press("Enter")
            page.wait_for_timeout(1200)

            after = json.loads(page.evaluate(STATE, {"row": t["row"]}))
            ok = (str(after.get("ty_mth2")) == 불공
                  and str(after.get("cd_notdedct") or "").strip() == t["code"])
            return ok, before, after

        print()
        print("  " + "-" * 60)
        first = targets[0]
        print(f"   먼저 한 건만: {first['row']}행 {first['rec'].get('nm_trade')}")
        print(f"   과세 → 불공 / 사유 {first['code']} {사유이름[first['code']]}")
        print("  " + "-" * 60)
        if input("\n  진행할까요? (y) >>> ").strip().lower() != "y":
            raise SystemExit

        ok, before, after = convert(first)
        print(f"\n  전: {json.dumps(before, ensure_ascii=False)}")
        print(f"  후: {json.dumps(after, ensure_ascii=False) if after else '(없음)'}")
        print(f"  → {'성공' if ok else '기대한 값이 아닙니다. 화면에서 확인해주세요'}")
        done.append({"줄번호": first["row"], "거래처": first["rec"].get("nm_trade"),
                     "사유": first["code"], "성공": ok})

        if not ok:
            print("\n  실패했으므로 나머지는 진행하지 않습니다.")
            print("  이 줄의 유형과 불공사유를 화면에서 확인해주세요.")
        elif len(targets) > 1:
            print()
            if input(f"  나머지 {len(targets) - 1}건도 진행할까요? (y) >>> ").strip().lower() == "y":
                good = 1
                for t in targets[1:]:
                    print(f"    {t['row']:4d}행 {str(t['rec'].get('nm_trade'))[:18]:<20} 사유={t['code']}")
                    ok2, _, after2 = convert(t)
                    good += 1 if ok2 else 0
                    done.append({"줄번호": t["row"], "거래처": t["rec"].get("nm_trade"),
                                 "사유": t["code"], "성공": ok2})
                    if not ok2:
                        print(f"      기대한 값이 아님: {json.dumps(after2, ensure_ascii=False)}")
                        print("      여기서 멈춥니다.")
                        break
                print(f"\n  전환된 건: {good} / {len(targets)}")

        if done:
            out = HERE / f"불공전환기록_{datetime.now():%Y%m%d_%H%M}.csv"
            with out.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(done[0].keys()))
                w.writeheader()
                w.writerows(done)
            print(f"\n  기록: {out}")

        browser.close()
except SystemExit:
    pass
except Exception:
    print("\n실패했습니다. 원인:")
    traceback.print_exc()

print()
print("=" * 68)
print("  전송(F3)은 누르지 않았습니다.")
print("  유형과 불공사유를 화면에서 확인하시고 직접 전송하세요.")
print("=" * 68)
print()
input("  창을 닫으려면 Enter >>> ")
