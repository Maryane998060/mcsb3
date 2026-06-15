@echo off
echo ==========================================
echo  MCS B3 - Liberando porta 5000 no Firewall
echo ==========================================
echo.

REM Remove regra antiga se existir
netsh advfirewall firewall delete rule name="MCS B3 - Flask 5000" >nul 2>&1

REM Cria nova regra liberando porta 5000 para rede local
netsh advfirewall firewall add rule name="MCS B3 - Flask 5000" dir=in action=allow protocol=TCP localport=5000 profile=private,domain

if %errorlevel%==0 (
    echo.
    echo [OK] Porta 5000 liberada com sucesso!
    echo Outros computadores da rede ja podem acessar http://192.168.1.29:5000
) else (
    echo.
    echo [ERRO] Nao foi possivel liberar a porta.
    echo Execute este arquivo como Administrador.
)

echo.
pause
