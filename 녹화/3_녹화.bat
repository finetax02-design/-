@echo off
chcp 949 >nul
title 위하고 자동화 - 화면 녹화
echo.
echo  브라우저와 함께 '녹화 창'이 하나 더 열립니다.
echo  브라우저에서 하시는 모든 클릭과 입력이 녹화 창에 코드로 쌓입니다.
echo.
echo  아래 네 가지를 차례로 한 번씩만 해주세요.
echo.
echo   (1) 전자세금계산서 화면으로 이동
echo   (2) 기간/구분/전표상태 를 설정하고 조회
echo   (3) 미추천 건 하나에 계정과목을 입력
echo   (4) 과세 - 불공 을 바꾸고, 전송(확정) 까지
echo.
echo  다 하셨으면 브라우저를 닫으세요.
echo  이 폴더에 녹화결과.py 파일이 생깁니다.
echo.
pause

python -m playwright codegen --channel chrome --target python --user-data-dir="%~dp0프로필" -o "%~dp0녹화결과.py" https://www.wehago.com

echo.
echo  ============================================
echo   녹화결과.py 파일이 만들어졌습니다.
echo   그 파일을 그대로 보내주세요.
echo  ============================================
pause
