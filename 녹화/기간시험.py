"""조회 기간을 프로그램으로 정할 수 있는지 확인한다. 조회는 누르지 않는다.

앞선 시험에서 알아낸 것.
  평소   <span class="fakeinput">2026.01.01</span> 이 <div class="fake_inputbox"> 안에
  누르면  그 div 에 포커스가 간다
  치면   <input class="LSinput"> 로 바뀐다. ____-__-__ 꼴 마스크가 걸려 있다

빨리 치면 값이 어그러진다(2026-2_-__ 이 되었다). 한 자씩 천천히 쳐야 한다.

기간만 정하고 조회는 누르지 않는다. 자료는 그대로다.
끝나면 원래 기간으로 되돌려 놓는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

import 공통

HERE = Path(__file__).resolve().parent
OUT = HERE / "기간시험.txt"

lines = []


def say(t=""):
    print(str(t)[:400])
    lines.append(str(t))


print()
print("=" * 72)
print("  조회 기간 정하기 시험 (조회는 누르지 않습니다)")
print("=" * 72)
print()
print("  아무 고객사나 열어 전자세금계산서 화면을 띄워두세요.")
print()
차림 = ["1분기", "2분기", "3분기", "4분기", "상반기", "하반기", "올해전체"]
for n, t in enumerate(차림, 1):
    print(f"  {n}) {t}")
골 = input("\n  넣어볼 기간 (1~7, 그냥 Enter 면 3분기) >>> ").strip()
무엇 = 차림[int(골) - 1] if 골.isdigit() and 1 <= int(골) <= 7 else "3분기"

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
        say(f"고객사 {h['이름']} {h['기수']}   회계기간 {h['기간']}")

        처음 = json.loads(page.evaluate(공통.DATE_BOXES))
        say("")
        say("===== 지금 기간 =====")
        for c in 처음:
            say(f"  ({c['자리']}) [{c['글자'].splitlines()[0]}]")
        if len(처음) < 2:
            say("  기간 칸을 두 개 못 찾았습니다.")
            raise SystemExit
        원래 = [
            "".join(ch for ch in 처음[0]["글자"].splitlines()[0] if ch.isdigit())[:8],
            "".join(ch for ch in 처음[1]["글자"].splitlines()[0] if ch.isdigit())[:8],
        ]

        연도 = 공통.회계연도(page) or 원래[0][:4]
        시작, 끝 = 공통.기간계산(연도, 무엇)
        say("")
        say(f"===== {무엇} ({연도}년) 를 넣어봅니다: {시작} ~ {끝} =====")
        된다, 까닭 = 공통.기간설정(page, 시작, 끝, say)
        say("")
        if 된다:
            say("===== 됩니다 =====")
            say(f"  {무엇} 로 기간이 들어갔습니다. 순회에 넣을 수 있습니다.")
        else:
            say("===== 안 됩니다 =====")
            say(f"  {까닭}")

        say("")
        say(f"===== 원래 기간으로 되돌립니다: {원래[0]} ~ {원래[1]} =====")
        되돌림, 까닭2 = 공통.기간설정(page, 원래[0], 원래[1], say)
        if not 되돌림:
            say(f"  되돌리지 못했습니다: {까닭2}")
            say("  화면에서 기간을 손으로 되돌려 주세요.")

        say("")
        say("  조회는 누르지 않았습니다. 자료는 그대로입니다.")
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
