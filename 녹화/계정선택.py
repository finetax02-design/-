"""팝업 목록에서 코드로 계정을 골라 빈 칸을 채운다. 타이핑 없음.

앞선 시험에서 두 가지가 확인됐다.

1) 팝업 목록은 계정과목 마스터 전체다. 839행에 코드와 이름이 모두 있다.
   그러면 검색칸이 필요 없다. 목록에서 원하는 코드의 줄을 찾아 지정하면 된다.
   한글 입력 문제도, 검색칸 클릭 실패도 함께 사라진다.

2) 지난 시험은 시작부터 차변이 채워져 있던 줄을 골라 아무것도 증명하지 못했다.
   판정이 허술했다. 이번에는 정말로 비어 있는 칸에만 시도하고,
   쓰기 전후 값을 비교해서 실제로 바뀌었을 때만 성공이라고 한다.

흐름
  빈 칸으로 커서 이동 -> F2 로 팝업 -> 팝업 목록에서 코드로 줄 찾기
  -> 그 줄로 이동 -> Enter -> 값이 실제로 바뀌었는지 확인

전송(F3)은 누르지 않는다.
"""
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "계정선택.txt"

# 메인 그리드와 팝업 그리드를 컬럼으로 구분해 잡는다
GRIDS = r"""(args) => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
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
          const src = window.__dp || v;
          try {
            const n = src.getRowCount();
            out.main = { count: n, rows: args.withRows ? (src.getJsonRows(0, n - 1) || []) : [] };
          } catch (e) { out.main = { count: 0, rows: [] }; }
        } else if (cols.includes('cd_acctit') && cols.includes('nm_acctit')) {
          window.__pop = v;
          let src = v;
          try { const dp = v.getDataSource(); if (dp) src = dp; } catch (e) {}
          try {
            const n = src.getRowCount();
            out.popup = { count: n, rows: src.getJsonRows(0, n - 1) || [] };
          } catch (e) { out.popup = { count: 0, rows: [] }; }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify(out);
}"""

PREP = r"""(args) => {
  const g = window.__g;
  const L = [];
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: args.field, fieldName: args.field });
        L.push('커서: ' + JSON.stringify(g.getCurrent())); }
  catch (e) { L.push('setCurrent 오류: ' + String(e).slice(0, 130)); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  return L.join('\n');
}"""

