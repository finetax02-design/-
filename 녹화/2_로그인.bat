@echo off
chcp 949 >nul
title 위하고 자동화 - 로그인 (최초 1회)
echo.
echo  브라우저가 열립니다.
echo.
echo   1. 평소처럼 위하고에 로그인하세요.
echo   2. 로그인이 끝나면 브라우저를 그냥 닫으세요.
echo.
echo  로그인 정보는 이 폴더 안 프로필 폴더에만 저장되며
echo  녹화 파일에는 절대 기록되지 않습니다.
echo.
pause

python -m playwright open --channel chrome --user-data-dir="%~dp0프로필" https://www.wehago.com

echo.
echo  로그인 정보가 저장되었습니다. 이제 3_녹화.bat 을 실행하세요.
pause
