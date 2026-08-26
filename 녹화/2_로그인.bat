@echo off
chcp 949 >nul
title 위하고 자동화 - 로그인 (최초 1회) v2

echo.
echo  ========================================================
echo   로그인 세션을 저장합니다 (최초 1회)
echo  ========================================================
echo.
echo   크롬을 닫으실 필요 없습니다.
echo   Playwright 전용 브라우저가 따로 열립니다.
echo.
echo   1. 열리는 브라우저에서 평소처럼 위하고에 로그인하세요.
echo   2. 로그인이 끝나면 브라우저를 닫으세요.
echo.
echo   로그인 정보는 이 폴더의 '프로필' 폴더에만 저장되고
echo   녹화 파일에는 기록되지 않습니다.
echo.
pause

python -m playwright open --user-data-dir="%~dp0프로필" https://www.wehago.com

echo.
if exist "%~dp0프로필" (
  echo  로그인 세션이 저장되었습니다. 이제 3_녹화.bat 을 실행하세요.
) else (
  echo  프로필 폴더가 만들어지지 않았습니다. 화면 메시지를 캡처해 알려주세요.
)
pause
