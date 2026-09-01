"""진짜 키보드 입력으로 계정과목을 넣어본다. 한 줄만.

진단으로 원인이 확실해졌다.
  editOptions.editWhenFocused = false
  칸을 선택해도 편집기가 열리지 않는다. 키를 눌러야 열린다.
  그래서 showEditor() 뒤에도 isItemEditing() 이 false 였고,
  setEditValue 는 열리지도 않은 편집기에 값을 넣으려 한 셈이다.

숨은 입력칸 GRID_TOP_line 이 RealGrid 의 편집 입력칸이다.
전에 덤프에서 maxlength=50 으로 잡혔는데 nm_acctit_cha 의 maxLength 와 같다.

그래서 커서를 옮긴 뒤 브라우저에 실제 키 입력을 보낸다.
사람이 타이핑하는 것과 같은 경로이므로 위하고의 편집 흐름이 그대로 돈다.

빈칸 판정은 이름이 아니라 코드로 한다. '미추천' 은 코드가 null 일 때
표시되는 글자일 뿐이다.

전송(F3)은 절대 누르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "키입력시험.txt"
STATUS_미추천 = "5"

FIND = r"""() => {
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
        let cn = [];
        try { cn = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (cn.includes('nm_acctit_cha')) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          const src = window.__dp || v;
          const count = src.getRowCount();
          const rows = src.getJsonRows(0, count - 1) || [];
          const targets = [];
          rows.forEach((r, i) => {
            if (String(r.ty_jungstat) !== '5') return;
            targets.push({ row: i, trade: r.nm_trade, good: r.nm_good,
                           cha: r.cd_acctit_cha, dae: r.cd_acctit_dae,
                           chaName: r.nm_acctit_cha, daeName: r.nm_acctit_dae });
          });
          return JSON.stringify({ ok: true, total: rows.length, targets: targets });
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false });
}"""

# 커서를 옮기고 그리드에 초점을 준다
FOCUS = r"""(args) => {
  const { row, field } = args;
  const g = window.__g;
  const L = [];
  try { g.setCurrent({ itemIndex: row, dataRow: row, column: field, fieldName: field });
        L.push('setCurrent: ' + JSON.stringify(g.getCurrent())); }
  catch (e) { L.push('setCurrent 오류: ' + String(e).slice(0, 140)); }
  for (const m of ['setFocusToGrid', 'setFocus', 'focus']) {
    try { if (typeof g[m] === 'function') { g[m](); L.push(m + '() 호출'); break; } } catch (e) {}
  }
  try { L.push('편집중=' + g.isItemEditing()); } catch (e) {}
  return L.join('\n');
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  const row = args.row;
  const out = {};
  try {
    const r = (dp || g).getJsonRows(row, row)[0] || {};
    out.nm_cha = r.nm_acctit_cha; out.cd_cha = r.cd_acctit_cha;
    out.nm_dae = r.nm_acctit_dae; out.cd_dae = r.cd_acctit_dae;
    out.status = r.ty_jungstat;
  } catch (e) { out.error = String(e).slice(0, 120); }
  try { out.editing = g.isItemEditing(); } catch (e) {}
  try { out.editValue = g.getEditValue(); } catch (e) {}
  try {
    const el = document.getElementById('GRID_TOP_line');
    out.hiddenInput = el ? { value: el.value, maxlength: el.getAttribute('maxlength') } : null;
  } catch (e) {}
  return JSON.stringify(out);
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  진짜 키보드 입력 시험 - 한 줄")
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

        data = json.loads(page.evaluate(FIND))
        if not data.get("ok"):
            say("전표 목록을 못 찾았습니다. 줄을 한 번 클릭하고 다시 실행해주세요.")
            raise SystemExit

        targets = data["targets"]
        say(f"전체 {data['total']}행 / 미추천 {len(targets)}건")
        say("")
        say("  줄번호  거래처                    차변           대변")
        for t in targets[:15]:
            cha = t["chaName"] if t["cha"] else "(비어있음)"
            dae = t["daeName"] if t["dae"] else "(비어있음)"
            say(f"  {t['row']:6d}  {str(t['trade'])[:22]:<24} {cha:<14} {dae}")

        print()
        row_in = input("  시험할 줄 번호 >>> ").strip()
        if not row_in.isdigit():
            print("  줄 번호를 입력하지 않아 멈춥니다.")
            raise SystemExit
        row = int(row_in)
        pick = next((t for t in targets if t["row"] == row), None)
        if pick is None:
            print("  그 줄은 미추천 목록에 없습니다.")
            raise SystemExit

        field = "nm_acctit_cha" if not pick["cha"] else "nm_acctit_dae"
        which = "차변" if field == "nm_acctit_cha" else "대변"
        print(f"\n  이 줄에서 비어 있는 쪽은 {which} 입니다. ({field})")
        value = input(f"  넣을 {which} 계정과목 >>> ").strip()
        if not value:
            print("  값을 입력하지 않아 멈춥니다.")
            raise SystemExit

        say("")
        say(f"### {row}번째 줄 / {field} <- \"{value}\"")
        say("시작 상태: " + page.evaluate(STATE, {"row": row}))

        page.bring_to_front()
        say(page.evaluate(FOCUS, {"row": row, "field": field}))
        say("초점 후: " + page.evaluate(STATE, {"row": row}))

        # 사람이 하듯 친다. 첫 글자가 편집기를 연다.
        print("\n  키를 보냅니다...")
        page.keyboard.type(value, delay=60)
        page.wait_for_timeout(400)
        say("타이핑 후: " + page.evaluate(STATE, {"row": row}))

        print("  화면을 봐주세요. 목록 팝업이 떴나요? 글자가 칸에 보이나요?")
        input("  확인하셨으면 Enter (다음: Enter 키를 보냅니다) >>> ")

        page.keyboard.press("Enter")
        page.wait_for_timeout(600)
        say("Enter 후: " + page.evaluate(STATE, {"row": row}))

        final = json.loads(page.evaluate(STATE, {"row": row}))
        say("")
        say(f"결과: {which} 이름={final.get('nm_cha' if field == 'nm_acctit_cha' else 'nm_dae')}"
            f" 코드={final.get('cd_cha' if field == 'nm_acctit_cha' else 'cd_dae')}"
            f" 전표상태={final.get('status')}")
        ok_val = final.get("cd_cha" if field == "nm_acctit_cha" else "cd_dae")
        say("→ 계정코드가 " + ("채워졌습니다. 성공" if ok_val else "여전히 비어 있습니다."))
        if str(final.get("status")) != STATUS_미추천:
            say("→ 전표상태도 풀렸습니다!")
        else:
            say("→ 전표상태는 아직 미추천입니다 (반대쪽도 채워야 풀립니다).")

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
