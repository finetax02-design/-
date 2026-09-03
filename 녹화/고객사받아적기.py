"""고객사를 오갈 때마다 주소를 받아 적어 목록을 만든다.

담당자별로 맡은 업체가 50~80곳이다. 그 목록만 있으면 순회가 된다.
프로그램 속에서는 목록을 못 찾았다. 그래서 평소 일하듯 고객사를 오가면
그때마다 주소를 받아 적어 목록을 쌓는다.

**크롬에 붙지 않는다.**
앞서 Playwright 로 크롬에 붙었더니 새 화면이 뜨는 것을 붙잡아
두 번째 회사로 들어가지지 않았다. 프로그램을 닫아야 풀렸다.

크롬은 9222 번으로 열려 있는 탭 목록을 그냥 알려준다.
주소창을 밖에서 엿보는 것과 같아서 크롬이 하는 일을 조금도 방해하지 않는다.

    http://localhost:9222/json   <- 탭마다 제목과 주소가 적혀 있다

고객사명은 탭 제목에서 얻는다.

    "전자세금계산서(2기) - 오벨피부과의원"
       화면       기수      고객사명

이 창을 켜둔 채로 위하고에서 담당 업체를 하나씩 열면 된다.
한 바퀴 돌고 나면 목록이 다 만들어진다.

값은 하나도 바꾸지 않는다. 크롬을 건드리지도 않는다.
"""
import csv
import datetime
import json
import re
import time
import traceback
import urllib.request
from pathlib import Path

CDP목록 = "http://localhost:9222/json"
HERE = Path(__file__).resolve().parent
OUT = HERE / "고객사목록.csv"

머리 = ["고객사명", "cd_com", "gisu", "cno", "yminsa", "할것", "처음본때"]


def 탭들():
    """크롬이 알려주는 탭 목록. 붙는 것이 아니라 물어보기만 한다."""
    열기 = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with 열기.open(CDP목록, timeout=5) as r:
        것들 = json.loads(r.read().decode("utf-8", "replace"))
    return [t for t in 것들 if t.get("type") == "page"]


def 주소풀기(url):
    조각 = {}
    for k in ("cd_com", "gisu", "cno", "yminsa"):
        m = re.search(k + r"=([^&#]*)", url)
        조각[k] = m.group(1) if m else ""
    return 조각


def 이름풀기(title):
    """탭 제목에서 고객사명과 기수를 뽑는다.

    '전자세금계산서(2기) - 오벨피부과의원' 처럼 되어 있다.
    """
    t = (title or "").strip()
    기수 = ""
    m = re.search(r"\((\d+)기\)", t)
    if m:
        기수 = m.group(1)
    이름 = ""
    if " - " in t:
        이름 = t.split(" - ")[-1].strip()
    elif "-" in t:
        이름 = t.rsplit("-", 1)[-1].strip()
    # 제목이 잘려 있거나 화면 이름만 있는 경우를 걸러낸다
    if 이름 in ("WEHAGO", "WEHAGO T", "") or len(이름) > 40:
        이름 = ""
    return 이름, 기수


def 읽어오기():
    """이미 적어둔 것을 읽는다. 두 번 적지 않으려는 것이다."""
    있는것, 차례 = {}, []
    if OUT.exists():
        with OUT.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                열쇠 = (r.get("cd_com", ""), r.get("gisu", ""))
                if 열쇠[0]:
                    있는것[열쇠] = r
                    차례.append(열쇠)
    return 있는것, 차례


def 저장(있는것, 차례):
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=머리)
        w.writeheader()
        for 열쇠 in 차례:
            w.writerow({k: 있는것[열쇠].get(k, "") for k in 머리})


print()
print("=" * 72)
print("  고객사 받아 적기")
print("=" * 72)
print()
print("  이 창을 켜둔 채로 위하고에서 담당 업체를 하나씩 열어주세요.")
print("  전자세금계산서 화면까지 들어가시면 그때 받아 적습니다.")
print("  평소 일하시던 대로 하시면 됩니다.")
print()
print("  크롬을 건드리지 않습니다. 주소만 밖에서 엿봅니다.")
print("  그만두려면 이 창에서 Ctrl+C 를 누르세요.")
print("  적은 것은 그때까지 다 저장되어 있습니다.")
print()

있는것, 차례 = 읽어오기()
if 차례:
    print(f"  이미 적어둔 고객사 {len(차례)}곳이 있습니다. 이어서 적습니다.")
    print()

try:
    탭들()
except Exception as e:
    print(f"  크롬을 찾지 못했습니다: {str(e)[:90]}")
    print("  크롬열기.bat 으로 연 창이 떠 있어야 합니다.")
    input("\n  창을 닫으려면 Enter >>> ")
    raise SystemExit

input("  준비되었으면 Enter >>> ")
print()
print("  지켜보는 중입니다. 위하고에서 수임처를 하나씩 열어주세요.")
print()

마지막알림 = 0.0
탈났던때 = 0
try:
    while True:
        try:
            것들 = 탭들()
            탈났던때 = 0
        except Exception as e:
            탈났던때 += 1
            print(f"\r  크롬과 말이 안 통합니다 ({탈났던때}번째) {str(e)[:50]}        ",
                  end="", flush=True)
            if 탈났던때 >= 20:
                print()
                print("  크롬이 닫힌 것 같습니다. 그만둡니다.")
                break
            time.sleep(3)
            continue

        고객사탭 = [t for t in 것들
                    if "smarta.wehago.com" in (t.get("url") or "") and "cd_com=" in (t.get("url") or "")]

        for t in 고객사탭:
            조각 = 주소풀기(t.get("url") or "")
            열쇠 = (조각["cd_com"], 조각["gisu"])
            if not 열쇠[0] or 열쇠 in 있는것:
                continue
            이름, 기수제목 = 이름풀기(t.get("title"))
            있는것[열쇠] = {
                "고객사명": 이름 or "(이름을 못 읽음)",
                "cd_com": 조각["cd_com"], "gisu": 조각["gisu"],
                "cno": 조각["cno"], "yminsa": 조각["yminsa"],
                "할것": "Y",
                "처음본때": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            차례.append(열쇠)
            저장(있는것, 차례)
            print(f"\r  {len(차례):>3}곳  {이름 or '(이름 못 읽음)'}"
                  f"  {(기수제목 or 조각['gisu'])}기  {조각['cd_com']}{' ' * 24}")
            마지막알림 = 0.0

        지금 = time.time()
        if 지금 - 마지막알림 >= 3:
            마지막알림 = 지금
            때 = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\r  [{때}] 지켜보는 중   크롬 탭 {len(것들)}개"
                  f"   그중 고객사 화면 {len(고객사탭)}개"
                  f"   적은 곳 {len(차례)}곳        ", end="", flush=True)

        time.sleep(2)

except KeyboardInterrupt:
    print()
    print()
    print("  그만둡니다.")
except Exception:
    print()
    print("실패했습니다. 원인:")
    traceback.print_exc()

저장(있는것, 차례)
print()
print("=" * 72)
print(f"  고객사 {len(차례)}곳을 적었습니다: {OUT}")
print("  할것 칸을 N 으로 바꾸면 그 고객사는 건너뜁니다.")
print("=" * 72)
print()
input("  창을 닫으려면 Enter >>> ")
