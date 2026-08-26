"""위하고에 로그인해 세션을 프로필 폴더에 저장한다.

배치 파일에서 playwright CLI 를 부르면 창이 안 뜨는 경우가 있어서,
진단.py 와 같은 방식으로 파이썬에서 직접 브라우저를 띄운다.
실패하면 이유를 화면에 그대로 보여준다.
"""
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "프로필"
URL = "https://www.wehago.com"

print()
print("=" * 60)
print("  위하고 로그인 (최초 1회)")
print("=" * 60)
print(f"  프로필 폴더: {PROFILE}")
print()

try:
    with sync_playwright() as p:
        print("  브라우저를 여는 중...")
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, timeout=60000)

        print()
        print("  브라우저가 열렸습니다.")
        print("  ------------------------------------------------------")
        print("   1. 열린 브라우저에서 위하고에 로그인하세요.")
        print("   2. 로그인이 끝나면 브라우저는 그대로 두고,")
        print("      이 검은 창으로 돌아와 Enter 를 누르세요.")
        print("  ------------------------------------------------------")
        print()
        input("  로그인을 마쳤으면 Enter >>> ")

        try:
            current = ctx.pages[-1] if ctx.pages else page
            print(f"\n  현재 주소: {current.url}")
            if "landing" in current.url:
                print("  [주의] 아직 로그아웃 화면입니다. 로그인이 안 된 것 같습니다.")
            else:
                print("  로그인된 것으로 보입니다.")
        except Exception:
            pass

        ctx.close()
        print("\n  세션을 저장했습니다. 이제 3_녹화.bat 을 실행하세요.")

except Exception:
    print()
    print("  브라우저를 열지 못했습니다. 원인:")
    print("-" * 60)
    traceback.print_exc()
    print("-" * 60)
    print()
    print("  '프로필' 폴더가 사용 중이라는 오류라면,")
    print("  작업 관리자에서 chrome.exe 를 모두 종료하거나")
    print("  '프로필' 폴더를 지우고 다시 실행하세요.")

print()
input("  창을 닫으려면 Enter >>> ")
