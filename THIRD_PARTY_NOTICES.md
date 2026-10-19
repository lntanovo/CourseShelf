# CourseShelf third-party notices

CourseShelf is MIT licensed. This portable folder contains dynamic libraries and local OCR models.
Installed package versions and available original license texts are included under `licenses/`.
No online service or model download is required at runtime.

| Component | License / source |
| --- | --- |
| PySide6, shiboken6, Qt (dynamic DLLs) | LGPLv3 / GPLv3 / commercial options; this distribution uses the LGPL option. [Qt LGPL](https://doc.qt.io/qt-6/lgpl.html), [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git/), [Qt source](https://download.qt.io/archive/qt/) |
| RapidOCR | Apache-2.0. [Source and license](https://github.com/RapidAI/RapidOCR) |
| PP-OCRv6 detection / recognition, PP-OCR classification models | PaddleOCR project, Apache-2.0. [Model source](https://github.com/PaddlePaddle/PaddleOCR), [License](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE) |
| ONNX Runtime | MIT. [Source and license](https://github.com/microsoft/onnxruntime) |
| Send2Trash | BSD-3-Clause. [Source](https://github.com/arsenetar/send2trash) |
| Pillow | HPND and bundled library notices. [Source](https://github.com/python-pillow/Pillow) |
| OpenCV / opencv-python | Apache-2.0 and bundled third-party notices. [Source](https://github.com/opencv/opencv-python) |
| NumPy / OpenBLAS | BSD and bundled notices. [NumPy source](https://github.com/numpy/numpy) |
| Python | PSF license and bundled notices. [Source](https://www.python.org/downloads/source/) |
| UPX 5.2.1 (build tool) | GPL with special exception for compressed executables. Only selected OCR/numeric libraries are packed. [Source and exception](https://github.com/upx/upx/blob/devel/LICENSE) |
| Other Python dependencies | Original notices and installed versions under `licenses/`. |

The Qt DLLs remain separately replaceable; users may relink or replace compatible LGPL libraries
and debug modifications to those libraries. This application imposes no restriction on reverse
engineering for debugging such modifications. Source for this application and its build scripts:
see the repository URL in the accompanying README. Keep these notices when redistributing.

This build is unsigned. Windows may display SmartScreen prompts. Code signing requires a separate certificate.
