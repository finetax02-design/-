"""고객사를 차례로 돌며 계정과목을 채우고 과세를 불공으로 바꾼다.

한 고객사에서 하는 일은 사람이 손으로 하던 것과 같다.

  수임처 화면에서 이름으로 찾아 회계를 누른다
  메뉴로 전자세금계산서 화면까지 간다
  기간을 정하고 구분을 2.매입 으로 바꾼 뒤 조회를 누른다
  미추천으로 남은 계정과목을 과거 이력대로 채운다
  과거에 불공이던 거래처를 불공으로 바꾸고 사유를 넣는다
  무엇을 했는지 적고 그 고객사가 연 탭을 닫는다

**전송(F3)은 어디에서도 부르지 않는다.** 전송은 사람이 눈으로 보고 한다.

한 고객사 안에서는 묻지 않고 스스로 한다. 대신 한 걸음마다 확인하고
어긋나면 그 고객사만 멈춘다. 손댄 것은 그대로 두고 다음 고객사로 넘어간다.

이어서 하기가 된다. 마친 고객사는 진행상황.csv 에 적어 두고
다시 돌리면 안 한 곳부터 이어간다.
"""
import csv
import datetime
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

import 공통

HERE = Path(__file__).resolve().parent
LIST = HERE / "고객사목록.csv"
DONE = HERE / "진행상황.csv"
LOG = HERE / f"순회기록_{datetime.datetime.now():%Y%m%d_%H%M}.txt"

기록 = []


def say(t=""):
    print(str(t)[:400])
    기록.append(str(t))


def 저장():
    LOG.write_text("\n".join(기록), encoding="utf-8")


def 진행읽기():
    한것 = {}
    if DONE.exists():
        with DONE.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                한것[(r.get("cd_com", ""), r.get("gisu", ""))] = r
    return 한것


def 진행쓰기(한것):
    머리 = ["고객사명", "cd_com", "gisu", "한때", "기간", "결과",
            "계정과목", "불공전환", "메모"]
    with DONE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=머리)
        w.writeheader()
        for r in 한것.values():
            w.writerow({k: r.get(k, "") for k in 머리})


print()
print("=" * 72)
print("  고객사 순회")
print("=" * 72)
print()
print("  전송(F3)은 부르지 않습니다. 전송은 눈으로 확인하고 직접 하세요.")
print()

