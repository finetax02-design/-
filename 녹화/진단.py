"""브라우저가 왜 안 열리는지 알아내고 결과를 진단결과.txt 로 남긴다."""
import platform
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "진단결과.txt"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def section(title: str) -> None:
    say()
    say("=" * 60)
    say(f"  {title}")
    say("=" * 60)


section("기본 정보")
say(f"Python  : {sys.version}")
say(f"실행파일: {sys.executable}")
say(f"OS      : {platform.platform()}")

section("Playwright 패키지")
try:
    import playwright
    say(f"버전    : {getattr(playwright, '__version__', '알 수 없음')}")
    say(f"설치위치: {Path(playwright.__file__).parent}")
except Exception:
    say("패키지를 불러오지 못했습니다.")
    say(traceback.format_exc())
    LOG.write_text("\n".join(lines), encoding="utf-8")
    raise SystemExit(1)

section("브라우저 본체 설치")
say("playwright install chromium 실행 중... (처음이면 몇 분 걸립니다)")
try:
    proc = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    say(f"종료코드: {proc.returncode}")
    for stream in (proc.stdout, proc.stderr):
        if stream and stream.strip():
            say(stream.strip()[-1500:])
except Exception:
    say(traceback.format_exc())

section("브라우저 열기 시험")
from playwright.sync_api import sync_playwright

ok = False
try:
    with sync_playwright() as p:
        say(f"chromium 실행파일 경로: {p.chromium.executable_path}")
        say(f"파일 존재 여부: {Path(p.chromium.executable_path).exists()}")

        # 1) 가장 단순한 실행
        say("\n[1] 일반 실행 시도...")
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.wehago.com", timeout=60000)
        say(f"    성공. 페이지 제목: {page.title()}")
        say(f"    최종 주소: {page.url}")
        browser.close()

        # 2) 2_로그인.bat 과 같은 방식 (프로필 폴더 사용)
        say("\n[2] 프로필 폴더 방식 시도...")
        ctx = p.chromium.launch_persistent_context(str(HERE / "프로필"), headless=False)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://www.wehago.com", timeout=60000)
        say(f"    성공. 페이지 제목: {pg.title()}")
        ctx.close()
        ok = True
except Exception:
    say("\n실패했습니다. 아래가 원인입니다.")
    say(traceback.format_exc())

section("결론")
if ok:
    say("브라우저가 정상적으로 열립니다.")
    say("프로필 폴더도 만들어졌으니 3_녹화.bat 으로 진행하세요.")
else:
    say("브라우저를 열지 못했습니다. 위 오류 내용을 그대로 보내주세요.")

LOG.write_text("\n".join(lines), encoding="utf-8")
print(f"\n>>> 결과가 저장되었습니다: {LOG}")
