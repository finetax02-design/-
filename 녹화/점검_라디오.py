"""라디오가 왜 안 눌리는지 마지막으로 확인한다. 원인만 본다.

여섯 번 실패했다. 좌표도 맞고 요소도 맞는데 선택이 안 바뀐다.
남은 가능성은 두 가지다.
  1 그 좌표에 다른 것이 덮여 있어 클릭이 엉뚱한 요소로 간다
  2 조상 어딘가에 visibility:hidden 이 걸려 실제로는 눌릴 수 없다

document.elementFromPoint 로 그 자리에 실제로 무엇이 있는지 보고,
조상을 거슬러 올라가며 화면 표시 속성을 확인한다.

값을 바꾸지 않는다. 팝업은 esc 로 닫는다.
단, esc 는 기본값 4 를 남기므로 유형도 과세로 되돌린다.
"""
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "라디오점검.txt"

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
          catch (e) { return JSON.stringify({ ok: false }); }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false });
}"""

TO_불공 = r"""(args) => {
  const g = window.__g;
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'ty_mth2', fieldName: 'ty_mth2' }); } catch (e) {}
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  try { g.setValue(args.row, 'ty_mth2', '54'); } catch (e) { return '실패'; }
  let ci = -1;
  try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === 'ty_mth2'); } catch (e) {}
  try { g.onCellEdited(g, args.row, args.row, ci); } catch (e) {}
  return '불공으로 설정';
}"""

CHECK = r"""(args) => {
  const want = String(args.code);
  const L = [];
  const 사유패턴 = /^[0-9AB][.\s]/;
  const labelOf = el => {
    for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
      const t = (n.innerText || '').trim();
      if (t && t.length < 60) return { node: n, text: t };
    }
    return null;
  };
  const desc = el => {
    if (!el) return 'null';
    const a = [];
    for (const at of el.attributes || []) { if (at.name !== 'style') a.push(`${at.name}="${at.value.slice(0,30)}"`); }
    return `<${el.tagName.toLowerCase()} ${a.join(' ')}>`;
  };

  let hit = null;
  for (const el of document.querySelectorAll('input[type=radio]')) {
    const lab = labelOf(el);
    if (!lab || !사유패턴.test(lab.text)) continue;
    const rr = el.getBoundingClientRect();
    const lr = lab.node.getBoundingClientRect();
    if (rr.width < 1 && lr.width < 1) continue;
    if (lab.text.startsWith(want + '.') || lab.text.startsWith(want + ' ')) { hit = { el: el, lab: lab }; break; }
  }
  if (!hit) return '목표 라디오를 못 찾음';

  const lr = hit.lab.node.getBoundingClientRect();
  const cx = lr.x + lr.width / 2, cy = lr.y + lr.height / 2;
  L.push(`목표 라벨: ${desc(hit.lab.node)}`);
  L.push(`  rect=(${Math.round(lr.x)},${Math.round(lr.y)}) ${Math.round(lr.width)}x${Math.round(lr.height)}`);
  L.push(`  가운데 좌표 (${Math.round(cx)},${Math.round(cy)})`);

  L.push('');
  L.push('--- 그 자리에 실제로 있는 것 ---');
  for (const [name, x, y] of [['가운데', cx, cy], ['왼쪽 아이콘', lr.x + 7, cy], ['글자', lr.x + 40, cy]]) {
    const at = document.elementFromPoint(x, y);
    const 내부 = at && (at === hit.lab.node || hit.lab.node.contains(at));
    L.push(`  ${name} (${Math.round(x)},${Math.round(y)}) → ${desc(at)}  ${내부 ? '[목표 안쪽]' : '[다른 요소!]'}`);
  }

  L.push('');
  L.push('--- 조상 화면 표시 속성 ---');
  let n = hit.lab.node;
  for (let i = 0; n && i < 8; n = n.parentElement, i++) {
    const cs = getComputedStyle(n);
    const r = n.getBoundingClientRect();
    L.push(`  [${i}] ${desc(n).slice(0, 90)}`);
    L.push(`      visibility=${cs.visibility} display=${cs.display} opacity=${cs.opacity}`
           + ` pointerEvents=${cs.pointerEvents} overflow=${cs.overflow}`
           + ` rect=${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  return L.join('\n');
}"""

REVERT = r"""(args) => {
  const g = window.__g;
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'ty_mth2', fieldName: 'ty_mth2' }); } catch (e) {}
  try { g.setValue(args.row, 'ty_mth2', '51'); } catch (e) { return '되돌리기 실패'; }
  let ci = -1;
  try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === 'ty_mth2'); } catch (e) {}
  try { g.onCellEdited(g, args.row, args.row, ci); } catch (e) {}
  return '과세로 되돌림';
}"""

lines = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 66)
print("  라디오가 왜 안 눌리는지 확인 (원인만)")
print("=" * 66)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 진행하세요.")
print()
input("  준비되었으면 Enter >>> ")

rules = {}
if RULES.exists():
    with RULES.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("사유코드") or "").strip()
            if r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y") and code:
                rules[r["사업자번호"].strip()] = code

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages]
        page = next((pg for pg in pages if "smarta.wehago.com" in pg.url), None)
        if page is None:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit
        page.bring_to_front()

        data = json.loads(page.evaluate(GRAB))
        rows = data.get("rows") or []
        if not rows:
            say("화면에 자료가 없습니다. 조회를 먼저 해주세요.")
            raise SystemExit

        row = code = None
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != "51":
                continue
            c = rules.get(str(r.get("no_bisocial") or ""))
            if c:
                row, code = i, c
                say(f"대상: {i}행 {r.get('nm_trade')} / 사유 {c}")
                break
        if row is None:
            say("전환 대상이 없습니다.")
            raise SystemExit

        say(page.evaluate(TO_불공, {"row": row}))
        page.wait_for_timeout(1400)
        say("")
        say(page.evaluate(CHECK, {"code": code}))

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        say("")
        say(page.evaluate(REVERT, {"row": row}))

        browser.close()
except SystemExit:
    pass
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 66)
print(f"  저장됨: {OUT}")
print("=" * 66)
print()
input("  창을 닫으려면 Enter >>> ")
