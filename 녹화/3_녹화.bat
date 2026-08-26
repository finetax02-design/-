@echo off
chcp 949 >nul
title 위하고 자동화 - 화면 녹화 (v2)

echo.
echo  ========================================================
echo   녹화 전 확인
echo  ========================================================
echo.
echo   * 실행 중인 크롬 창을 전부 닫아주세요.
echo     (크롬이 켜져 있으면 녹화가 안 됩니다)
echo.
echo   * 브라우저는 작업을 다 마친 뒤에 닫으세요.
echo     먼저 닫으면 아무것도 기록되지 않습니다.
echo.
pause

echo.
echo  브라우저와 'Playwright Inspector' 창이 함께 열립니다.
echo  Inspector 창에 코드가 한 줄씩 쌓이는지 꼭 확인하세요.
echo.
echo  [순서]
echo    1. 위하고 로그인
echo    2. 전자세금계산서 화면으로 이동
echo    3. 기간/구분/전표상태 설정 후 조회
echo    4. 미추천 건 하나에 계정과목 입력
echo    5. 과세 - 불공 변경, 전송(확정)
echo.
echo  다 하신 뒤 브라우저를 닫으면 녹화결과.py 가 만들어집니다.
echo.
pause

python -m playwright codegen --target python --user-data-dir="%~dp0프로필" -o "%~dp0녹화결과.py" https://www.wehago.com

echo.
if exist "%~dp0녹화결과.py" (
  echo  녹화결과.py 가 만들어졌습니다. 메모장으로 열어
  echo  page.click / page.fill 같은 줄이 여러 개 있는지 확인하세요.
  echo  비밀번호가 보이면 그 부분만 지우고 보내주세요.
) else (
  echo  파일이 만들어지지 않았습니다. 화면 메시지를 캡처해 알려주세요.
)
pause
