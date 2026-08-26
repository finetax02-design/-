"""위하고 화면의 구조를 읽어 화면구조.txt 로 저장한다 (v2).

v1 에서 두 가지가 걸렸다.
  1. 브라우저를 닫아도 크롬 프로세스가 남아 프로필 폴더를 잠갔다.
     -> 실행 전에 잠금 파일을 지우고, 그래도 막히면 새 프로필로 넘어간다.
  2. 위하고 T 모듈이 새 창으로 열리는데 빈 창만 보였다.
     -> 새로 열리는 창을 모두 추적하고, 콘솔 오류를 함께 기록한다.

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
PROFILE_ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "wehago_auto"
URL = "https://www.wehago.com"

lines: list[str] = []
console_errors: list[str] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def free_profile() -> Path:
    """잠기지 않은 프로필 폴더를 준비한다.

    크롬은 프로필 폴더에 SingletonLock 등을 만들어 중복 실행을 막는다.
    앞선 실행의 프로세스가 남아 있으면 이 파일이 안 지워져 다음 실행이 실패한다.
    """
    for n in range(20):
        path = PROFILE_ROOT / (f"profile{n}" if n else "profile")
        path.mkdir(parents=True, exist_ok=True)
        stuck = False
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            f = path / name
            if not f.exists():
                continue
            try:
                f.unlink()
            except OSError:
                stuck = True  # 아직 쓰는 프로세스가 있다
        if not stuck:
            return path
        print(f"  {path.name} 은(는) 아직 사용 중입니다. 다음 폴더로 넘어갑니다.")
    raise RuntimeError("쓸 수 있는 프로필 폴더를 찾지 못했습니다.")


def watch(page, tag: str) -> None:
    """빈 창의 원인을 알기 위해 콘솔 오류와 실패한 요청을 기록한다."""
    page.on("console", lambda m: m.type == "error"
            and console_errors.append(f"[{tag}] 콘솔: {m.text[:200]}"))
    page.on("pageerror", lambda e: console_errors.append(f"[{tag}] 오류: {str(e)[:200]}"))
    page.on("requestfailed", lambda r: console_errors.append(
        f"[{tag}] 요청실패: {r.url[:120]} ({r.failure})"))


def dump_frame(frame, depth: int) -> None:
    pad = "  " * depth
    say(f"\n{pad}--- 프레임: {frame.url[:110]} ---")
    try:
        fields = frame.evaluate("""() => [...document.querySelectorAll('input, select, textarea')]
            .filter(el => el.offsetParent !== null).slice(0, 120).map(el => ({
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
            'button, a[role=button], input[type=button], input[type=submit]')]
            .filter(el => el.offsetParent !== null).slice(0, 80)
            .map(el => ({ text: (el.innerText || el.value || '').trim().slice(0, 30),
                          id: el.id || '', cls: (el.className || '').toString().slice(0, 60) }))
            .filter(b => b.text)""")
        if buttons:
            say(f"{pad}[버튼 {len(buttons)}개]")
            for b in buttons:
                say(f"{pad}  \"{b['text']}\"  id={b['id']}  class={b['cls']}")

        tables = frame.evaluate("""() => [...document.querySelectorAll('table')].slice(0, 10)
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
        say(f"{pad}(이 프레임은 읽지 못했습니다: {str(exc)[:120]})")

    for child in frame.child_frames:
        if depth < 3:
            dump_frame(child, depth + 1)


def dump_all(ctx, title: str) -> None:
    say(f"\n\n{'#' * 60}\n#  {title}  — 열린 창 {len(ctx.pages)}개\n{'#' * 60}")
    for i, pg in enumerate(ctx.pages):
        try:
            say(f"\n===== 창 {i + 1} =====")
            say(f"주소: {pg.url}")
            say(f"제목: {pg.title()}")
            body = pg.evaluate("() => (document.body ? document.body.innerText.length : 0)")
            say(f"본문 글자수: {body}   {'<-- 비어 있음' if body < 20 else ''}")
            dump_frame(pg.main_frame, 0)
        except Exception as exc:
            say(f"창 {i + 1} 을 읽지 못했습니다: {str(exc)[:150]}")


print()
print("=" * 62)
print("  위하고 화면 구조 수집 (v2)")
print("=" * 62)

try:
    profile = free_profile()
    print(f"  프로필: {profile}")
    print()

    with sync_playwright() as p:
        ctx = None
        for channel in ("chrome", None):   # 위하고는 실제 크롬에서 더 잘 뜬다
            try:
                print(f"  브라우저 실행 중 ({channel or '기본 브라우저'})...")
                ctx = p.chromium.launch_persistent_context(
                    str(profile), headless=False, channel=channel,
                    args=["--start-maximized"], no_viewport=True)
                print(f"  성공: {channel or '기본 브라우저'}")
                break
            except Exception as exc:
                print(f"  실패: {str(exc)[:150]}")
        if ctx is None:
            raise RuntimeError("어떤 브라우저로도 실행하지 못했습니다.")

        for pg in ctx.pages:
            watch(pg, "첫창")
        ctx.on("page", lambda pg: (watch(pg, "새창"),
                                   print(f"  >> 새 창이 열렸습니다: {pg.url[:80]}")))

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, timeout=60000)

        print()
        print("  " + "-" * 56)
        print("   1. 위하고 로그인 -> 회사 선택")
        print("   2. 전자세금계산서 화면까지 이동, 조회해서 자료가 보이게")
        print("   3. 빈 창이 나와도 그대로 두고 Enter 를 누르세요.")
        print("      빈 창의 원인도 함께 기록됩니다.")
        print("  " + "-" * 56)
        print()
        input("  준비되었으면 Enter >>> ")
        dump_all(ctx, "화면 구조")

        print()
        input("  계정과목 입력칸을 눌러보시고 Enter (건너뛰려면 그냥 Enter) >>> ")
        dump_all(ctx, "클릭 후")

        if console_errors:
            say(f"\n\n{'#' * 60}\n#  브라우저 오류 기록 ({len(console_errors)}건)\n{'#' * 60}")
            for e in console_errors[:80]:
                say(e)

        try:
            ctx.close()
        except Exception:
            pass

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
