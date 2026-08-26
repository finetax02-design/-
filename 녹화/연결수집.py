"""이미 실행 중인 진짜 크롬에 붙어서 화면 구조를 읽는다.

Playwright 가 브라우저를 직접 띄우면 위하고 T 모듈이 빈 화면으로만 나왔다.
자동화된 브라우저라는 표시(navigator.webdriver 등)를 보고 화면을 안 그리는
서비스가 있어서다.

그래서 브라우저는 크롬열기.bat 이 평범하게 띄우고, 이 스크립트는
디버깅 포트로 '붙기만' 한다. 위하고 입장에서는 평소 크롬과 구별되지 않는다.

거래처명이나 금액 같은 실제 자료는 담지 않는다.
"""
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "화면구조.txt"
CDP = "http://localhost:9222"

lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def dump_frame(frame, depth: int) -> None:
    pad = "  " * depth
    say(f"\n{pad}--- 프레임: {frame.url[:110]} ---")
    try:
        fields = frame.evaluate("""() => [...document.querySelectorAll('input, select, textarea')]
            .filter(el => el.offsetParent !== null).slice(0, 150).map(el => ({
                tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
                id: el.id || '', name: el.getAttribute('name') || '',
                cls: (el.className || '').toString().slice(0, 80),
                placeholder: el.getAttribute('placeholder') || '',
                label: el.getAttribute('aria-label') || el.getAttribute('title') || '',
            }))""")
        if fields:
            say(f"{pad}[입력칸 {len(fields)}개]")
            for f in fields:
                say(f"{pad}  " + "  ".join(f"{k}={v}" for k, v in f.items() if v))

        buttons = frame.evaluate("""() => [...document.querySelectorAll(
            'button, a[role=button], input[type=button], input[type=submit], [class*=btn]')]
            .filter(el => el.offsetParent !== null).slice(0, 100)
            .map(el => ({ text: (el.innerText || el.value || '').trim().slice(0, 30),
                          id: el.id || '', cls: (el.className || '').toString().slice(0, 60) }))
            .filter(b => b.text)""")
        if buttons:
            say(f"{pad}[버튼 {len(buttons)}개]")
            for b in buttons:
                say(f"{pad}  \"{b['text']}\"  id={b['id']}  class={b['cls']}")

        tables = frame.evaluate("""() => [...document.querySelectorAll('table')].slice(0, 12)
            .map(t => ({ id: t.id || '', cls: (t.className || '').toString().slice(0, 60),
                         rows: t.rows.length,
                         head: [...(t.rows[0] ? t.rows[0].cells : [])]
                                 .map(c => c.innerText.trim().slice(0, 14)) }))
            .filter(t => t.head.length)""")
        if tables:
            say(f"{pad}[표 {len(tables)}개]")
            for t in tables:
                say(f"{pad}  id={t['id']}  class={t['cls']}  행수={t['rows']}")
                say(f"{pad}    제목줄: {' | '.join(t['head'])}")
    except Exception as exc:
        say(f"{pad}(읽지 못함: {str(exc)[:120]})")

    for child in frame.child_frames:
        if depth < 3:
            dump_frame(child, depth + 1)


def dump_all(browser, title: str) -> None:
    pages = [pg for ctx in browser.contexts for pg in ctx.pages]
    say(f"\n\n{'#' * 60}\n#  {title} — 열린 탭 {len(pages)}개\n{'#' * 60}")
    for i, pg in enumerate(pages):
        try:
            say(f"\n===== 탭 {i + 1} =====")
            say(f"주소: {pg.url}")
            say(f"제목: {pg.title()}")
            info = pg.evaluate("""() => ({
                len: document.body ? document.body.innerText.length : 0,
                webdriver: navigator.webdriver,
            })""")
            say(f"본문 글자수: {info['len']}   navigator.webdriver={info['webdriver']}"
                + ("   <-- 비어 있음" if info["len"] < 20 else ""))
            dump_frame(pg.main_frame, 0)
        except Exception as exc:
            say(f"탭 {i + 1} 읽기 실패: {str(exc)[:150]}")


print()
print("=" * 62)
print("  위하고 화면 구조 수집 (실행 중인 크롬에 연결)")
print("=" * 62)
print()
print("  먼저 크롬열기.bat 으로 크롬을 띄우고,")
print("  위하고 로그인 -> 회사 선택 -> 전자세금계산서 조회까지")
print("  마친 상태여야 합니다.")
print()
input("  준비되었으면 Enter >>> ")

try:
    with sync_playwright() as p:
        print(f"\n  {CDP} 에 연결 중...")
        browser = p.chromium.connect_over_cdp(CDP)
        print(f"  연결 성공. 컨텍스트 {len(browser.contexts)}개")

        dump_all(browser, "화면 구조")

        print()
        input("  계정과목 입력칸을 눌러보시고 Enter (건너뛰려면 그냥 Enter) >>> ")
        dump_all(browser, "클릭 후")

        browser.close()   # 연결만 끊는다. 크롬은 그대로 켜져 있다.

except Exception:
    say("\n연결에 실패했습니다. 원인:")
    say(traceback.format_exc())
    say("\n크롬열기.bat 으로 띄운 크롬 창이 켜져 있는지 확인하세요.")
    say("평소 쓰던 크롬이 아니라, 그 배치가 띄운 크롬이어야 합니다.")

OUT.write_text("\n".join(lines), encoding="utf-8")
print()
print("=" * 62)
print(f"  저장됨: {OUT}")
print("=" * 62)
print()
input("  창을 닫으려면 Enter >>> ")
