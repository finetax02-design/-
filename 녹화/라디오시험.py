"""불공제 사유 라디오를 어떻게 눌러야 선택되는지 찾는다. 한 건만.

좌표 클릭이 안 먹었다. 라디오 주변 구조를 모르는 채 좌표만 찍은 탓이다.
이번에는 구조를 먼저 뜨고, 여러 방법을 순서대로 시도하며 매번 확인한다.

시도 순서
  1 라디오 입력칸 자체의 좌표 클릭
  2 감싼 요소의 왼쪽 끝 클릭 (동그라미가 있는 자리)
  3 글자 부분 클릭
  4 화살표 키로 이동 (기본 선택이 4 이므로 5 는 아래로 한 번)
  5 자바스크립트로 checked 를 바꾸고 이벤트를 직접 발생

하나라도 성공하면 거기서 멈추고 선택(enter) 까지 누른다.
전부 실패하면 확정하지 않고 유형을 과세로 되돌린다.
전송(F3)은 부르지 않는다.
"""
import csv
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
HERE = Path(__file__).resolve().parent
RULES = HERE / "불공규칙표.csv"
OUT = HERE / "라디오시험.txt"

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
          let src = window.__dp || v;
          try { const n = src.getRowCount();
                return JSON.stringify({ ok: true, rows: n ? (src.getJsonRows(0, n - 1) || []) : [] }); }
          catch (e) { return JSON.stringify({ ok: false, reason: String(e).slice(0, 120) }); }
        }
      }
      if (d < 9) queue.push({ o: v, d: d + 1 });
    }
  }
  return JSON.stringify({ ok: false, reason: '전표 목록을 못 찾음' });
}"""

TO_불공 = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  let r;
  try { r = (dp || g).getJsonRows(args.row, args.row)[0]; } catch (e) { r = null; }
  if (!r) return JSON.stringify({ ok: false, reason: '줄을 못 읽음' });
  if (String(r.ty_mth2) !== '51') return JSON.stringify({ ok: false, reason: '과세가 아님' });
  try { g.setCurrent({ itemIndex: args.row, dataRow: args.row,
                       column: 'ty_mth2', fieldName: 'ty_mth2' }); } catch (e) {}
  try { if (g.setFocusToGrid) g.setFocusToGrid(); } catch (e) {}
  try { g.setValue(args.row, 'ty_mth2', '54'); }
  catch (e) { return JSON.stringify({ ok: false, reason: 'setValue ' + String(e).slice(0, 80) }); }
  let ci = -1;
  try { ci = g.getColumns().findIndex(c => String(c.name || c.fieldName) === 'ty_mth2'); } catch (e) {}
  try { g.onCellEdited(g, args.row, args.row, ci); } catch (e) {}
  return JSON.stringify({ ok: true });
}"""

# 라디오 주변 구조를 그대로 뜬다
DUMP = r"""() => {
  const L = [];
  const rects = [];
  const radios = [...document.querySelectorAll('input[type=radio]')];
  L.push(`라디오 ${radios.length}개`);
  radios.forEach((el, i) => {
    const rr = el.getBoundingClientRect();
    const p = el.parentElement;
    const pr = p ? p.getBoundingClientRect() : null;
    const cs = getComputedStyle(el);
    let text = '';
    for (let n = el, j = 0; n && j < 4; n = n.parentElement, j++) {
      const t = (n.innerText || '').trim();
      if (t && t.length < 60) { text = t; break; }
    }
    L.push(`\n[${i}] value=${el.value} checked=${el.checked} text="${text}"`);
    L.push(`    입력칸 rect=(${Math.round(rr.x)},${Math.round(rr.y)}) ${Math.round(rr.width)}x${Math.round(rr.height)}`
           + ` opacity=${cs.opacity} display=${cs.display} pointerEvents=${cs.pointerEvents}`);
    if (p) {
      L.push(`    부모 <${p.tagName.toLowerCase()} class="${(p.className||'').toString().slice(0,60)}">`
             + ` rect=(${Math.round(pr.x)},${Math.round(pr.y)}) ${Math.round(pr.width)}x${Math.round(pr.height)}`);
      L.push(`    부모 HTML: ${p.outerHTML.slice(0, 260)}`);
    }
    rects.push({ i: i, value: el.value, text: text,
                 radio: { x: rr.x + rr.width / 2, y: rr.y + rr.height / 2, w: rr.width, h: rr.height },
                 parent: pr ? { x: pr.x, y: pr.y, w: pr.width, h: pr.height } : null });
  });
  return JSON.stringify({ log: L.join('\n'), rects: rects });
}"""

