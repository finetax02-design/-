"""위하고 화면의 구조를 읽어 화면구조.txt 로 저장한다.

codegen 은 별도 프로그램이 하나 더 뜨는 방식이라 실패 지점이 많았다.
대신 브라우저 하나만 띄우고, 사용자가 원하는 화면까지 직접 이동한 뒤
그 화면의 요소 구조를 읽어온다.

거래처명이나 금액 같은 실제 자료는 담지 않는다.
입력칸의 이름표, 버튼 글자, 표의 제목줄 같은 화면 구조만 모은다.
"""
import os
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "화면구조.txt"

# OneDrive 로 동기화되는 폴더에 브라우저 프로필을 두면 파일 잠금 충돌이 난다.
# 항상 로컬 전용 경로를 쓴다.
PROFILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "wehago_auto" / "profile"

URL = "https://www.wehago.com"
lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def dump_frame(frame, depth: int) -> None:
    """한 프레임 안의 입력칸, 버튼, 표 제목을 뽑는다."""
    pad = "  " * depth
    say(f"\n{pad}--- 프레임: {frame.url[:110]} ---")

    # 입력칸과 선택상자: 무엇을 넣는 칸인지 알려주는 속성만 모은다
    fields = frame.evaluate("""() => {
        const pick = el => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            cls: (el.className || '').toString().slice(0, 80),
            placeholder: el.getAttribute('placeholder') || '',
            label: el.getAttribute('aria-label') || el.getAttribute('title') || '',
            role: el.getAttribute('role') || '',
        });
        return [...document.querySelectorAll('input, select, textarea')]
            .filter(el => el.offsetParent !== null).slice(0, 120).map(pick);
    }""")
    if fields:
        say(f"{pad}[입력칸 {len(fields)}개]")
        for f in fields:
            bits = [f"{k}={v}" for k, v in f.items() if v]
            say(f"{pad}  " + "  ".join(bits))

    # 버튼: 글자는 화면 문구라 그대로 담아도 된다
    buttons = frame.evaluate("""() => {
        return [...document.querySelectorAll('button, a[role=button], input[type=button], input[type=submit]')]
            .filter(el => el.offsetParent !== null)
            .slice(0, 80)
            .map(el => ({
                text: (el.innerText || el.value || '').trim().slice(0, 30),
                id: el.id || '',
                cls: (el.className || '').toString().slice(0, 60),
            }))
            .filter(b => b.text);
    }""")
    if buttons:
        say(f"{pad}[버튼 {len(buttons)}개]")
        for b in buttons:
            say(f"{pad}  \"{b['text']}\"  id={b['id']}  class={b['cls']}")

    # 표: 제목줄만. 자료 행은 담지 않는다.
    tables = frame.evaluate("""() => {
        return [...document.querySelectorAll('table')].slice(0, 10).map(t => ({
            id: t.id || '',
            cls: (t.className || '').toString().slice(0, 60),
            rows: t.rows.length,
            head: [...(t.rows[0] ? t.rows[0].cells : [])].map(c => c.innerText.trim().slice(0, 14)),
        })).filter(t => t.head.length);
    }""")
    if tables:
        say(f"{pad}[표 {len(tables)}개]")
        for t in tables:
            say(f"{pad}  id={t['id']}  class={t['cls']}  행수={t['rows']}")
            say(f"{pad}    제목줄: {' | '.join(t['head'])}")

    for child in frame.child_frames:
        if depth < 3:
            dump_frame(child, depth + 1)


print()
print("=" * 62)
print("  위하고 화면 구조 수집")
print("=" * 62)
print(f"  프로필 폴더: {PROFILE}")
print("  (OneDrive 충돌을 피하려고 로컬 폴더를 씁니다)")
print()

try:
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        print("  브라우저를 여는 중...")
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), headless=False, args=["--start-maximized"], no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, timeout=60000)

        print()
        print("  브라우저가 열렸습니다.")
        print("  " + "-" * 56)
        print("   1. 위하고에 로그인하세요.")
        print("   2. 전자세금계산서 화면까지 이동하세요.")
        print("   3. 기간과 구분을 정하고 조회해서, 자료가 보이게 하세요.")
        print("   4. 미추천 건이 한 건이라도 보이면 더 좋습니다.")
        print("   5. 그 상태에서 이 검은 창으로 돌아와 Enter 를 누르세요.")
        print("  " + "-" * 56)
        print()
        input("  화면이 준비되었으면 Enter >>> ")

        target = ctx.pages[-1] if ctx.pages else page
        say(f"주소: {target.url}")
        say(f"제목: {target.title()}")
        dump_frame(target.main_frame, 0)

        print()
        input("  계정과목 입력칸을 한 번 눌러보시고 다시 Enter (건너뛰려면 그냥 Enter) >>> ")
        say("\n\n########## 클릭 후 다시 수집 ##########")
        target = ctx.pages[-1] if ctx.pages else target
        say(f"주소: {target.url}")
        dump_frame(target.main_frame, 0)

        ctx.close()

except Exception:
    say("\n실패했습니다. 원인:")
    say(traceback.format_exc())

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("  이 파일을 보내주세요. 실제 거래 자료는 들어있지 않습니다.")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
