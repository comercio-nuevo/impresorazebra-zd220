"""Escribe el LaunchAgent de esta Mac. No guarda rutas personales en el repo."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "com.cazatoy.labels.plist"
DEST = Path.home() / "Library/LaunchAgents/com.cazatoy.labels.plist"


def main() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("PROJECT_DIR", str(ROOT))
    text = text.replace("HOME", str(Path.home()))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(text, encoding="utf-8")
    print(DEST)


if __name__ == "__main__":
    main()
