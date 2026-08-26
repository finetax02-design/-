@echo off
chcp 949 >nul
title 위하고 자동화 - 설치
echo.
echo  [1/2] Playwright 설치 중...
python -m pip install --upgrade playwright
if errorlevel 1 goto :fail
echo.
echo  [2/2] 브라우저 구성 요소 설치 중... (몇 분 걸립니다)
python -m playwright install chromium
if errorlevel 1 goto :fail
echo.
echo  ============================================
echo   설치 완료. 2_로그인.bat 을 실행하세요.
echo  ============================================
pause
exit /b 0

:fail
echo.
echo  설치에 실패했습니다. 위 메시지를 그대로 알려주세요.
pause
exit /b 1
