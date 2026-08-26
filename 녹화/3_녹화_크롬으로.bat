@echo off
chcp 949 >nul
title 위하고 자동화 - 화면 녹화 (설치된 크롬 사용)

echo.
echo  설치된 크롬으로 녹화합니다.
echo  크롬 창이 하나라도 열려 있으면 실패하니 전부 닫아주세요.
echo.
tasklist /fi "imagename eq chrome.exe" 2>nul | find /i "chrome.exe" >nul
if not errorlevel 1 (
  echo  [!] 크롬이 실행 중입니다.
  echo.
  set /p KILL="  지금 모두 종료할까요? (Y/N): "
  if /i "%KILL%"=="Y" taskkill /f /im chrome.exe >nul 2>&1
)
pause

python -m playwright codegen --channel chrome --target python --user-data-dir="%~dp0프로필" -o "%~dp0녹화결과.py" https://www.wehago.com
pause
