"""기간 칸의 달력이 어떻게 생겼는지 살핀다. 값은 바꾸지 않는다.

기간을 글자로 넣는 길은 막혔다.
  한 자씩 천천히 치기        -> 안 들어감
  값을 직접 넣고 알리기       -> 넣어도 되돌아감
사유 라디오와 같다. 부품이 제 상태를 따로 들고 있어 바깥에서 넣은 값을 무시한다.

남은 길은 달력이다. 달력을 열어 무엇이 있는지, 연월을 어떻게 옮기는지,
날짜 칸이 어떻게 생겼는지 적는다.

달력을 열어 보기만 하고 날짜는 고르지 않는다. 조회도 누르지 않는다.
"""
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

import 공통

HERE = Path(__file__).resolve().parent
OUT = HERE / "달력시험.txt"

# 달력이 열렸을 만한 자리를 훑는다
CALENDAR = r"""(args) => {
  const 것들 = [];
  const 담은것 = new Set();
  for (const el of document.querySelectorAll('*')) {
    if (el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (r.y < args.y - 40 || r.y > args.y + 460) continue;
    if (r.x < args.x - 220 || r.x > args.x + 460) continue;
    let 스스로 = '';
    for (const n of el.childNodes) if (n.nodeType === 3) 스스로 += n.textContent;
    스스로 = 스스로.trim().replace(/\s+/g, ' ');
    const cls = (el.className || '').toString().slice(0, 40);
    const 달력티 = /calendar|datepicker|picker|month|year|day/i.test(cls);
    if (!스스로 && !달력티) continue;
    if (스스로.length > 20) continue;
    const 열쇠 = 스스로 + '|' + Math.round(r.x) + ',' + Math.round(r.y);
    if (담은것.has(열쇠)) continue;
    담은것.add(열쇠);
    것들.push({ 글자: 스스로, 태그: el.tagName.toLowerCase(), cls: cls,
                자리: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
                x: Math.round(r.x), y: Math.round(r.y) });
  }
  것들.sort((a, b) => (a.y - b.y) || (a.x - b.x));
  return JSON.stringify(것들.slice(0, 90));
}"""

lines = []


def say(t=""):
    print(str(t)[:400])
    lines.append(str(t))


print()
print("=" * 72)
print("  기간 달력 살펴보기 (아무것도 바꾸지 않습니다)")
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
        say(f"고객사 {h['이름']} {h['기수']}   회계기간 {h['기간']}")

        칸들 = json.loads(page.evaluate(공통.DATE_BOXES))
        if len(칸들) < 2:
            say("기간 칸을 두 개 못 찾았습니다.")
            raise SystemExit
        칸 = 칸들[0]
        say(f"시작 날짜 칸: ({칸['자리']}) [{칸['글자'].splitlines()[0]}]")

        say("")
        say("===== 열기 전 =====")
        앞 = json.loads(page.evaluate(CALENDAR, {"x": 칸["x"], "y": 칸["y"]}))
        say(f"  그 언저리에 있는 것 {len(앞)}개")

        # 달력 단추는 칸의 오른쪽 끝에 있다
        단추 = [c for c in json.loads(page.evaluate(공통.BTN, {"글": "달력 열기"}))]
        say("")
        if 단추:
            단추.sort(key=lambda c: c["x"])
            say(f"'달력 열기' 단추 {len(단추)}개: " + ", ".join(c["자리"] for c in 단추))
            say(f"===== 첫 번째 달력 단추 ({단추[0]['자리']}) 를 누릅니다 =====")
            page.mouse.click(단추[0]["x"], 단추[0]["y"])
        else:
            say(f"===== 칸의 오른쪽 끝 ({칸['x'] + 칸['너비'] - 10},{칸['가운데y']}) 를 누릅니다 =====")
            page.mouse.click(칸["x"] + 칸["너비"] - 10, 칸["가운데y"])
        page.wait_for_timeout(1500)

        뒤 = json.loads(page.evaluate(CALENDAR, {"x": 칸["x"], "y": 칸["y"]}))
        앞열쇠 = {(c["글자"], c["자리"]) for c in 앞}
        새것 = [c for c in 뒤 if (c["글자"], c["자리"]) not in 앞열쇠]
        say("")
        say(f"===== 새로 생긴 것 {len(새것)}개 =====")
        for c in 새것:
            say(f"  ({c['자리']}) <{c['태그']} class=\"{c['cls']}\"> [{c['글자']}]")
        if not 새것:
            say("  아무것도 안 열렸습니다.")

        say("")
        say("  달력을 열어 보기만 했습니다. 날짜는 고르지 않았습니다.")
        say("  화면에 달력이 떠 있으면 esc 나 빈 곳을 눌러 닫아주세요.")
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
