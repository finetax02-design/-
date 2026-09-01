"""계정과목 코드도움 팝업의 구조를 읽는다.

F2 는 인라인 편집기가 아니라 계정과목 코드도움 팝업을 여는 키였다.
화면 오른쪽 안내에 그렇게 적혀 있었는데 놓쳤다.

그런데 이게 오히려 낫다. 그 팝업은 캔버스가 아니라 보통의 HTML 이라
검색칸에 입력하고 원하는 줄을 클릭하면 된다.
계정과목 이름이 겹쳐도 정확한 것을 지정할 수 있다.

이 스크립트는
  1 미추천 줄로 커서를 옮기고 F2 로 팝업을 연다
  2 팝업 안의 입력칸 버튼 탭 목록 행을 모두 기록한다
  3 검색칸에 값을 넣어보고 목록이 어떻게 걸러지는지 본다

값을 확정하지 않는다. 팝업은 esc 로 닫는다.
전송(F3)은 누르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
OUT = HERE / "팝업구조.txt"

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
        let names = [];
        try { names = v.getColumns().map(c => String(c.name || c.fieldName || '')); } catch (e) {}
        if (names.includes('nm_acctit_cha')) {
          window.__g = v;
          try { window.__dp = v.getDataSource(); } catch (e) { window.__dp = null; }
          const src = window.__dp || v;
          const count = src.getRowCount();
          const rows = src.getJsonRows(0, count - 1) || [];
          const targets = [];
          rows.forEach((r, i) => {
            if (String(r.ty_jungstat) !== '5') return;
            targets.push({ row: i, trade: r.nm_trade,
                           chaCode: r.cd_acctit_cha, daeCode: r.cd_acctit_dae,
                           chaName: r.nm_acctit_cha, daeName: r.nm_acctit_dae });
          });
          return JSON.stringify({ ok: true, targets: targets });
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

# 팝업 안을 샅샅이 기록한다
DUMP = r"""() => {
  const L = [];
  const log = s => L.push(String(s));
  const desc = el => {
    const a = [];
    for (const at of el.attributes) {
      if (at.name === 'style') continue;
      a.push(`${at.name}="${at.value.slice(0, 50)}"`);
    }
    return `<${el.tagName.toLowerCase()} ${a.join(' ')}>`;
  };

  // 화면에 보이는 팝업 컨테이너를 찾는다
  const boxes = [...document.querySelectorAll('div,section,dialog')].filter(el => {
    if (el.offsetParent === null && el.tagName !== 'DIALOG') return false;
    if (el.clientHeight < 120 || el.clientWidth < 200) return false;
    const c = (el.className || '').toString();
    const t = (el.innerText || '');
    return /dialog|modal|popup|layer|Dialog|Modal|Popup/.test(c)
        || (/확인\(enter\)|취소\(esc\)/.test(t) && el.clientHeight < 900);
  });
  log(`팝업 후보 ${boxes.length}개`);
  if (!boxes.length) { log('팝업이 안 보입니다.'); return L.join('\n'); }

  // 가장 안쪽(작은) 것부터 본다
  boxes.sort((a, b) => (a.clientHeight * a.clientWidth) - (b.clientHeight * b.clientWidth));
  const box = boxes[0];
  log('');
  log('=== 선택한 팝업 ===');
  log('  ' + desc(box));
  log(`  크기 ${box.clientWidth}x${box.clientHeight}`);

  log('');
  log('--- 입력칸 ---');
  [...box.querySelectorAll('input,textarea')].forEach((el, i) => {
    log(`  ${i}: ${desc(el)}  값="${el.value}"  보임=${el.offsetParent !== null}`);
  });

  log('');
  log('--- 버튼 ---');
  [...box.querySelectorAll('button,a[role=button],[class*=btn],[class*=Btn]')]
    .filter(el => el.offsetParent !== null)
    .slice(0, 30)
    .forEach((el, i) => {
      const t = (el.innerText || el.value || '').trim().slice(0, 24);
      if (t) log(`  ${i}: "${t}"  ${desc(el)}`);
    });

  log('');
  log('--- 목록 (표 또는 행 반복) ---');
  const tables = [...box.querySelectorAll('table')];
  log(`  table ${tables.length}개`);
  tables.slice(0, 3).forEach((t, ti) => {
    log(`  [table ${ti}] ${desc(t)} 행 ${t.rows.length}개`);
    [...t.rows].slice(0, 12).forEach((r, ri) => {
      const cells = [...r.cells].map(c => (c.innerText || '').trim().slice(0, 20));
      log(`    행${ri} ${desc(r)} : ${cells.join(' | ')}`);
    });
  });

  // 표가 아니라 div 반복인 경우
  const lists = [...box.querySelectorAll('ul,[role=listbox],[class*=list],[class*=List]')]
    .filter(el => el.children.length >= 3).slice(0, 3);
  log(`  목록형 컨테이너 ${lists.length}개`);
  lists.forEach((l, li) => {
    log(`  [목록 ${li}] ${desc(l)} 자식 ${l.children.length}개`);
    [...l.children].slice(0, 12).forEach((c, ci) => {
      log(`    ${ci}: ${desc(c)} "${(c.innerText || '').trim().replace(/\n/g, ' / ').slice(0, 50)}"`);
    });
  });

  // 팝업 안에 또 RealGrid 가 있을 수도 있다
  const rg = [...box.querySelectorAll('[class*=realgrid],[id*=GRID]')];
  log(`  RealGrid 흔적 ${rg.length}개: ` + rg.slice(0, 5).map(desc).join(' '));

  return L.join('\n');
}"""

lines: list[str] = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 62)
print("  계정과목 코드도움 팝업 구조 읽기")
print("=" * 62)
print()
print("  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 실행하세요.")
print("  팝업은 마지막에 esc 로 닫습니다. 값은 확정하지 않습니다.")
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

        targets = data["targets"]
        say(f"미추천 {len(targets)}건")
        for t in targets[:12]:
            cha = t["chaName"] if t["chaCode"] else "(비어있음)"
            dae = t["daeName"] if t["daeCode"] else "(비어있음)"
            say(f"  {t['row']:6d}  {str(t['trade'])[:22]:<24} 차변={cha:<12} 대변={dae}")

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
        say("")
        say(f"### {row}번째 줄 / {field}")
        page.bring_to_front()
        say(page.evaluate(PREP, {"row": row, "field": field}))

        print("\n  F2 로 코드도움 팝업을 엽니다...")
        page.keyboard.press("F2")
        page.wait_for_timeout(1200)

        say("")
        say("===== 팝업 구조 =====")
        say(page.evaluate(DUMP))

        print()
        keyword = input("  팝업 검색칸에 넣어볼 말 (예: 의약품, 없으면 Enter) >>> ").strip()
        if keyword:
            page.keyboard.type(keyword, delay=60)
            page.wait_for_timeout(900)
            say("")
            say(f"===== '{keyword}' 입력 후 팝업 =====")
            say(page.evaluate(DUMP))

        print("\n  팝업을 닫습니다 (esc). 값은 확정하지 않습니다.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

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
print("  계정과목 이름과 화면 구조뿐이라 보내주셔도 안전합니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
