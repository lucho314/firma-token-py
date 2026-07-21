@echo off
setlocal
echo === Firmador Token - build ===

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :err

python make_icon.py
if errorlevel 1 goto :err

pyinstaller --noconfirm --clean firmador.spec
if errorlevel 1 goto :err

echo.
echo OK -> dist\FirmadorToken.exe
echo.
echo Para el instalador todo-en-uno, compilar con Inno Setup:
echo    iscc installer.iss
echo (produce Output\FirmadorToken-Setup.exe)
goto :eof

:err
echo.
echo *** Build FALLO ***
exit /b 1
