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
echo  ---- 프로필 폴더 (로그인 세션) ----
if exist "%~dp0프로필" (
  echo  있음 - 로그인 세션이 저장되어 있습니다. 3_녹화.bat 으로 진행하세요.
) else (
  echo  없음 - 2_로그인.bat 을 먼저 실행해야 합니다.
)
echo.
echo  ---- 실행 중인 크롬 ----
tasklist /fi "imagename eq chrome.exe" 2>nul | find /i "chrome.exe" >nul
if errorlevel 1 (
  echo  없음
) else (
  echo  실행 중 - 상관없습니다.
  echo  2_로그인.bat 과 3_녹화.bat 은 크롬을 쓰지 않습니다.
  echo  3_녹화_크롬으로.bat 을 쓸 때만 크롬을 모두 닫으면 됩니다.
)
echo.
pause
