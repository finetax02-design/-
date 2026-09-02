"""과세를 불공으로 바꾸는 방법을 찾는다. 한 건만, 확인하며.

규칙표가 확정됐다. 62개 거래처가 불공, 사유는 3·4·5 셋뿐이다.
이제 실행을 만들어야 하는데 ty_mth2 칸을 어떻게 바꾸는지 아직 모른다.
계정과목은 F2 팝업이었지만 유형은 다를 수 있고,
불공으로 바꾸면 사유 선택 팝업이 또 뜬다.

위하고 코드에서 미리 본 것
  _onCellEdited 에서 새 값이 54 이고 옛 값이 52 55 가 아니면
      gridView.commit()
      setState({ Mth2Mth54_show: true,
                 tyMth54: 기존 cd_notdedct 가 비었으면 "4" })
  즉 불공 전환은 사유 선택 팝업을 동반한다.

이 스크립트는
  1 규칙표를 읽어 전환 대상을 찾는다
  2 ty_mth2 칸의 편집기 정의를 먼저 확인한다
  3 몇 가지 방법을 하나씩 시도하며 단계마다 값과 팝업을 기록한다

값 확정은 사람이 정한다. 전송(F3)은 부르지 않는다.
"""
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "불공전환시험.txt"

과세 = "51"
불공 = "54"
사유 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

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
        let cols = [];
        try { cols = v.getColumns(); } catch (e) {}
        const names = cols.map(c => String(c.name || c.fieldName || ''));
        if (names.includes('nm_acctit_cha')) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          const info = {};
          for (const f of ['ty_mth2', 'cd_notdedct', 'ty_mth', 'ty_trade']) {
            const c = cols.find(x => String(x.name || x.fieldName) === f);
            info[f] = c ? { editable: c.editable, readOnly: c.readOnly, visible: c.visible,
                            editor: c.editor, editorOptions: c.editorOptions,
                            values: c.values, labels: c.labels, button: c.button,
                            lookupDisplay: c.lookupDisplay } : null;
          }
          let src = window.__dp || v;
          let rows = [];
          try { const n = src.getRowCount(); rows = n ? (src.getJsonRows(0, n - 1) || []) : []; }
          catch (e) {}
          return JSON.stringify({ ok: true, rows: rows, colInfo: info });
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

PREP = r"""(args) => {
  const g = window.__g;
  const L = [];
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'ty_mth2', fieldName: 'ty_mth2' });
        L.push('커서: ' + JSON.stringify(g.getCurrent())); }
  catch (e) { L.push('setCurrent 오류: ' + String(e).slice(0, 130)); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  try { L.push('편집중=' + g.isItemEditing()); } catch (e) {}
  return L.join('\n');
}"""

