"""과세 -> 불공 일괄변환. 불공제사유까지 한 번에 바꾼다.

불공제사유 라디오는 어떤 방법으로도 눌리지 않았다. 여섯 번 실패했다.
그래서 라디오를 아예 건드리지 않는 길로 간다.

위하고 일괄변경의 원리는 이렇다.
  1 사유가 정확히 들어간 불공 줄 하나를 클릭해서 현재 줄로 만든다  (본보기 줄)
  2 바꿀 줄들을 전부 체크한다
  3 일괄변경 > 전체일괄변경 을 누른다
  4 확인창에 '과세유형 | 불공 | 몇건' 이 뜨면 확인
그러면 체크한 줄들이 본보기 줄과 같은 불공 + 같은 사유로 바뀐다.
라디오를 누를 일이 없다.

일괄변경은 본보기가 하나뿐이라 사유도 하나씩만 처리된다.
그래서 사유 3, 4, 5 를 한 번에 한 사유씩 돌린다.

안전장치
  - 본보기 줄은 사용자가 눈으로 확인한 뒤에만 쓴다
  - 체크한 건수와 확인창의 건수가 다르면 멈춘다
  - 바꾼 뒤 실제로 유형과 사유가 맞게 들어갔는지 다시 읽어 대조한다
  - 전송(F3)은 절대 부르지 않는다
"""
import collections
import csv
import json
import re
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "일괄변환기록.txt"

과세 = "51"
불공 = "54"
사유이름 = {"3": "비영업용승용차유지", "4": "면세사업관련", "5": "공통매입세액안분"}

GRAB = r"""() => {
  // 같은 열 구성을 가진 그리드가 여러 개일 수 있다. 화면에 안 보이는 빈 것도 있다.
  // 그래서 하나만 찾고 멈추지 않고 전부 모은 뒤 자료가 가장 많은 것을 고른다.
  const gridish = o => {
    if (!o || (typeof o !== 'object' && typeof o !== 'function')) return false;
    try { return typeof o.getColumns === 'function' && typeof o.getValues === 'function'; }
    catch (e) { return false; }
  };
  const found = [];
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
        if (names.includes('nm_acctit_cha')) found.push(v);
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  if (!found.length) return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });

  const 후보 = [];
  let best = null, bestN = -1;
  for (const g of found) {
    let src = g, n = 0, err = '';
    try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
    try { n = src.getRowCount() || 0; } catch (e) { err = String(e).slice(0, 60); }
    후보.push({ 건수: n, 오류: err });
    if (n > bestN) { bestN = n; best = { g: g, src: src, n: n }; }
  }
  if (!best || best.n <= 0) {
    return JSON.stringify({ ok: false, reason: '전표 목록은 찾았으나 자료가 없음', 후보: 후보 });
  }
  window.__g = best.g;
  let rows = [], err = '';
  try { rows = best.src.getJsonRows(0, best.n - 1) || []; }
  catch (e) { err = String(e).slice(0, 120); }
  return JSON.stringify({ ok: rows.length > 0, rows: rows, 후보: 후보,
                          reason: rows.length ? '' : ('자료를 읽지 못함 ' + err) });
}"""

