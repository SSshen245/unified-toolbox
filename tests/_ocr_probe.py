"""OCR probe against a generated image; prints result for manual verification."""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PS1 = HERE / "_ocr_probe.ps1"

from PIL import Image, ImageDraw, ImageFont

FONT = Path(r"C:\Windows\Fonts\arial.ttf")

with tempfile.TemporaryDirectory() as folder:
    image = Path(folder) / "sample.png"
    picture = Image.new("RGB", (560, 160), "white")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype(str(FONT), 48) if FONT.exists() else ImageFont.load_default()
    draw.text((24, 50), "HELLO 12345", fill="black", font=font)
    picture.save(image)
    out = Path(folder) / "out.txt"
    powershell = str(Path(sys.executable).parents[1] / "System32" / "WindowsPowerShell"
                     / "v1.0" / "powershell.exe")
    if not Path(powershell).exists():
        powershell = str(Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"))
    r = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-File", str(PS1), str(image), str(out)],
                       capture_output=True)
    print("returncode:", r.returncode)
    print("stdout:", r.stdout.decode("utf-8", "replace")[:400])
    print("stderr:", r.stderr.decode("gbk", "replace")[:600])
    print("result:", repr(out.read_text(encoding="utf-8-sig")) if out.exists() else "NO OUTPUT FILE")