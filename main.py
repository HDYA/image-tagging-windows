"""
Image Tagging Desktop - GUI 入口
"""
import sys
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Image Tagging Desktop")
    app.setOrganizationName("HDYA")

    # 高 DPI 缩放
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
