"""규칙표대로 불공 전환 대상 줄에 체크를 넣는다. 그리고 일괄변경 화면 구조를 뜬다.

불공제 사유 라디오를 하나씩 누르는 방식은 여섯 번 실패했다.
점검해보니 요소도 좌표도 정상이고 덮인 것도 없는데 선택이 안 바뀐다.
그 부품 내부에서 되돌리는 것으로 보이며 더 파도 얻을 게 없다.

위하고에 여러 건을 골라 한 번에 유형과 불공사유를 바꾸는 기능이 있다.
그쪽으로 간다. 체크박스는 그리드가 관리하므로 우리가 다룰 수 있고,
54건이면 라디오를 54번 누르는 대신 일괄변경 한 번으로 끝난다.

이 스크립트는 두 가지를 한 번에 한다.
  1 규칙표대로 대상 줄에 체크를 넣는다
  2 사용자가 일괄변경 화면을 열면 그 구조를 기록한다

체크만 넣고 값은 바꾸지 않는다. 전송(F3)도 부르지 않는다.
"""
import collections
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "일괄변경구조.txt"

과세 = "51"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

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
          const has = m => { try { return typeof v[m] === 'function'; } catch (e) { return false; } };
          let src = window.__dp || v;
          let rows = [];
          try { const n = src.getRowCount(); rows = n ? (src.getJsonRows(0, n - 1) || []) : []; }
          catch (e) {}
          return JSON.stringify({ ok: true, rows: rows,
            api: ['checkItem','checkItems','checkAll','setCheckedRows','getCheckedRows',
                  'getCheckedItems','getCheckedItemIndices','resetCheckables','applyCheckables',
                  'setCheckBar','isCheckedItem'].filter(has) });
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

