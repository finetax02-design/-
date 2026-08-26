"""playwright codegen 을 실행해 위하고 화면 조작을 녹화한다.

배치에서 직접 부르지 않고 파이썬에서 실행해, 오류가 나면
그 내용을 화면에 남긴다.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "프로필"
OUTPUT = HERE / "녹화결과.py"
URL = "https://www.wehago.com"

print()
print("=" * 60)
print("  위하고 화면 녹화")
print("=" * 60)
print()
print("  브라우저와 'Playwright Inspector' 창이 함께 열립니다.")
print()
print("  [꼭 확인] 클릭할 때마다 Inspector 창에 코드가 한 줄씩")
print("            쌓여야 정상입니다. 안 쌓이면 알려주세요.")
print()
print("  [녹화할 것]")
print("    1. 전자세금계산서 화면으로 이동")
print("    2. 기간 / 구분 / 전표상태 설정 후 조회")
print("    3. 미추천 건 하나에 계정과목 입력")
print("    4. 과세 - 불공 변경, 전송(확정)")
print()
print("  할 일을 모두 마친 뒤에 브라우저를 닫으세요.")
print("  먼저 닫으면 아무것도 기록되지 않습니다.")
print()
input("  준비되셨으면 Enter >>> ")

cmd = [
    sys.executable, "-m", "playwright", "codegen",
    "--target", "python",
    "--user-data-dir", str(PROFILE),
    "-o", str(OUTPUT),
    URL,
]
print(f"\n  실행: {' '.join(cmd)}\n")

proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

if proc.stdout and proc.stdout.strip():
    print(proc.stdout.strip())
if proc.stderr and proc.stderr.strip():
    print("\n  [오류 출력]")
    print(proc.stderr.strip())

print()
print("=" * 60)
if OUTPUT.exists():
    text = OUTPUT.read_text(encoding="utf-8", errors="replace")
    actions = sum(text.count(f".{verb}(") for verb in
                  ("click", "fill", "select_option", "press", "check", "type"))
    print(f"  녹화결과.py 생성됨 — 동작 {actions}개 기록")
    if actions < 3:
        print("  [주의] 기록된 동작이 너무 적습니다. 다시 녹화가 필요합니다.")
    else:
        print("  이 파일을 보내주세요.")
else:
    print(f"  녹화결과.py 가 만들어지지 않았습니다. (종료코드 {proc.returncode})")
print("=" * 60)
print()
input("  창을 닫으려면 Enter >>> ")
