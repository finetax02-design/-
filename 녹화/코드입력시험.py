"""계정과목을 이름 대신 코드로 넣어본다. 그리고 글자 유실을 막는다.

앞선 시험에서 두 가지가 드러났다.

1) 타이핑한 '지급수수료' 중 '수수료' 만 들어갔다.
   첫 키가 편집기를 여는 데 쓰이고 그동안 들어온 키가 버려진다.
   해결: 키 하나로 편집기를 먼저 연 뒤, 열린 것을 확인하고
        setEditValue 로 값을 통째로 넣는다.

2) 이름이 겹치면 선택 팝업이 뜬다. 지급수수료가 세 개였다.
   자동화에서는 프로그램이 어느 것인지 정해야 한다.
   우리는 과거 이력에서 계정코드까지 알고 있으므로
   이름 대신 코드를 넣으면 겹칠 일이 없다. 그게 되는지 확인한다.

세 가지를 하나씩 시도한다.
  E1 코드를 nm_acctit_cha 칸에 입력
  E2 코드를 cd_acctit_cha 칸에 직접 입력 (그 칸이 편집 가능하면)
  E3 이름을 setEditValue 로 통째로 입력 (글자 유실 없이)

각 시도 뒤 팝업이 떴는지 화면에서 찾아 구조를 기록한다.
전송(F3)은 누르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "코드입력시험.txt"

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
        let cols = [];
        try { cols = v.getColumns(); } catch (e) {}
        const names = cols.map(c => String(c.name || c.fieldName || ''));
        if (names.includes('nm_acctit_cha')) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          const src = window.__dp || v;
          const count = src.getRowCount();
          const rows = src.getJsonRows(0, count - 1) || [];

          // 계정코드 칸이 편집 가능한지 확인
          const colInfo = {};
          for (const f of ['nm_acctit_cha', 'cd_acctit_cha', 'nm_acctit_dae', 'cd_acctit_dae']) {
            const c = cols.find(x => String(x.name || x.fieldName) === f);
            colInfo[f] = c ? { editable: c.editable, readOnly: c.readOnly,
                               visible: c.visible, editor: c.editor,
                               editorOptions: c.editorOptions, button: c.button } : null;
          }

          // 과거 이력에서 계정 이름과 코드 짝을 모은다
          const pairs = {};
          for (const r of rows) {
            if (r.nm_acctit_cha && r.cd_acctit_cha) pairs[r.nm_acctit_cha] = r.cd_acctit_cha;
            if (r.nm_acctit_dae && r.cd_acctit_dae) pairs[r.nm_acctit_dae] = r.cd_acctit_dae;
          }

          const targets = [];
          rows.forEach((r, i) => {
            if (String(r.ty_jungstat) !== '5') return;
            targets.push({ row: i, trade: r.nm_trade, good: r.nm_good,
                           chaCode: r.cd_acctit_cha, daeCode: r.cd_acctit_dae,
                           chaName: r.nm_acctit_cha, daeName: r.nm_acctit_dae });
          });
          return JSON.stringify({ ok: true, total: rows.length, targets: targets,
                                  colInfo: colInfo, pairs: pairs });
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false });
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

SET_EDIT = r"""(args) => {
  const g = window.__g;
  const L = [];
  try { L.push('편집중=' + g.isItemEditing()); } catch (e) {}
  try { g.setEditValue(args.value, false, false); L.push('setEditValue: ' + args.value); }
  catch (e) { L.push('setEditValue 오류: ' + String(e).slice(0, 130)); }
  try { L.push('편집값=' + JSON.stringify(g.getEditValue())); } catch (e) {}
  try {
    const el = document.getElementById('GRID_TOP_line');
    L.push('숨은칸=' + (el ? JSON.stringify(el.value) : 'null'));
  } catch (e) {}
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
  try { out.editing = g.isItemEditing(); } catch (e) {}
  try { out.editValue = g.getEditValue(); } catch (e) {}
  try {
    const el = document.getElementById('GRID_TOP_line');
    out.hidden = el ? el.value : null;
  } catch (e) {}
  return JSON.stringify(out);
}"""

# 팝업(모달)이 떴는지 찾고 구조를 기록한다
POPUP = r"""() => {
  const L = [];
  const cand = [...document.querySelectorAll('div,section')].filter(el => {
    const c = (el.className || '').toString();
    if (!/dialog|modal|popup|layer|Dialog|Modal|Popup|LUX_.*[Pp]op/.test(c)) return false;
    return el.offsetParent !== null && el.clientHeight > 60;
  });
  L.push(`팝업 후보 ${cand.length}개`);
  cand.slice(0, 6).forEach((el, i) => {
    L.push(`\n  --- 후보 ${i + 1} ---`);
    L.push(`  tag=${el.tagName.toLowerCase()} id=${el.id} class=${(el.className||'').toString().slice(0,80)}`);
    const txt = (el.innerText || '').trim().split('\n').slice(0, 14);
    L.push('  글자: ' + txt.join(' | ').slice(0, 300));
    const rows = el.querySelectorAll('tr, li, [role=row], [class*=row]');
    L.push(`  행 같은 요소 ${rows.length}개`);
    [...rows].slice(0, 8).forEach((r, j) => {
      L.push(`    행${j}: class=${(r.className||'').toString().slice(0,50)}`
             + ` 글자=${(r.innerText||'').trim().replace(/\n/g,' / ').slice(0,70)}`);
    });
  });
  return L.join('\n');
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  코드로 입력하기 + 글자 유실 막기")
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
            say("전표 목록을 못 찾았습니다. 줄을 클릭하고 다시 실행해주세요.")
            raise SystemExit

        say("===== 계정 칸의 편집 가능 여부 =====")
        for f, info in data["colInfo"].items():
            say(f"  {f}: {json.dumps(info, ensure_ascii=False)}")

        pairs = data["pairs"]
        say(f"\n===== 이 화면에서 확인된 계정 이름-코드 짝 {len(pairs)}개 =====")
        for name, code in sorted(pairs.items())[:25]:
            say(f"  {code}  {name}")

        targets = data["targets"]
        say(f"\n===== 미추천 {len(targets)}건 =====")
        say("  줄번호  거래처                    차변           대변")
        for t in targets[:15]:
            cha = t["chaName"] if t["chaCode"] else "(비어있음)"
            dae = t["daeName"] if t["daeCode"] else "(비어있음)"
            say(f"  {t['row']:6d}  {str(t['trade'])[:22]:<24} {cha:<14} {dae}")

        print()
        row_in = input("  시험할 줄 번호 >>> ").strip()
        if not row_in.isdigit():
            raise SystemExit
        row = int(row_in)
        pick = next((t for t in targets if t["row"] == row), None)
        if pick is None:
            print("  그 줄은 미추천 목록에 없습니다.")
            raise SystemExit

        field = "nm_acctit_cha" if not pick["chaCode"] else "nm_acctit_dae"
        which = "차변" if field == "nm_acctit_cha" else "대변"
        print(f"\n  비어 있는 쪽: {which} ({field})")

        print("\n  무엇을 시도할까요?")
        print("    1 = 계정코드를 이름칸에 입력 (예: 83100)")
        print("    2 = 이름을 통째로 입력 (글자 유실 없이)")
        mode = input("  선택 (1 또는 2) >>> ").strip()
        value = input("  넣을 값 >>> ").strip()
        if not value or mode not in ("1", "2"):
            print("  입력이 없어 멈춥니다.")
            raise SystemExit

        say("")
        say(f"### {row}번째 줄 / {field} <- \"{value}\" (방식 {mode})")
        say("시작: " + page.evaluate(STATE, {"row": row}))

        page.bring_to_front()
        say(page.evaluate(PREP, {"row": row, "field": field}))

        # 키 하나로 편집기를 연다. 그 글자는 곧 통째로 덮어쓴다.
        page.keyboard.press("F2")
        page.wait_for_timeout(300)
        st = json.loads(page.evaluate(STATE, {"row": row}))
        if not st.get("editing"):
            page.keyboard.type(value[0], delay=80)
            page.wait_for_timeout(400)
            st = json.loads(page.evaluate(STATE, {"row": row}))
        say(f"편집기 열림 여부: {st.get('editing')}")

        if not st.get("editing"):
            say("편집기가 열리지 않아 여기서 멈춥니다.")
        else:
            say(page.evaluate(SET_EDIT, {"value": value}))
            page.wait_for_timeout(300)
            say("입력 후: " + page.evaluate(STATE, {"row": row}))

            print("\n  화면을 봐주세요. 팝업이 떴나요? 값이 제대로 보이나요?")
            input("  확인하셨으면 Enter (다음: Enter 키를 보냅니다) >>> ")

            page.keyboard.press("Enter")
            page.wait_for_timeout(800)
            say("Enter 후: " + page.evaluate(STATE, {"row": row}))
            say("")
            say("===== 팝업 확인 =====")
            say(page.evaluate(POPUP))

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
