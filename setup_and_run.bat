@echo off
cd /d "%~dp0"
echo ============================================
echo   CardScan - Setup and Run
echo   Folder: %CD%
echo ============================================

if not exist "app.py" (
    echo ERROR: app.py not found here.
    pause & exit /b 1
)
if not exist "templates\index.html" (
    echo ERROR: templates\index.html missing!
    pause & exit /b 1
)

echo Installing packages...
python -m pip install --upgrade pip -q
python -m pip install flask easyocr pillow opencv-python numpy pyopenssl

echo.
echo Starting CardScan...
echo.
python app.py
pause