# 대상 줄에 체크를 넣는다. 그리드마다 쓸 수 있는 메서드가 달라 순서대로 시도한다.
CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  const rows = args.rows;
  const L = [];
  // 먼저 전부 해제한다
  for (const m of ['checkAll', 'resetCheckables']) {
    try { if (typeof g[m] === 'function') { g[m](false); L.push(m + '(false) 로 초기화'); break; } }
    catch (e) { L.push(m + ' 오류: ' + String(e).slice(0, 80)); }
  }
  let done = '';
  try {
    if (typeof g.checkItems === 'function') { g.checkItems(rows, true); done = 'checkItems'; }
    else if (typeof g.setCheckedRows === 'function') { g.setCheckedRows(rows, true); done = 'setCheckedRows'; }
    else if (typeof g.checkItem === 'function') {
      for (const r of rows) g.checkItem(r, true);
      done = 'checkItem 반복';
    }
  } catch (e) { L.push('체크 오류: ' + String(e).slice(0, 140)); }
  L.push(done ? `${done} 로 ${rows.length}줄 체크` : '체크할 방법이 없음');

  let after = [];
  try {
    if (typeof g.getCheckedItemIndices === 'function') after = g.getCheckedItemIndices() || [];
    else if (typeof g.getCheckedRows === 'function') after = g.getCheckedRows() || [];
  } catch (e) {}
  L.push(`실제로 체크된 줄 ${after.length}개`);
  return JSON.stringify({ log: L, checked: after.slice(0, 60) });
}"""

# 일괄변경 화면이 열리면 그 구조를 기록한다
DUMP = r"""() => {
  const L = [];
  const desc = el => {
    const a = [];
    for (const at of el.attributes || []) { if (at.name !== 'style') a.push(`${at.name}="${at.value.slice(0,40)}"`); }
    return `<${el.tagName.toLowerCase()} ${a.join(' ')}>`;
  };
  const boxes = [...document.querySelectorAll('div,section,dialog')].filter(el => {
    if (el.offsetParent === null) return false;
    if (el.clientHeight < 100 || el.clientWidth < 200) return false;
    const c = (el.className || '').toString();
    const t = (el.innerText || '');
    return /dialog|modal|popup|layer/i.test(c) || /일괄|변경항목|변경내용|변경 전|변경가능/.test(t);
  });
  boxes.sort((a, b) => (a.clientHeight * a.clientWidth) - (b.clientHeight * b.clientWidth));
  L.push(`후보 ${boxes.length}개`);
  for (const box of boxes.slice(0, 3)) {
    L.push('');
    L.push('=== ' + desc(box) + ` (${box.clientWidth}x${box.clientHeight}) ===`);
    L.push('글자: ' + (box.innerText || '').trim().split('\n').slice(0, 25).join(' | ').slice(0, 500));
    L.push('');
    [...box.querySelectorAll('input,select,textarea')].slice(0, 20).forEach((el, i) => {
      L.push(`  입력${i}: ${desc(el)} 값="${el.value}" 보임=${el.offsetParent !== null}`);
    });
    [...box.querySelectorAll('button,[class*=btn],[class*=Btn]')]
      .filter(el => el.offsetParent !== null).slice(0, 25).forEach((el, i) => {
        const t = (el.innerText || el.value || '').trim().slice(0, 26);
        if (t) L.push(`  버튼${i}: "${t}" ${desc(el)}`);
      });
    [...box.querySelectorAll('table')].slice(0, 4).forEach((t, ti) => {
      L.push(`  [표${ti}] 행 ${t.rows.length}개`);
      [...t.rows].slice(0, 10).forEach((r, ri) => {
        L.push(`    ${ri}: ` + [...r.cells].map(c => (c.innerText || '').trim().slice(0, 18)).join(' | '));
      });
    });
    const rg = [...box.querySelectorAll('[class*=realgrid],[id*=GRID],[id*=CODEHELP]')];
    if (rg.length) L.push('  그리드: ' + rg.slice(0, 4).map(desc).join(' '));
  }
  return L.join('\n');
}"""

lines = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 70)
print("  일괄변경으로 가기 - 대상 줄 체크 + 화면 구조 확인")
print("=" * 70)
print()
if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = (r.get("사유코드") or "").strip()
        if r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y") and code in 사유이름:
            rules[r["사업자번호"].strip()] = code
print(f"  규칙표 {len(rules)}곳")
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
        say(f"전표 {len(rows)}건")
        say(f"쓸 수 있는 체크 관련 기능: {', '.join(data['api']) or '없음'}")
        if not rows:
            say("화면에 자료가 없습니다. 조회를 먼저 해주세요.")
            raise SystemExit

        # 사유가 같은 것끼리 묶는다. 일괄변경은 사유를 하나만 고르므로
        # 사유별로 나눠서 처리해야 한다.
        by_code = collections.defaultdict(list)
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            code = rules.get(str(r.get("no_bisocial") or ""))
            if code:
                by_code[code].append(i)

        total = sum(len(v) for v in by_code.values())
        say("")
        say(f"불공으로 바꿀 건 {total}건")
        for code, idx in sorted(by_code.items()):
            say(f"  사유 {code} {사유이름[code]}: {len(idx)}건")
        if not total:
            say("바꿀 건이 없습니다.")
            raise SystemExit

        say("")
        say("일괄변경은 사유를 하나만 고르므로 사유별로 나눠서 해야 합니다.")
        code = input("\n  먼저 체크할 사유 (3/4/5) >>> ").strip()
        if code not in by_code:
            print(f"  사유 {code} 대상이 없습니다.")
            raise SystemExit

        res = json.loads(page.evaluate(CHECK_ROWS, {"rows": by_code[code]}))
        say("")
        for line in res["log"]:
            say("  " + line)
        say(f"  체크된 줄 번호(앞 60개): {res['checked']}")

        print()
        print("  " + "-" * 62)
        print("   화면을 봐주세요. 대상 줄에 체크 표시가 들어갔나요?")
        print()
        print("   들어갔으면, 위하고의 일괄변경 기능을 열어주세요.")
        print("   (유형을 불공으로 바꾸고 사유를 고르는 그 화면입니다)")
        print("   열기만 하시고 적용은 누르지 마세요.")
        print("  " + "-" * 62)
        print()
        input("  일괄변경 화면을 여셨으면 Enter >>> ")

        say("")
        say("===== 일괄변경 화면 구조 =====")
        say(page.evaluate(DUMP))

        browser.close()
except SystemExit:
    pass
except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 70)
print(f"  저장됨: {OUT}")
print("  체크만 넣었고 값은 바꾸지 않았습니다.")
print("=" * 70)
print()
input("  창을 닫으려면 Enter >>> ")