CHECKED = r"""() => {
  for (const el of document.querySelectorAll('input[type=radio]')) {
    if (!el.checked) continue;
    let t = '';
    for (let n = el, i = 0; n && i < 4; n = n.parentElement, i++) {
      const s = (n.innerText || '').trim();
      if (s && s.length < 60) { t = s; break; }
    }
    return JSON.stringify({ value: el.value, text: t });
  }
  return JSON.stringify({ value: '', text: '' });
}"""

JS_CLICK = r"""(args) => {
  const el = [...document.querySelectorAll('input[type=radio]')]
    .find(e => String(e.value) === String(args.value));
  if (!el) return '해당 라디오 없음';
  const L = [];
  try {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'checked').set;
    setter.call(el, true);
    L.push('checked 설정');
  } catch (e) { L.push('checked 오류: ' + String(e).slice(0, 80)); }
  for (const type of ['click', 'input', 'change']) {
    try { el.dispatchEvent(new Event(type, { bubbles: true })); L.push(type + ' 발생'); }
    catch (e) {}
  }
  return L.join(' / ');
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

STATE = r"""(args) => {
  const g = window.__g, dp = window.__dp;
  try {
    const r = (dp || g).getJsonRows(args.row, args.row)[0] || {};
    return JSON.stringify({ ty_mth2: r.ty_mth2, cd_notdedct: r.cd_notdedct, trade: r.nm_trade });
  } catch (e) { return JSON.stringify({ error: String(e).slice(0, 80) }); }
}"""

lines = []


def say(t=""):
    print(t[:400])
    lines.append(t)


print()
print("=" * 66)
print("  불공제 사유 라디오 누르는 방법 찾기 (한 건)")
print("=" * 66)
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
print("\n  전표 목록에서 아무 줄이나 한 번 클릭한 뒤 진행하세요.")
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

        targets = []
        for i, r in enumerate(rows):
            if str(r.get("ty_mth2")) != 과세:
                continue
            code = rules.get(str(r.get("no_bisocial") or ""))
            if code:
                targets.append((i, r, code))
        say(f"전환 대상 {len(targets)}건")
        for n, (i, r, code) in enumerate(targets[:15]):
            say(f"  [{n:2d}] {i:4d}행 {str(r.get('nm_trade'))[:20]:<22} 사유={code} {사유이름[code]}")
        if not targets:
            say("전환할 건이 없습니다.")
            raise SystemExit

        sel = input("\n  시험할 항목 번호 >>> ").strip()
        if not sel.isdigit() or int(sel) >= len(targets):
            raise SystemExit
        row, rec, code = targets[int(sel)]

        say("")
        say(f"### {row}행 {rec.get('nm_trade')} / 사유 {code} {사유이름[code]}")
        say("시작: " + page.evaluate(STATE, {"row": row}))

        res = json.loads(page.evaluate(TO_불공, {"row": row}))
        if not res.get("ok"):
            say(f"불공 전환 실패: {res.get('reason')}")
            raise SystemExit
        page.wait_for_timeout(1400)

        dump = json.loads(page.evaluate(DUMP))
        say("")
        say("===== 라디오 구조 =====")
        say(dump["log"])

        target = next((r for r in dump["rects"]
                       if r["text"].startswith(code + ".") or r["text"].startswith(code + " ")), None)
        if target is None:
            target = next((r for r in dump["rects"] if str(r["value"]).endswith(code)), None)
        if target is None:
            say(f"\n사유 {code} 를 못 찾았습니다.")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            say(page.evaluate(REVERT, {"row": row}))
            raise SystemExit

        say("")
        say(f"목표: [{target['i']}] {target['value']} \"{target['text']}\"")
        say("")
        say("===== 방법을 하나씩 시도 =====")

        def now():
            return json.loads(page.evaluate(CHECKED))

        def hit():
            c = now()
            return c["text"].startswith(code + ".") or c["text"].startswith(code + " ")

        say(f"  현재 선택: {json.dumps(now(), ensure_ascii=False)}")
        ok = False

        # 1 입력칸 자체
        if target["radio"]["w"] > 1 and target["radio"]["h"] > 1:
            page.mouse.click(target["radio"]["x"], target["radio"]["y"])
            page.wait_for_timeout(400)
            say(f"  1 입력칸 클릭 → {json.dumps(now(), ensure_ascii=False)}")
            ok = hit()
        else:
            say("  1 입력칸이 크기 0 이라 건너뜀")

        # 2 감싼 요소 왼쪽 끝
        if not ok and target["parent"]:
            pr = target["parent"]
            page.mouse.click(pr["x"] + 10, pr["y"] + pr["h"] / 2)
            page.wait_for_timeout(400)
            say(f"  2 왼쪽 끝 클릭 → {json.dumps(now(), ensure_ascii=False)}")
            ok = hit()

        # 3 글자 부분
        if not ok and target["parent"]:
            pr = target["parent"]
            page.mouse.click(pr["x"] + min(pr["w"] * 0.5, 120), pr["y"] + pr["h"] / 2)
            page.wait_for_timeout(400)
            say(f"  3 글자 클릭 → {json.dumps(now(), ensure_ascii=False)}")
            ok = hit()

        # 4 화살표 키
        if not ok:
            cur = now()
            ci = next((r["i"] for r in dump["rects"] if r["value"] == cur["value"]), None)
            if ci is not None:
                step = target["i"] - ci
                key = "ArrowDown" if step > 0 else "ArrowUp"
                for _ in range(abs(step)):
                    page.keyboard.press(key)
                    page.wait_for_timeout(150)
                say(f"  4 화살표 {key} × {abs(step)} → {json.dumps(now(), ensure_ascii=False)}")
                ok = hit()
            else:
                say("  4 현재 선택 위치를 몰라 건너뜀")

        # 5 자바스크립트로 직접
        if not ok:
            say("  5 " + page.evaluate(JS_CLICK, {"value": target["value"]}))
            page.wait_for_timeout(400)
            say(f"    → {json.dumps(now(), ensure_ascii=False)}")
            ok = hit()

        say("")
        if not ok:
            say("모든 방법이 실패했습니다. 확정하지 않고 되돌립니다.")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            say(page.evaluate(REVERT, {"row": row}))
            say("끝: " + page.evaluate(STATE, {"row": row}))
        else:
            say("선택 성공. 이제 확정합니다.")
            clicked = False
            for s in ("button:has-text('선택(enter)')", "button:has-text('선택')",
                      "button:has-text('확인(enter)')", "button:has-text('확인')"):
                try:
                    loc = page.locator(s).last
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=4000)
                        say(f"  버튼 클릭: {s}")
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                names = page.evaluate("""() => [...document.querySelectorAll('button')]
                    .filter(e => e.offsetParent).map(e => (e.innerText||'').trim())
                    .filter(Boolean).slice(0, 20)""")
                say(f"  버튼을 못 찾음. 보이는 버튼: {names}")
                page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
            after = json.loads(page.evaluate(STATE, {"row": row}))
            say("끝: " + json.dumps(after, ensure_ascii=False))
            say("→ " + ("성공" if str(after.get("cd_notdedct") or "").strip() == code
                        else f"사유가 {after.get('cd_notdedct')} 입니다. 화면에서 확인해주세요"))

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