# 본보기 줄을 현재 줄로 만든다. 사용자가 손으로 클릭하는 것과 같은 상태.
SET_CURRENT = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  let src = g;
  try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
  let r = null;
  try { r = src.getJsonRows(args.row, args.row)[0]; } catch (e) {}
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(r.ty_mth2) !== args.want_ty || String(r.cd_notdedct) !== args.want_cd) {
    return JSON.stringify({ ok: false,
      reason: `본보기 줄이 달라짐 (유형 ${r.ty_mth2} 사유 ${r.cd_notdedct})` });
  }
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'nm_trade', fieldName: 'nm_trade' }); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setCurrent ' + String(e).slice(0, 90) }); }
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  let cur = null;
  try { cur = g.getCurrent(); } catch (e) {}
  return JSON.stringify({ ok: true, 거래처: r.nm_trade, 현재: cur && cur.itemIndex });
}"""

CHECK_ROWS = r"""(args) => {
  const g = window.__g;
  const L = [];
  for (const m of ['checkAll', 'resetCheckables']) {
    try { if (typeof g[m] === 'function') { g[m](false); L.push(m + '(false) 로 초기화'); break; } }
    catch (e) { L.push(m + ' 오류: ' + String(e).slice(0, 80)); }
  }
  try {
    if (typeof g.checkItems === 'function') g.checkItems(args.rows, true);
    else if (typeof g.checkItem === 'function') for (const r of args.rows) g.checkItem(r, true);
    else return JSON.stringify({ ok: false, reason: '체크할 방법이 없음', log: L });
  } catch (e) { return JSON.stringify({ ok: false, reason: '체크 오류 ' + String(e).slice(0, 120), log: L }); }
  let after = [];
  try {
    if (typeof g.getCheckedItemIndices === 'function') after = g.getCheckedItemIndices() || [];
    else if (typeof g.getCheckedRows === 'function') after = g.getCheckedRows() || [];
  } catch (e) {}
  L.push(`${args.rows.length}줄 체크 요청, 실제 체크 ${after.length}줄`);
  return JSON.stringify({ ok: after.length === args.rows.length, checked: after, log: L,
    reason: after.length === args.rows.length ? '' : '체크된 줄 수가 다릅니다' });
}"""

# 글자가 정확히 일치하는 화면상의 누를 것을 찾는다. 오른쪽 아래에 있는 것을 고른다.
FIND = r"""(args) => {
  const out = [];
  const els = document.querySelectorAll('button, a, li, span, div, [role=button], [role=menuitem]');
  for (const el of els) {
    const t = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    if (t !== args.text) continue;
    // 글자만 가진 가장 안쪽 요소를 고른다
    let inner = true;
    for (const c of el.children) {
      const ct = (c.innerText || c.textContent || '').trim().replace(/\s+/g, ' ');
      if (ct === args.text) { inner = false; break; }
    }
    if (!inner) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    out.push({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               w: Math.round(r.width), h: Math.round(r.height),
               tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 50) });
  }
  return JSON.stringify(out);
}"""

# 열린 확인창의 내용을 읽는다
DIALOG = r"""() => {
  const boxes = [...document.querySelectorAll('div,section,dialog')].filter(el => {
    if (el.offsetParent === null) return false;
    if (el.clientHeight < 80 || el.clientWidth < 200) return false;
    const c = (el.className || '').toString();
    const t = el.innerText || '';
    return (/dialog|modal|popup|layer/i.test(c) || /일괄변경 하시겠|변경항목/.test(t))
           && /변경항목|일괄변경 하시겠/.test(t);
  });
  if (!boxes.length) return JSON.stringify({ ok: false, reason: '확인창을 못 찾음' });
  boxes.sort((a, b) => (a.clientHeight * a.clientWidth) - (b.clientHeight * b.clientWidth));
  const box = boxes[0];
  const text = (box.innerText || '').trim();
  const tables = [];
  for (const t of box.querySelectorAll('table')) {
    for (const r of t.rows) tables.push([...r.cells].map(c => (c.innerText || '').trim()));
  }
  const btns = [];
  for (const el of box.querySelectorAll('button,[class*=btn],[class*=Btn],[role=button]')) {
    if (el.offsetParent === null) continue;
    const t = (el.innerText || el.value || '').trim();
    if (t && t.length <= 20 && !btns.includes(t)) btns.push(t);
  }
  return JSON.stringify({ ok: true, text: text.slice(0, 900), table: tables.slice(0, 12), buttons: btns });
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


def 저장():
    OUT.write_text("\n".join(lines), encoding="utf-8")


def 누르기(page, 글자, 위치="아래"):
    """글자가 정확히 일치하는 것을 찾아 누른다. 여러 개면 아래쪽/오른쪽 것을 고른다."""
    found = json.loads(page.evaluate(FIND, {"text": 글자}))
    if not found:
        return None, f"'{글자}' 를 화면에서 못 찾음"
    if 위치 == "아래":
        found.sort(key=lambda e: (e["y"], e["x"]))
        target = found[-1]
    else:
        found.sort(key=lambda e: (e["y"], e["x"]))
        target = found[0]
    page.mouse.click(target["x"], target["y"])
    page.wait_for_timeout(700)
    return target, ""


print()
print("=" * 72)
print("  과세 -> 불공 일괄변환 (불공제사유까지 한 번에)")
print("=" * 72)
print()

if not RULES.exists():
    print(f"  규칙표가 없습니다: {RULES}")
    print("  24_불공규칙.bat 을 먼저 돌려주세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

rules = {}
with RULES.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = (r.get("사유코드") or "").strip()
        if r.get("판정") == "불공" and (r.get("적용", "").strip().upper() == "Y") and code in 사유이름:
            rules[r["사업자번호"].strip()] = code
print(f"  규칙표 {len(rules)}곳 (사유 3, 4, 5 만)")
print()
print("  전자세금계산서 화면을 띄우고 조회를 마친 상태여야 합니다.")
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "smarta.wehago.com" in pg.url]
        if not pages:
            say("smarta.wehago.com 탭을 찾지 못했습니다.")
            raise SystemExit
        # 위하고 탭이 여러 개 열려 있을 수 있다. 전자세금계산서 화면을 먼저 본다.
        pages.sort(key=lambda pg: "SAAC0103" not in pg.url)
        say(f"위하고 탭 {len(pages)}개를 봅니다.")

        page, rows, data = None, None, None
        for pg in pages:
            꼬리 = pg.url.split("/#/")[-1][:60]
            try:
                d = json.loads(pg.evaluate(GRAB))
            except Exception as e:
                say(f"  탭 {꼬리} : 읽기 실패 {str(e)[:80]}")
                continue
            if d.get("ok") and d.get("rows"):
                page, rows, data = pg, d["rows"], d
                say(f"  탭 {꼬리} : 전표 {len(rows)}건")
                break
            say(f"  탭 {꼬리} : {d.get('reason') or '자료 없음'}"
                + (f" (그리드 {len(d.get('후보', []))}개 건수 "
                   + ",".join(str(c['건수']) for c in d.get('후보', [])) + ")"
                   if d.get('후보') else ""))
        if page is None:
            say("")
            say("자료가 들어 있는 전자세금계산서 탭을 찾지 못했습니다.")
            say("전자세금계산서 화면에서 조회를 한 번 더 누른 뒤 다시 실행해주세요.")
            raise SystemExit
        page.bring_to_front()
        say(f"전표 {len(rows)}건을 읽었습니다.")

        # 사유별로 바꿀 줄과 본보기 줄을 나눈다
        대상 = collections.defaultdict(list)
        본보기 = collections.defaultdict(list)
        for i, r in enumerate(rows):
            ty = str(r.get("ty_mth2") or "")
            cd = str(r.get("cd_notdedct") or "")
            if ty == 불공 and cd in 사유이름:
                본보기[cd].append(i)
            elif ty == 과세:
                code = rules.get(str(r.get("no_bisocial") or ""))
                if code:
                    대상[code].append(i)

        say("")
        say(f"불공으로 바꿀 건 {sum(len(v) for v in 대상.values())}건")
        for code in sorted(사유이름):
            say(f"  사유 {code} {사유이름[code]}: 바꿀 줄 {len(대상.get(code, []))}건"
                f" / 본보기로 쓸 수 있는 줄 {len(본보기.get(code, []))}건")
        if not 대상:
            say("바꿀 건이 없습니다.")
            raise SystemExit

        say("")
        say("일괄변경은 본보기가 하나뿐이라 사유를 하나씩만 바꿉니다.")
        code = input("\n  이번에 처리할 사유 (3/4/5) >>> ").strip()
        if code not in 대상 or not 대상[code]:
            print(f"  사유 {code} 로 바꿀 줄이 없습니다.")
            raise SystemExit
        if not 본보기.get(code):
            print()
            print(f"  화면에 사유 {code} 인 불공 줄이 하나도 없습니다.")
            print("  일괄변경은 본보기 줄을 그대로 베끼는 방식이라 본보기가 꼭 필요합니다.")
            print(f"  아무 줄이나 하나를 손으로 불공 + 사유 {code} 로 바꾼 뒤 다시 실행해주세요.")
            raise SystemExit

        tmpl = 본보기[code][0]
        t = rows[tmpl]
        say("")
        say(f"본보기 줄: {tmpl + 1}번째  {t.get('s_date')}  {t.get('nm_trade')}"
            f"  유형 {t.get('ty_mth2')}  사유 {t.get('cd_notdedct')}")
        say("")
        say(f"바꿀 줄 {len(대상[code])}건:")
        for i in 대상[code][:40]:
            r = rows[i]
            say(f"  {i + 1:>4}번째  {r.get('s_date')}  {r.get('nm_trade')}"
                f"  {r.get('mn_mnam')}  {r.get('nm_good')}")
        if len(대상[code]) > 40:
            say(f"  ... 그 밖에 {len(대상[code]) - 40}건")

        print()
        print("  먼저 1건만 해보고 화면을 확인한 뒤 나머지를 하시겠습니까?")
        시험 = input("  1건만 먼저 (y/n, 처음이면 y) >>> ").strip().lower() != "n"
        묶음 = 대상[code][:1] if 시험 else 대상[code]

        # 1 본보기 줄을 현재 줄로
        res = json.loads(page.evaluate(SET_CURRENT,
                                       {"row": tmpl, "want_ty": 불공, "want_cd": code}))
        if not res.get("ok"):
            say(f"본보기 줄 지정 실패: {res.get('reason')}")
            raise SystemExit
        say("")
        say(f"본보기 줄을 현재 줄로 두었습니다: {res.get('거래처')}")

        # 2 바꿀 줄 체크
        res = json.loads(page.evaluate(CHECK_ROWS, {"rows": 묶음}))
        for line in res.get("log", []):
            say("  " + line)
        if not res.get("ok"):
            say(f"체크 실패: {res.get('reason')}")
            raise SystemExit

        첫줄 = rows[묶음[0]]
        print()
        print("  " + "-" * 66)
        print("   화면에서 두 가지를 확인해주세요. 둘은 역할이 다릅니다.")
        print()
        print(f"   1) 본보기 줄  {tmpl + 1}번째  {t.get('s_date')} {t.get('nm_trade')}")
        print(f"      -> 파란색으로 '선택' 되어 있어야 합니다. 체크는 아닙니다.")
        print(f"      -> 이 줄의 불공 + 사유 {code} 를 그대로 베낍니다.")
        print()
        print(f"   2) 바꿀 줄  {len(묶음)}건  (첫 줄: {묶음[0] + 1}번째"
              f" {첫줄.get('s_date')} {첫줄.get('nm_trade')})")
        print(f"      -> 체크표시가 들어가 있어야 합니다. 이 줄들이 불공으로 바뀝니다.")
        print("  " + "-" * 66)
        if input("\n  이대로 맞으면 y, 아니면 Enter >>> ").strip().lower() != "y":
            say("사용자가 중단했습니다. 값은 바꾸지 않았습니다.")
            raise SystemExit

        # 3 일괄변경 > 전체일괄변경
        btn, err = 누르기(page, "일괄변경", "아래")
        if err:
            say(err)
            say("오른쪽 아래 일괄변경 단추를 못 찾았습니다. 손으로 눌러주세요.")
            raise SystemExit
        say(f"일괄변경 누름 ({btn['x']},{btn['y']})")

        btn, err = 누르기(page, "전체일괄변경", "아래")
        if err:
            say(err)
            say("전체일괄변경 항목을 못 찾았습니다.")
            raise SystemExit
        say(f"전체일괄변경 누름 ({btn['x']},{btn['y']})")

        # 4 확인창 대조
        dlg = json.loads(page.evaluate(DIALOG))
        if not dlg.get("ok"):
            say(f"확인창을 못 읽었습니다: {dlg.get('reason')}")
            say("화면을 보시고 아니면 닫기를 눌러주세요.")
            raise SystemExit
        say("")
        say("===== 확인창 =====")
        for row in dlg["table"]:
            say("  " + " | ".join(row))
        say("  단추: " + ", ".join(dlg["buttons"]))

        본문 = dlg["text"] + " " + " ".join(" ".join(r) for r in dlg["table"])
        숫자 = [int(n) for n in re.findall(r"\b(\d+)\b", " ".join(" ".join(r) for r in dlg["table"]))]
        문제 = []
        if "불공" not in 본문:
            문제.append("확인창에 '불공' 이라는 말이 없습니다")
        if 숫자 and len(묶음) not in 숫자:
            문제.append(f"확인창의 건수 {숫자} 가 체크한 {len(묶음)}건과 다릅니다")
        if 문제:
            say("")
            for m in 문제:
                say(f"  [멈춤] {m}")
            say("  바꾸지 않고 멈춥니다. 화면의 닫기를 눌러주세요.")
            raise SystemExit
        say(f"  확인창 내용이 체크한 {len(묶음)}건과 맞습니다.")

        print()
        if input("\n  확인을 눌러 실제로 바꿀까요? (y) >>> ").strip().lower() != "y":
            say("사용자가 중단했습니다. 화면의 닫기를 눌러주세요.")
            raise SystemExit

        ok = False
        for 글자 in ("확인(Enter)", "확인(enter)", "확인"):
            btn, err = 누르기(page, 글자, "아래")
            if not err:
                say(f"'{글자}' 누름")
                ok = True
                break
        if not ok:
            say("확인 단추를 못 찾았습니다. 손으로 눌러주세요.")
            raise SystemExit

        page.wait_for_timeout(1500)

        # 5 결과 대조
        after = json.loads(page.evaluate(GRAB))
        if not after.get("ok"):
            say("바꾼 뒤 목록을 다시 읽지 못했습니다. 화면을 확인해주세요.")
            raise SystemExit
        arows = after["rows"]
        성공, 실패 = 0, []
        for i in 묶음:
            if i >= len(arows):
                실패.append((i, "줄이 사라짐"))
                continue
            r = arows[i]
            if str(r.get("nm_trade") or "") != str(rows[i].get("nm_trade") or ""):
                실패.append((i, "다른 줄로 밀림"))
                continue
            ty, cd = str(r.get("ty_mth2") or ""), str(r.get("cd_notdedct") or "")
            if ty == 불공 and cd == code:
                성공 += 1
            else:
                실패.append((i, f"유형 {ty} 사유 {cd}"))

        say("")
        say("===== 결과 =====")
        say(f"  바뀐 줄 {성공} / {len(묶음)}")
        for i, why in 실패[:20]:
            say(f"  안 바뀜 {i + 1}번째 {arows[i].get('nm_trade') if i < len(arows) else ''} : {why}")
        if 실패:
            say("")
            say("  하나라도 어긋나면 나머지는 진행하지 않습니다.")
        elif 시험:
            say("")
            say(f"  1건이 제대로 바뀌었습니다. 다시 실행해서 n 을 고르면"
                f" 남은 {len(대상[code]) - 1}건을 한 번에 바꿉니다.")
        say("")
        say("  전송(F3)은 부르지 않았습니다. 전송은 눈으로 확인하고 직접 하세요.")

except SystemExit:
    pass
except Exception:
    say("")
    say("실패했습니다. 원인:")
    say(traceback.format_exc())

저장()
print()
print("=" * 72)
print(f"  기록 저장됨: {OUT}")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
