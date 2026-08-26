@echo off
chcp 949 >nul
title 위하고용 크롬 열기

set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
  echo  크롬을 찾지 못했습니다. 설치 경로를 알려주세요.
  pause
  exit /b 1
)

echo.
echo  크롬을 엽니다: %CHROME%
echo.
echo  이 크롬은 평소 쓰시는 크롬과 별개입니다.
echo  클로드 창은 닫지 않으셔도 됩니다.
echo.
echo  열리면 위하고 로그인 - 회사 선택 - 전자세금계산서 조회까지
echo  평소처럼 진행하세요. 빈 창이 나와도 닫지 마세요.
echo.
echo  그 상태에서 5_연결수집.bat 을 실행하시면 됩니다.
echo  (이 검은 창은 그대로 두세요)
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%LocalAppData%\wehago_chrome" https://www.wehago.com

echo  크롬을 띄웠습니다. 작업이 끝날 때까지 이 창을 닫지 마세요.
pause
