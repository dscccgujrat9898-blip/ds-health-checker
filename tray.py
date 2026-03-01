import threading
import time
from PIL import Image
import pystray
from win10toast import ToastNotifier

class TrayController:
    def __init__(self, icon_path, on_open, on_quit):
        self.on_open = on_open
        self.on_quit = on_quit
        self.toaster = ToastNotifier()
        self._stop = False

        img = Image.open(icon_path)
        menu = pystray.Menu(
            pystray.MenuItem("Open DS Health Checker", self._open),
            pystray.MenuItem("Quit", self._quit),
        )
        self.icon = pystray.Icon("DS_Health_Checker", img, "DS Health Checker", menu)

    def run_detached(self):
        threading.Thread(target=self.icon.run, daemon=True).start()

    def notify(self, title, msg):
        try:
            self.toaster.show_toast(title, msg, duration=5, threaded=True)
        except Exception:
            pass

    def stop(self):
        self._stop = True
        try:
            self.icon.stop()
        except Exception:
            pass

    def _open(self, icon=None, item=None):
        self.on_open()

    def _quit(self, icon=None, item=None):
        self.on_quit()
