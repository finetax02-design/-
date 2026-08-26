@echo off
chcp 949 >nul
title 환경 점검
echo.
echo  ---- Python ----
python --version
echo.
echo  ---- Playwright ----
python -m playwright --version
echo.
echo  ---- 프로필 폴더 ----
if exist "%~dp0프로필" (echo  있음 - 로그인 세션이 저장되어 있습니다) else (echo  없음 - 2_로그인.bat 이 실행되지 않았습니다)
echo.
echo  ---- 실행 중인 크롬 ----
tasklist /fi "imagename eq chrome.exe" 2>nul | find /i "chrome.exe" >nul
if errorlevel 1 (echo  없음 - 좋습니다) else (echo  실행 중 - 녹화 전에 모두 닫아야 합니다)
echo.
echo  위 내용을 그대로 캡처해서 보내주세요.
pause
