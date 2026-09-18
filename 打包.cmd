@echo off
rem ══════════════════════════════════════════
rem  统一工具箱 一键打包脚本
rem  用法：双击运行，产物在 dist\统一工具箱.exe
rem ══════════════════════════════════════════
cd /d %~dp0

echo [1/2] PyInstaller 打包中（UPX 已关闭，降低杀软误报）...
venv\Scripts\python.exe -m PyInstaller "统一工具箱.spec" --noconfirm --distpath dist --workpath build
if errorlevel 1 (
    echo [错误] 打包失败，请检查上方报错信息
    pause
    exit /b 1
)
echo [2/2] 完成：dist\统一工具箱.exe

rem ── 可选：代码签名（拿到证书后启用）──
rem 前置：安装 Windows SDK 的 signtool，并把证书装进 U 盾/系统
rem signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /a "dist\统一工具箱.exe"

echo.
echo 分发建议：把 dist\ 里的 统一工具箱.exe 和 使用说明.txt 一起打包发送
pause
