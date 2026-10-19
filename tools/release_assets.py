"""Create a geometric source icon and copy installed third-party license texts."""
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def icon():
    directory = ROOT / "assets"
    directory.mkdir(exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), 44, fill="#163b60")
    for left, top, right, bottom, color in [(49, 58, 87, 189, "#e7c46a"),
                                           (100, 77, 137, 189, "#76b9bd"),
                                           (150, 45, 199, 189, "#f4f1e7")]:
        draw.rounded_rectangle((left, top, right, bottom), 6, fill=color)
        draw.line((left + 9, top + 18, right - 9, top + 18), fill="#163b60", width=4)
    draw.rounded_rectangle((37, 195, 213, 208), 5, fill="#ffffff")
    image.save(directory / "courseshelf.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


def notices(release):
    directory = release / "licenses"
    directory.mkdir(exist_ok=True)
    packages = ["PySide6", "PySide6_Essentials", "shiboken6", "rapidocr", "onnxruntime", "Send2Trash", "Pillow",
                "numpy", "opencv-python", "pyclipper", "Shapely", "PyYAML", "tqdm", "omegaconf", "requests",
                "six", "colorlog", "antlr4-python3-runtime", "charset-normalizer", "idna", "urllib3", "certifi",
                "packaging"]
    inventory = []
    for package in packages:
        try:
            installed = distribution(package)
        except PackageNotFoundError:
            continue
        inventory.append(f"{package}=={installed.version}")
        for entry in installed.files or []:
            if any(part.casefold().startswith(("license", "copying", "notice")) for part in entry.parts):
                source = Path(installed.locate_file(entry))
                if source.is_file():
                    target = directory / package / str(entry).replace("/", "_").replace("\\", "_")
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
    (directory / "package-versions.txt").write_text("\n".join(inventory), encoding="utf-8")


if __name__ == "__main__":
    icon()
    if len(sys.argv) > 1:
        notices(Path(sys.argv[1]))