# 팝업 목록에서 코드에 해당하는 줄로 커서를 옮긴다
GOTO = r"""(args) => {
  const p = window.__pop;
  if (!p) return JSON.stringify({ ok: false, reason: '팝업 그리드 없음' });
  const L = [];
  try {
    p.setCurrent({ itemIndex: args.row, dataRow: args.row,
                   column: 'nm_acctit', fieldName: 'nm_acctit' });
    L.push('팝업 커서: ' + JSON.stringify(p.getCurrent()));
  } catch (e) { L.push('오류: ' + String(e).slice(0, 150)); }
  try { if (p.setFocusToGrid) { p.setFocusToGrid(); L.push('팝업에 초점'); } } catch (e) {}
  let shown = null;
  try {
    let src = p;
    try { const dp = p.getDataSource(); if (dp) src = dp; } catch (e) {}
    const r = src.getJsonRows(args.row, args.row)[0];
    shown = r ? { cd: r.cd_acctit, nm: r.nm_acctit } : null;
  } catch (e) {}
  return JSON.stringify({ ok: true, log: L, row: shown });
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    return JSON.stringify({ nm_cha: r.nm_acctit_cha, cd_cha: r.cd_acctit_cha,
                            nm_dae: r.nm_acctit_dae, cd_dae: r.cd_acctit_dae,
                            status: r.ty_jungstat, trade: r.nm_trade });
  } catch (e) { return JSON.stringify({ error: String(e).slice(0, 120) }); }
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  팝업 목록에서 코드로 계정 고르기 (타이핑 없음)")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  전송(F3)은 누르지 않습니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        page = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if page is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit
        page.bring_to_front()

        data = json.loads(page.evaluate(GRIDS, {"withRows": True}))
        if not data.get("main"):
            say("전표 목록을 못 찾았습니다. 줄을 클릭하고 다시 실행해주세요.")
            raise SystemExit
        rows = data["main"]["rows"]
        say(f"메인 그리드 {len(rows)}행")

        # 정말로 비어 있는 칸만 모은다
        todo = []
        for i, r in enumerate(rows):
            if str(r.get("ty_jungstat")) != "5":
                continue
            if not r.get("cd_acctit_cha"):
                todo.append((i, "nm_acctit_cha", "차변", r))
            if not r.get("cd_acctit_dae"):
                todo.append((i, "nm_acctit_dae", "대변", r))
        say(f"\n비어 있는 칸 {len(todo)}개")
        for i, (row, field, side, r) in enumerate(todo[:20]):
            say(f"  [{i:2d}] {row:4d}행 {side}  {str(r.get('nm_trade'))[:20]:<22} {str(r.get('nm_good'))[:24]}")
        if not todo:
            say("비어 있는 칸이 없습니다.")
            raise SystemExit

        sel = input("\n  시험할 항목 번호 ([ ] 안의 숫자) >>> ").strip()
        if not sel.isdigit() or int(sel) >= len(todo):
            raise SystemExit
        row, field, side, rec = todo[int(sel)]

        before = json.loads(page.evaluate(STATE, {"row": row}))
        say("")
        say(f"### {row}행 {side} ({field})")
        say(f"거래처: {before.get('trade')}")
        say("시작: " + json.dumps(before, ensure_ascii=False))

        want = input(f"  넣을 계정코드 (예: 14600) >>> ").strip()
        if not want:
            raise SystemExit

        say(page.evaluate(PREP, {"row": row, "field": field}))
        print("\n  F2 로 팝업을 엽니다...")
        page.keyboard.press("F2")
        page.wait_for_timeout(1500)

        pop = json.loads(page.evaluate(GRIDS, {"withRows": False})).get("popup")
        if not pop:
            say("팝업 그리드를 못 찾았습니다.")
            raise SystemExit
        say(f"팝업 목록 {pop['count']}행")

        # 계정과목 마스터를 파일로 남겨둔다. 다음부터 이름-코드 변환에 쓴다.
        master = HERE / "계정과목마스터.csv"
        if pop["rows"]:
            with master.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(pop["rows"][0].keys()))
                w.writeheader()
                w.writerows(pop["rows"])
            say(f"계정과목 마스터 저장: {master}")

        hit = next((i for i, r in enumerate(pop["rows"])
                    if str(r.get("cd_acctit")) == want), None)
        if hit is None:
            say(f"코드 {want} 를 목록에서 못 찾았습니다.")
            near = [f"{r.get('cd_acctit')} {r.get('nm_acctit')}"
                    for r in pop["rows"] if want in str(r.get("cd_acctit", ""))][:10]
            say("비슷한 코드: " + ", ".join(near))
            raise SystemExit

        target = pop["rows"][hit]
        say(f"찾음: 목록 {hit}번째 = {target.get('cd_acctit')} {target.get('nm_acctit')}")

        res = json.loads(page.evaluate(GOTO, {"row": hit}))
        for line in res.get("log", []):
            say("  " + line)
        say(f"  팝업에서 선택된 줄: {json.dumps(res.get('row'), ensure_ascii=False)}")
        page.wait_for_timeout(400)

        print("\n  화면을 봐주세요. 팝업에서 그 계정이 선택되어 있나요?")
        if input("  Enter 키로 확정할까요? (y) >>> ").strip().lower() != "y":
            print("  확정하지 않고 esc 로 닫습니다.")
            page.keyboard.press("Escape")
            raise SystemExit

        page.keyboard.press("Enter")
        page.wait_for_timeout(1200)

        after = json.loads(page.evaluate(STATE, {"row": row}))
        say("")
        say("끝: " + json.dumps(after, ensure_ascii=False))
        key = "cd_cha" if field == "nm_acctit_cha" else "cd_dae"
        changed = before.get(key) != after.get(key)
        say("")
        say(f"{side} 코드: {before.get(key)} → {after.get(key)}")
        say("→ " + ("실제로 바뀌었습니다. 성공" if changed else "바뀌지 않았습니다."))
        if str(after.get("status")) != "5":
            say("→ 전표상태도 풀렸습니다! (양쪽이 다 채워짐)")
        else:
            say("→ 전표상태는 아직 미추천 (반대쪽도 채워야 풀립니다)")

        browser.close()
except SystemExit:
    pass
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  전송(F3)은 누르지 않았습니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
