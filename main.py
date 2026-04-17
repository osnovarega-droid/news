import sys
from pathlib import Path

import customtkinter

from Managers.GSIManager import GSIManager
from Managers.VideoConfigManager import VideoConfigManager
from ui.app import App


APP_ICON_CANDIDATES = ("Icon2.ico", "Icon1.ico")


def resource_path(relative_path: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


def _resolve_app_icon_path():
    for icon_name in APP_ICON_CANDIDATES:
        icon_path = resource_path(icon_name)
        if icon_path.exists():
            return icon_path
    return None


def _set_window_icon(window):
    icon_path = _resolve_app_icon_path()
    if not icon_path:
        return

    try:
        window.iconbitmap(str(icon_path))
    except Exception:
        pass

    try:
        window.wm_iconbitmap(str(icon_path))
    except Exception:
        pass


if __name__ == "__main__":
    gsi = GSIManager()

    def startup_services_initializer():
        startup_gpu_info = None
        try:
            video_config_manager = VideoConfigManager()
            startup_gpu_info = video_config_manager.sync_on_startup()
        except Exception as exc:
            print(f"⚠️ Ошибка инициализации VideoConfigManager: {exc}")

        try:
            gsi.start()
        except Exception as exc:
            print(f"⚠️ Ошибка запуска GSIManager: {exc}")

        return startup_gpu_info

    app = App(
        gsi_manager=gsi,
        startup_services_initializer=startup_services_initializer
    )

    app.title("Goose Panel")
    _set_window_icon(app)

    app.mainloop()