if not LIST.exists():
    print(f"  고객사목록이 없습니다: {LIST}")
    print("  38_고객사받아적기.bat 으로 목록을 먼저 만들어주세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

목록 = []
with LIST.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if r.get("cd_com") and (r.get("할것", "Y").strip().upper() != "N"):
            목록.append(r)

한것 = 진행읽기()
남은 = [r for r in 목록 if (r["cd_com"], r["gisu"]) not in 한것]

print(f"  목록 {len(목록)}곳   이미 한 곳 {len(한것)}곳   남은 곳 {len(남은)}곳")
print()
if not 남은:
    print("  다 했습니다. 다시 하려면 진행상황.csv 를 지우세요.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

for n, r in enumerate(남은[:40], 1):
    print(f"  {n:>3}) {r['고객사명']}  {r['gisu']}기")
if len(남은) > 40:
    print(f"  ... 그 밖에 {len(남은) - 40}곳")

print()
몇곳 = input(f"  이번에 몇 곳까지 할까요? (그냥 Enter 면 {min(3, len(남은))}곳) >>> ").strip()
몇곳 = int(몇곳) if 몇곳.isdigit() and int(몇곳) > 0 else min(3, len(남은))
몇곳 = min(몇곳, len(남은))

print()
print("  어느 기간을 조회할까요?")
차림 = ["1분기", "2분기", "3분기", "4분기", "상반기", "하반기", "올해전체"]
for n, t2 in enumerate(차림, 1):
    print(f"    {n}) {t2}")
print("    8) 화면에 뜬 기본값 그대로 (올해 1월 1일 ~ 오늘)")
골 = input("  (1~8, 그냥 Enter 면 8) >>> ").strip()
기간무엇 = 차림[int(골) - 1] if 골.isdigit() and 1 <= int(골) <= 7 else None
print(f"  기간: {기간무엇 or '화면 기본값'}"
      + ("  (고객사마다 그 고객사 회계연도로 셈합니다)" if 기간무엇 else ""))

print()
print("  고객사마다 멈춰서 화면을 보시겠습니까?")
print("    y  한 곳 끝날 때마다 멈춥니다. 처음에는 이쪽을 권합니다.")
print("    n  멈추지 않고 끝까지 갑니다.")
멈출까 = input("  (y/n, 그냥 Enter 면 y) >>> ").strip().lower() != "n"

print()
print("  " + "-" * 66)
print("   위하고 수임처 화면(담당 수임처 목록이 보이는 화면)을 띄워두세요.")
print("   그 탭 하나만 남기고 다른 위하고 탭은 닫아주시면 깔끔합니다.")
print("  " + "-" * 66)
input("\n  준비되었으면 Enter >>> ")

say(f"순회 시작 {datetime.datetime.now():%Y-%m-%d %H:%M}   {몇곳}곳"
    f"   기간 {기간무엇 or '화면 기본값'}")
say("")

for 차례, 표적 in enumerate(남은[:몇곳], 1):
    say("=" * 68)
    say(f"[{차례}/{몇곳}] {표적['고객사명']}  {표적['gisu']}기  {표적['cd_com']}")
    한줄 = {"고객사명": 표적["고객사명"], "cd_com": 표적["cd_com"],
            "gisu": 표적["gisu"],
            "한때": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "기간": 기간무엇 or "기본값",
            "결과": "", "계정과목": "", "불공전환": "", "메모": ""}
    연탭 = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(공통.CDP)
            수임처탭 = next((pg for ctx in browser.contexts for pg in ctx.pages
                             if "www.wehago.com" in pg.url), None)
            if 수임처탭 is None:
                한줄["결과"] = "멈춤"
                한줄["메모"] = "수임처 화면 탭을 못 찾음"
                say("  수임처 화면 탭(www.wehago.com)이 없습니다. 순회를 멈춥니다.")
                한것[(표적["cd_com"], 표적["gisu"])] = 한줄
                진행쓰기(한것)
                break

            전표화면, 연탭, 까닭 = 공통.고객사열기(browser, 수임처탭, 표적, say)
            if 전표화면 is None:
                한줄["결과"] = "멈춤"
                한줄["메모"] = 까닭
                say(f"  [멈춤] {까닭}")
            else:
                건수, 까닭2 = 공통.매입조회(전표화면, say, 기간무엇)
                if 건수 < 0:
                    한줄["결과"] = "멈춤"
                    한줄["메모"] = 까닭2
                    say(f"  [멈춤] {까닭2}")
                elif 건수 == 0:
                    한줄["결과"] = "자료없음"
                    say("    매입 자료가 없습니다.")
                else:
                    ㄱ = 공통.계정과목채우기(전표화면, say)
                    한줄["계정과목"] = f"{ㄱ['성공']}칸 채움 / 건너뜀 {ㄱ['건너뜀']}"

                    규칙, 자세히 = 공통.불공규칙만들기(공통.전표읽기(전표화면) or [])
                    say(f"    거래처 {len(자세히)}곳 중 불공 규칙 {len(규칙)}곳")
                    ㅂ = 공통.불공전환(전표화면, 규칙, say)
                    한줄["불공전환"] = f"{ㅂ['바꾼건']}건"
                    if ㅂ["못한사유"]:
                        한줄["메모"] = "본보기없음: " + ", ".join(ㅂ["못한사유"])
                    if ㅂ["멈춤"]:
                        한줄["결과"] = "멈춤"
                        한줄["메모"] = (한줄["메모"] + " / " if 한줄["메모"] else "") + ㅂ["멈춤"]
                        say(f"  [멈춤] {ㅂ['멈춤']}")
                    else:
                        한줄["결과"] = "정상"

            # 이 고객사가 연 탭을 닫는다. 안 닫으면 탭이 쌓인다.
            for pg in 연탭:
                try:
                    pg.close()
                except Exception:
                    pass
            say(f"    탭 {len(연탭)}개 닫음")
            browser.close()
    except Exception:
        한줄["결과"] = "실패"
        한줄["메모"] = "예상 못 한 오류"
        say("  실패했습니다. 원인:")
        say(traceback.format_exc())

    한것[(표적["cd_com"], 표적["gisu"])] = 한줄
    진행쓰기(한것)
    저장()
    say(f"  결과: {한줄['결과']}  계정과목 {한줄['계정과목']}  불공 {한줄['불공전환']}"
        + (f"  ({한줄['메모']})" if 한줄["메모"] else ""))
    say("")

    if 멈출까 and 차례 < 몇곳:
        print()
        print("  " + "-" * 66)
        print("   화면을 보고 확인해주세요. 다음 고객사로 넘어가려면 Enter,")
        print("   그만두려면 q 를 치고 Enter.")
        print("  " + "-" * 66)
        if input("\n  >>> ").strip().lower() == "q":
            say("사용자가 그만두었습니다.")
            break

say("=" * 68)
say("이번 순회 결과")
say("")
say(f"  {'고객사':<26}{'결과':<8}{'계정과목':<22}{'불공':<8}메모")
say("  " + "-" * 84)
for r in list(한것.values())[-몇곳:]:
    say(f"  {str(r['고객사명'])[:24]:<26}{r.get('기간', ''):<8}{r['결과']:<8}"
        f"{r['계정과목']:<22}{r['불공전환']:<8}{r['메모']}")
say("")
say("  전송(F3)은 부르지 않았습니다. 눈으로 확인하고 직접 전송하세요.")

저장()
print()
print("=" * 72)
print(f"  기록 저장됨: {LOG}")
print(f"  진행상황: {DONE}  (다시 돌리면 안 한 곳부터 이어갑니다)")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
