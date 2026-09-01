"""코드도움 팝업의 목록을 읽어 원하는 계정을 정확히 골라낸다.

두 가지가 확인됐다.

1) 한글이 뒤섞인다. '의약품' 을 쳤는데 입력칸에 '약품의' 가 들어갔다.
   keyboard.type 은 키를 하나씩 보내는데 한글 조합 처리와 충돌한다.
   해결: insertText 로 글자를 통째로 넣는다. 조합을 거치지 않는다.

2) 팝업 목록도 RealGrid 다. 숨은 입력칸 이름이 CODEHELP-FTB_ACCTIT_line 으로
   메인 그리드의 GRID_TOP_line 과 같은 규칙이다. HTML 표가 아니다.
   그래서 메인 그리드를 찾은 방법 그대로 이 그리드도 찾는다.
   찾으면 목록에서 어느 줄이 원하는 코드인지 데이터로 확인하고 고를 수 있다.

흐름
  커서 이동 -> F2 로 팝업 -> 검색칸에 이름 삽입 -> 팝업 목록 읽기
  -> 원하는 코드의 줄을 지정 -> 확인

값 확정 여부는 사람이 정한다. 전송(F3)은 누르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "팝업선택.txt"

# 그리드를 모두 찾아 컬럼으로 구분한다. 메인은 nm_acctit_cha 를 갖는다.
GRIDS = r"""() => {
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const seen = new WeakSet();
  const queue = [{ o: window, d: 0 }];
  const SKIP = /^(document|location|navigator|parent|top|self|frames|history|localStorage|sessionStorage|indexedDB|caches|crypto)$/;
  let visited = 0;
  const found = [];
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
        if (cols.length) found.push({ obj: v, cols: cols });
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }

  const read = g => {
    let src = g, count = 0, rows = [];
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try { count = src.getRowCount(); if (count > 0) rows = src.getJsonRows(0, Math.min(count, 60) - 1) || []; }
    catch (e) {}
    return { count: count, rows: rows };
  };

  const out = { main: null, popup: null, all: [] };
  for (const f of found) {
    const info = { cols: f.cols.length, sample: f.cols.slice(0, 12) };
    if (f.cols.includes('nm_acctit_cha')) {
      window.__g = f.obj;
      try { window.__dp = f.obj.getDataSource(); } catch (e) { window.__dp = null; }
      out.main = { ...info, ...read(f.obj) };
      out.main.rows = undefined;   // 메인 행은 여기서 안 쓴다
      info.role = '메인';
    } else if (f.cols.some(c => /acctit|계정/i.test(c))) {
      window.__pop = f.obj;
      const r = read(f.obj);
      out.popup = { ...info, count: r.count, rows: r.rows, columns: f.cols };
      info.role = '팝업후보';
    }
    out.all.push(info);
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

PICK = r"""(args) => {
  const p = window.__pop;
  const L = [];
  if (!p) return '팝업 그리드를 못 찾았습니다.';
  try { p.setCurrent({ itemIndex: args.row, dataRow: args.row });
        L.push('팝업 커서 이동: ' + JSON.stringify(p.getCurrent())); }
  catch (e) { L.push('오류: ' + String(e).slice(0, 150)); }
  try { if (p.setFocusToGrid) { p.setFocusToGrid(); L.push('팝업에 초점'); } } catch (e) {}
  return L.join('\n');
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  const out = {};
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    out.nm_cha = r.nm_acctit_cha; out.cd_cha = r.cd_acctit_cha;
    out.nm_dae = r.nm_acctit_dae; out.cd_dae = r.cd_acctit_dae;
    out.status = r.ty_jungstat;
  } catch (e) { out.error = String(e).slice(0, 100); }
  return JSON.stringify(out);
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  코드도움 팝업에서 계정 골라내기")
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
        first = json.loads(page.evaluate(GRIDS))
        if not first.get("main"):
            say("전표 목록을 못 찾았습니다. 줄을 클릭하고 다시 실행해주세요.")
            raise SystemExit
        say(f"메인 그리드 확인 (컬럼 {first['main']['cols']}개, 행 {first['main']['count']}개)")

        row_in = input("\n  시험할 줄 번호 >>> ").strip()
        if not row_in.isdigit():
            raise SystemExit
        row = int(row_in)
        field = input("  채울 칸 (1=차변, 2=대변) >>> ").strip()
        field = "nm_acctit_cha" if field == "1" else "nm_acctit_dae"
        name = input("  찾을 계정과목 이름 (예: 의약품) >>> ").strip()
        want = input("  원하는 계정코드 (예: 14600, 모르면 Enter) >>> ").strip()
        if not name:
            raise SystemExit

        say("")
        say(f"### {row}번째 줄 / {field} / 찾을 이름 '{name}' / 원하는 코드 '{want or '(지정없음)'}'")
        say("시작: " + page.evaluate(STATE, {"row": row}))
        say(page.evaluate(PREP, {"row": row, "field": field}))

        print("\n  F2 로 팝업을 엽니다...")
        page.keyboard.press("F2")
        page.wait_for_timeout(1200)

        # 한글이 뒤섞이지 않도록 글자를 통째로 넣는다
        box = page.locator("div.dialog_content input.LSinput").first
        try:
            box.click(timeout=3000)
            page.keyboard.insert_text(name)
            say(f"검색칸에 '{name}' 삽입")
        except Exception as exc:
            say(f"검색칸 입력 실패: {str(exc)[:150]}")
        page.wait_for_timeout(1000)
        try:
            say("검색칸 실제 값: " + json.dumps(box.input_value(), ensure_ascii=False))
        except Exception:
            pass

        after = json.loads(page.evaluate(GRIDS))
        pop = after.get("popup")
        say("")
        say("===== 팝업 목록 =====")
        if not pop:
            say("  팝업 그리드를 못 찾았습니다.")
            say("  찾은 그리드들: " + json.dumps(after.get("all"), ensure_ascii=False)[:600])
        else:
            say(f"  컬럼 {pop['cols']}개: {', '.join(pop['columns'][:15])}")
            say(f"  행 {pop['count']}개")
            match = None
            for i, r in enumerate(pop["rows"][:40]):
                vals = " | ".join(f"{k}={v}" for k, v in list(r.items())[:6] if v not in (None, ""))
                mark = ""
                if want and want in json.dumps(r, ensure_ascii=False):
                    mark = "  <-- 원하는 코드"
                    if match is None:
                        match = i
                say(f"    {i:3d}: {vals[:120]}{mark}")

            print()
            if match is not None:
                print(f"  {match}번째 줄이 코드 {want} 로 보입니다.")
            sel = input("  선택할 목록 줄 번호 (Enter = 건너뛰기) >>> ").strip()
            if sel.isdigit():
                say(page.evaluate(PICK, {"row": int(sel)}))
                page.wait_for_timeout(300)
                print("\n  화면을 봐주세요. 그 줄이 선택되었나요?")
                if input("  Enter 키로 확정할까요? (y) >>> ").strip().lower() == "y":
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(1000)
                    say("확정 후: " + page.evaluate(STATE, {"row": row}))

        final = json.loads(page.evaluate(STATE, {"row": row}))
        code = final.get("cd_cha" if field == "nm_acctit_cha" else "cd_dae")
        say("")
        say(f"결과: 코드={code} 전표상태={final.get('status')}")
        say("→ " + ("계정코드가 채워졌습니다. 성공" if code else "코드가 아직 비어 있습니다."))

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
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
