"""조회 기간을 프로그램으로 바꿀 수 있는지 살핀다. 값은 바꾸지 않는다.

분기, 반기로 끊어 돌리려면 기간을 정할 수 있어야 한다.
지금은 화면 기본값(올해 1월 1일 ~ 오늘)으로만 조회한다.

기간 칸은 조회 줄에서 이렇게 보인다.

    (74,135) 2026.01.01   ~   (203,135) 2026.09.04
    (164,140) 달력 열기       (294,140) 달력 열기

입력칸 목록에는 안 잡혔다. 글자만 있는 것으로 보인다.
눌렀을 때 입력칸으로 바뀌는지, 아니면 달력을 써야 하는지 알아본다.

전표 값은 하나도 바꾸지 않는다. 조회도 누르지 않는다.
"""
import json
import re
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

import 공통

HERE = Path(__file__).resolve().parent
OUT = HERE / "기간시험.txt"

# 화면의 입력칸을 거르지 않고 다 적는다. 숨은 것도 본다.
INPUTS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('input,textarea,[contenteditable]')) {
    const r = el.getBoundingClientRect();
    const 보임 = el.offsetParent !== null;
    if (r.y > 400) continue;
    out.push({
      태그: el.tagName.toLowerCase(),
      종류: (el.type || '').toLowerCase(),
      값: (el.value !== undefined ? el.value : (el.innerText || '')).slice(0, 30),
      힌트: el.placeholder || '',
      보임: 보임,
      자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
      cls: (el.className || '').toString().slice(0, 40),
      id: el.id || '',
      편집가능: el.isContentEditable === true,
    });
  }
  return JSON.stringify(out.slice(0, 30));
}"""

# 지금 포커스가 어디에 있는지
FOCUS = r"""() => {
  const el = document.activeElement;
  if (!el) return JSON.stringify({ 없음: true });
  const r = el.getBoundingClientRect();
  return JSON.stringify({
    태그: el.tagName.toLowerCase(), 종류: (el.type || '').toLowerCase(),
    값: (el.value !== undefined ? el.value : (el.innerText || '')).slice(0, 30),
    자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
    cls: (el.className || '').toString().slice(0, 40),
  });
}"""

# 날짜처럼 생긴 글자를 찾는다
DATES = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.y > 300 || r.width < 8) continue;
    const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
    if (!/^\d{4}[.\-/]\d{2}[.\-/]\d{2}$/.test(t)) continue;
    let 안쪽 = true;
    for (const c of el.children) {
      const ct = (c.innerText || '').trim();
      if (ct === t) { 안쪽 = false; break; }
    }
    if (!안쪽) continue;
    out.push({ 글자: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
               자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
               태그: el.tagName.toLowerCase(),
               cls: (el.className || '').toString().slice(0, 34) });
  }
  out.sort((a, b) => a.x - b.x);
  return JSON.stringify(out.slice(0, 6));
}"""

lines = []


def say(t=""):
    print(str(t)[:500])
    lines.append(str(t))


print()
print("=" * 72)
print("  조회 기간을 바꿀 수 있는지 살펴보기 (아무것도 바꾸지 않습니다)")
print("=" * 72)
print()
print("  아무 고객사나 열어 전자세금계산서 화면을 띄워두세요.")
input("\n  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(공통.CDP)
        page = next((pg for ctx in browser.contexts for pg in ctx.pages
                     if "SAAC0103" in pg.url), None)
        if page is None:
            say("전자세금계산서 화면(SAAC0103) 탭을 못 찾았습니다.")
            raise SystemExit
        page.bring_to_front()
        h = 공통.화면머리(page)
        say(f"고객사 {h['이름']} {h['기수']} {h['기간']}")

        날짜들 = json.loads(page.evaluate(DATES))
        say("")
        say("===== 날짜처럼 생긴 글자 =====")
        for d in 날짜들:
            say(f"  ({d['자리']}) <{d['태그']} class=\"{d['cls']}\"> [{d['글자']}]")
        if len(날짜들) < 2:
            say("  날짜 칸을 두 개 못 찾았습니다.")
            raise SystemExit

        say("")
        say("===== 누르기 전 입력칸 =====")
        앞 = json.loads(page.evaluate(INPUTS))
        for i in 앞:
            say(f"  <{i['태그']} type={i['종류']}> ({i['자리']}) 보임={i['보임']}"
                f" 값[{i['값']}] 힌트[{i['힌트']}] {i['cls']}")

        시작 = 날짜들[0]
        say("")
        say(f"===== 시작 날짜 ({시작['자리']}) 를 눌러봅니다 =====")
        page.mouse.click(시작["x"], 시작["y"])
        page.wait_for_timeout(1200)

        say("  누른 뒤 포커스: " + page.evaluate(FOCUS))
        뒤 = json.loads(page.evaluate(INPUTS))
        새것 = [i for i in 뒤 if i not in 앞]
        say(f"  새로 생기거나 바뀐 입력칸 {len(새것)}개:")
        for i in 새것:
            say(f"    <{i['태그']} type={i['종류']}> ({i['자리']}) 보임={i['보임']}"
                f" 값[{i['값']}] {i['cls']}")
        열린것 = json.loads(page.evaluate(공통.LIKE, {"글": "월"}))
        if 열린것:
            say("  '월' 이 든 것(달력일 수 있음): "
                + ", ".join(f"({c['자리']})[{c['글자']}]" for c in 열린것[:6]))

        say("")
        say("===== 글자를 쳐봅니다 (2026 0101) =====")
        page.keyboard.press("Control+a")
        page.keyboard.type("20260101", delay=60)
        page.wait_for_timeout(800)
        say("  치는 중 포커스: " + page.evaluate(FOCUS))
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)

        뒤날짜 = json.loads(page.evaluate(DATES))
        say("")
        say("===== 친 뒤 날짜 =====")
        for d in 뒤날짜:
            say(f"  ({d['자리']}) [{d['글자']}]")
        바뀌었나 = 뒤날짜 and 뒤날짜[0]["글자"] != 시작["글자"]
        say("")
        say("===== 됩니다 =====" if 바뀌었나 else "===== 안 됩니다 =====")
        if 바뀌었나:
            say(f"  {시작['글자']} 에서 {뒤날짜[0]['글자']} 로 바뀌었습니다.")
            say("  눌러서 글자를 치면 기간을 정할 수 있습니다.")
        else:
            say("  눌러서 치는 것으로는 안 바뀝니다. 달력을 써야 할 수 있습니다.")

        say("")
        say("  조회는 누르지 않았습니다. 기간이 바뀌었어도 자료는 그대로입니다.")
        say("  화면에서 기간을 원래대로 되돌려 주세요.")
        browser.close()

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