SETVAL = r"""(args) => {
  const g = window.__g;
  const L = [];
  try { g.setValue(args.row, 'ty_mth2', args.value); L.push('setValue(ty_mth2, ' + args.value + ')'); }
  catch (e) { L.push('setValue 오류: ' + String(e).slice(0, 140)); }
  let ci = -1;
  try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === 'ty_mth2'); } catch (e) {}
  try { const r = g.onCellEdited(g, args.row, args.row, ci); L.push('onCellEdited → ' + r); }
  catch (e) { L.push('onCellEdited 오류: ' + String(e).slice(0, 180)); }
  return L.join('\n');
}"""

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  const out = {};
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    out.ty_mth2 = r.ty_mth2; out.cd_notdedct = r.cd_notdedct;
    out.status = r.ty_jungstat; out.trade = r.nm_trade;
  } catch (e) { out.error = String(e).slice(0, 100); }
  try { out.editing = g.isItemEditing(); } catch (e) {}
  return JSON.stringify(out);
}"""

# 불공제 사유 팝업이 떴는지 찾는다
POPUP = r"""() => {
  const L = [];
  const desc = el => {
    const a = [];
    for (const at of el.attributes) { if (at.name !== 'style') a.push(`${at.name}="${at.value.slice(0,40)}"`); }
    return `<${el.tagName.toLowerCase()} ${a.join(' ')}>`;
  };
  const boxes = [...document.querySelectorAll('div,section,dialog')].filter(el => {
    if (el.offsetParent === null) return false;
    if (el.clientHeight < 80 || el.clientWidth < 180) return false;
    const c = (el.className || '').toString();
    const t = (el.innerText || '');
    return /dialog|modal|popup|layer/i.test(c) || /불공|사유|확인\(enter\)|취소\(esc\)/.test(t);
  });
  boxes.sort((a, b) => (a.clientHeight * a.clientWidth) - (b.clientHeight * b.clientWidth));
  L.push(`팝업 후보 ${boxes.length}개`);
  for (const box of boxes.slice(0, 3)) {
    L.push('');
    L.push('--- ' + desc(box) + ` (${box.clientWidth}x${box.clientHeight}) ---`);
    L.push('  글자: ' + (box.innerText || '').trim().split('\n').slice(0, 20).join(' | ').slice(0, 400));
    [...box.querySelectorAll('input,select')].slice(0, 12).forEach((el, i) => {
      L.push(`  입력${i}: ${desc(el)} 값="${el.value}"`);
    });
    [...box.querySelectorAll('button,[class*=btn]')].filter(el => el.offsetParent !== null)
      .slice(0, 20).forEach((el, i) => {
        const t = (el.innerText || el.value || '').trim().slice(0, 24);
        if (t) L.push(`  버튼${i}: "${t}" ${desc(el)}`);
      });
    const rg = [...box.querySelectorAll('[class*=realgrid],[id*=GRID],[id*=CODEHELP]')];
    if (rg.length) L.push('  그리드 흔적: ' + rg.slice(0, 4).map(desc).join(' '));
  }
  return L.join('\n');
}"""

lines = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 66)
print("  과세 → 불공 전환 방법 찾기 (한 건)")
print("=" * 66)
print()
if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    print("  24_불공규칙.bat 을 먼저 실행해주세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if r.get("판정") == "불공" and r.get("적용", "").strip().upper() == "Y":
            rules[r["사업자번호"].strip()] = r
print(f"  규칙표: 불공 적용 거래처 {len(rules)}곳")
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 진행하세요.")
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

        data = json.loads(page.evaluate(GRAB))
        if not data.get("ok"):
            say(f"  {data.get('reason')}")
            raise SystemExit
        rows = data["rows"]

        say("===== ty_mth2 칸 정의 — 어떻게 바꿔야 하는지의 열쇠 =====")
        for f, info in data["colInfo"].items():
            say(f"  {f}: {json.dumps(info, ensure_ascii=False)}")

        targets = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            biz = str(r.get("no_bisocial") or "")
            if biz in rules:
                targets.append((i, r, rules[biz]))
        say("")
        say(f"===== 전환 대상 {len(targets)}건 =====")
        for n, (i, r, rule) in enumerate(targets[:20]):
            say(f"  [{n:2d}] {i:4d}행 {str(r.get('nm_trade'))[:20]:<22}"
                f" {str(r.get('nm_good'))[:22]:<24} 사유={rule['사유코드']} {rule['사유이름']}")
        if not targets:
            say("전환할 건이 없습니다.")
            raise SystemExit

        sel = input("\n  시험할 항목 번호 >>> ").strip()
        if not sel.isdigit() or int(sel) >= len(targets):
            raise SystemExit
        row, rec, rule = targets[int(sel)]

        say("")
        say(f"### {row}행 {rec.get('nm_trade')} / 사유 {rule['사유코드']} {rule['사유이름']}")
        say("시작: " + page.evaluate(STATE, {"row": row}))
        say(page.evaluate(PREP, {"row": row}))

        print()
        print("  어떤 방법을 시도할까요?")
        print("    1 = F2 (계정과목처럼 코드도움이 뜨는지)")
        print("    2 = setValue(54) + onCellEdited (위하고 편집 흐름 직접 호출)")
        print("    3 = 키보드로 '54' 입력")
        mode = input("  선택 >>> ").strip()

        if mode == "1":
            page.keyboard.press("F2")
        elif mode == "2":
            say(page.evaluate(SETVAL, {"row": row, "value": 불공}))
        elif mode == "3":
            page.keyboard.type("54", delay=80)
        else:
            raise SystemExit
        page.wait_for_timeout(1500)

        say("")
        say("시도 후: " + page.evaluate(STATE, {"row": row}))
        say("")
        say("===== 화면에 뜬 팝업 =====")
        say(page.evaluate(POPUP))

        print()
        print("  화면을 봐주세요. 불공제 사유를 고르는 팝업이 떴나요?")
        input("  확인하셨으면 Enter >>> ")
        say("")
        say("확인 후: " + page.evaluate(STATE, {"row": row}))
        say("")
        say("===== 그 시점의 팝업 =====")
        say(page.evaluate(POPUP))

        print()
        print("  팝업이 떠 있으면 esc 로 닫습니다. 확정하지 않습니다.")
        if input("  esc 로 닫을까요? (y) >>> ").strip().lower() == "y":
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            say("esc 후: " + page.evaluate(STATE, {"row": row}))

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
print("  전송(F3)은 누르지 않았습니다.")
print("=" * 66)
print()
input("  창을 닫으려면 Enter >>> ")
