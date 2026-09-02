"""불공제사유를 창 없이 직접 고쳐본다. 한 줄만, 물어본 뒤에.

불공제사유 창은 포기한다. 살펴보니 이렇다.

  - 라디오에 name 이 없다. 한 무리로 묶이지 않아 여러 개가 동시에 체크된다.
    실제로 4 와 5 가 둘 다 체크되어 있었다. 위하고 속값은 4, 표시용은 5 다.
  - 라디오가 두 벌이다. 12개는 0x0 껍데기, 12개는 진짜다.
  - 리액트가 옛 판이라 __reactProps$ 가 없고 __reactInternalInstance$ 만 있다.
  - 진짜 라디오는 가려진 것도 없는데 마우스로 눌러도 꿈쩍하지 않는다.

대신 계정과목 때 통했던 길을 쓴다.
setValue 로 값을 넣고 onCellEdited 를 직접 불러 위하고가 알아듣게 한다.
계정과목 때도 setValue 만으로는 전표상태가 안 따라와 이렇게 풀었다.

이미 불공인 줄 하나를 골라 사유만 바꿔본다.
바꾸기 전에 무엇을 어떻게 바꿀지 보여주고 물어본다.
전송(F3)은 부르지 않는다.
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
OUT = HERE / "사유직접기록.txt"

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



# cd_notdedct 가 어떤 열인지, 고칠 수 있는지 살핀다
COLINFO = r"""() => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false });
  let cols = [];
  try { cols = g.getColumns(); } catch (e) { return JSON.stringify({ ok: false }); }
  const out = [];
  cols.forEach((c, i) => {
    const nm = String(c.name || c.fieldName || '');
    if (!/^(ty_mth2|cd_notdedct|nm_notdedct|ty_jungstat)$/.test(nm)) return;
    out.push({ 자리: i, 이름: nm, 고칠수있음: c.editable !== false, 보임: c.visible !== false,
               필드: c.fieldName || '', 머리: (c.header && c.header.text) || '' });
  });
  let 필드 = [];
  try { 필드 = (g.getDataSource().getFields() || []).map(f => f.fieldName); } catch (e) {}
  return JSON.stringify({ ok: true, 열: out, 필드자리: 필드.indexOf('cd_notdedct') });
}"""

# 사유를 직접 넣고 위하고가 알아듣게 한다
SET_REASON = r"""(args) => {
  const g = window.__g;
  if (!g) return JSON.stringify({ ok: false, reason: '그리드 없음' });
  let src = g;
  try { const dp = g.getDataSource(); if (dp) src = dp; } catch (e) {}
  const 읽기 = () => { try { return src.getJsonRows(args.row, args.row)[0] || null; }
                       catch (e) { return null; } };
  const 앞 = 읽기();
  if (!앞) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(앞.nm_trade || '') !== args.거래처) {
    return JSON.stringify({ ok: false, reason: `줄이 밀렸습니다 (${앞.nm_trade})` });
  }
  const 말 = [];
  // 어느 열인지 찾는다. onCellEdited 에 자리를 넘겨야 한다.
  let 열자리 = -1;
  try {
    g.getColumns().forEach((c, i) => {
      if (String(c.name || c.fieldName || '') === 'cd_notdedct') 열자리 = i;
    });
  } catch (e) {}
  말.push('cd_notdedct 열 자리 ' + 열자리);

  try { g.setValue(args.row, 'cd_notdedct', args.사유); 말.push('setValue 함'); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setValue ' + String(e).slice(0, 90), 말: 말 }); }

  // 위하고가 듣는 손잡이를 직접 부른다. 계정과목 때와 같은 방법이다.
  try {
    if (typeof g.onCellEdited === 'function') {
      g.onCellEdited(g, args.row, args.row, 열자리);
      말.push('onCellEdited 부름');
    } else 말.push('onCellEdited 가 없음');
  } catch (e) { 말.push('onCellEdited 오류 ' + String(e).slice(0, 80)); }

  const 뒤 = 읽기();
  return JSON.stringify({ ok: true, 말: 말,
    앞: { 유형: 앞.ty_mth2, 사유: 앞.cd_notdedct, 상태: 앞.ty_jungstat },
    뒤: { 유형: 뒤 && 뒤.ty_mth2, 사유: 뒤 && 뒤.cd_notdedct, 상태: 뒤 && 뒤.ty_jungstat } });
}"""

lines = []


def say(t=""):
    print(str(t)[:600])
    lines.append(str(t))


print()
print("=" * 72)
print("  불공제사유를 창 없이 직접 고치기 (한 줄만 시험)")
print("=" * 72)
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

print("  전자세금계산서 화면을 띄우고 조회를 마친 상태여야 합니다.")
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pages = [pg for ctx in browser.contexts for pg in ctx.pages
                 if "smarta.wehago.com" in pg.url]
        pages.sort(key=lambda pg: "SAAC0103" not in pg.url)
        page, rows = None, None
        for pg in pages:
            try:
                d = json.loads(pg.evaluate(GRAB))
            except Exception:
                continue
            if d.get("ok") and d.get("rows"):
                page, rows = pg, d["rows"]
                break
        if page is None:
            say("자료가 들어 있는 전자세금계산서 탭을 찾지 못했습니다.")
            raise SystemExit
        page.bring_to_front()
        say(f"전표 {len(rows)}건")

        ci = json.loads(page.evaluate(COLINFO))
        say("")
        say("===== 열 생김새 =====")
        for c in ci.get("열", []):
            say(f"  {c['자리']:>3} {c['이름']:<14} 고칠수있음={c['고칠수있음']}"
                f" 보임={c['보임']} 머리={c['머리']}")

        # 불공인 줄을 모두 보여준다. 규칙과 어긋나는 것은 표시해 둔다.
        불공줄 = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 불공:
                continue
            바람 = rules.get(str(r.get("no_bisocial") or ""))
            지금 = str(r.get("cd_notdedct") or "")
            불공줄.append((i, 지금, 바람))

        say("")
        if not 불공줄:
            say("불공인 줄이 하나도 없습니다. 고칠 것이 없습니다.")
            raise SystemExit
        say(f"불공인 줄 {len(불공줄)}건:")
        for n, (i, 지금, 바람) in enumerate(불공줄[:30], 1):
            r = rows[i]
            표 = ""
            if 바람 and 지금 != 바람:
                표 = f"   <- 규칙은 {바람} 인데 어긋남"
            elif 바람:
                표 = "   (규칙과 같음)"
            say(f"  {n:>2}) {i + 1:>4}번째  {r.get('s_date')}  {r.get('nm_trade')}"
                f"  {r.get('mn_mnam')}   사유 {지금 or '없음'}{표}")
        if len(불공줄) > 30:
            say(f"  ... 그 밖에 {len(불공줄) - 30}건")

        골 = input("\n  고칠 줄 번호 (1 부터, 그만두려면 Enter) >>> ").strip()
        if not 골.isdigit() or not (1 <= int(골) <= len(불공줄)):
            say("그만둡니다. 아무것도 바꾸지 않았습니다.")
            raise SystemExit
        i, 지금, 바람 = 불공줄[int(골) - 1]
        r = rows[i]

        기본 = 바람 or ""
        묻기 = f"  넣을 사유 (3/4/5" + (f", 그냥 Enter 면 {기본}" if 기본 else "") + ") >>> "
        새사유 = input("\n" + 묻기).strip() or 기본
        if 새사유 not in 사유이름:
            say(f"사유 {새사유} 는 다루지 않습니다. 3, 4, 5 만 됩니다.")
            raise SystemExit
        바람 = 새사유

        say("")
        say(f"바꿀 줄: {i + 1}번째  {r.get('s_date')}  {r.get('nm_trade')}"
            f"  {r.get('mn_mnam')}")
        say(f"사유를 {지금 or '없음'} 에서 {바람} {사유이름[바람]} 로 바꿉니다.")
        say("유형(불공)은 건드리지 않습니다.")
        if 지금 == 바람:
            say("[알림] 지금 사유와 같습니다. 아무것도 안 바뀔 것입니다.")
        if input("\n  이 한 줄만 바꿔볼까요? (y) >>> ").strip().lower() != "y":
            say("그만둡니다. 아무것도 바꾸지 않았습니다.")
            raise SystemExit

        res = json.loads(page.evaluate(SET_REASON,
                                       {"row": i, "사유": 바람,
                                        "거래처": str(r.get("nm_trade") or "")}))
        say("")
        for m in res.get("말", []):
            say("  " + m)
        if not res.get("ok"):
            say(f"  실패: {res.get('reason')}")
            raise SystemExit
        say(f"  바꾸기 앞: {res['앞']}")
        say(f"  바꾼 뒤:   {res['뒤']}")

        page.wait_for_timeout(1200)
        after = json.loads(page.evaluate(GRAB))
        if after.get("ok") and i < len(after["rows"]):
            a = after["rows"][i]
            say("")
            say("===== 다시 읽어 확인 =====")
            say(f"  {i + 1}번째 {a.get('nm_trade')}"
                f"  유형 {a.get('ty_mth2')}  사유 {a.get('cd_notdedct')}"
                f"  전표상태 {a.get('ty_jungstat')}")
            if str(a.get("ty_mth2")) == 불공 and str(a.get("cd_notdedct")) == 바람:
                say("  사유가 제대로 들어갔습니다.")
            else:
                say("  사유가 들어가지 않았습니다.")

        say("")
        say("  화면에서도 그 줄의 불공사유가 바뀌었는지 눈으로 봐주세요.")
        say("  전송(F3)은 부르지 않았습니다.")

except SystemExit:
    pass
except Exception:
    say("")
    say("실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 72)
print(f"  기록 저장됨: {OUT}")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
