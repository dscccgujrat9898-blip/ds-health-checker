import os
import sys
import time
import json
import threading
import platform
import tkinter as tk
from tkinter import ttk, messagebox

import psutil
import wmi

from smart import get_smart_summary, find_smartctl_path


APP_NAME = "DS Drive Health Checker"


def human_bytes(num: float) -> str:
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if num < step:
            return f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} EB"


def safe_run(func, default="N/A"):
    try:
        return func()
    except Exception:
        return default


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x620")
        self.minsize(900, 560)

        # Style
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        # Header
        header = ttk.Frame(self, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, text="CPU • RAM • HDD/SSD • SMART • Temperature",
                  font=("Segoe UI", 10)).pack(side="left", padx=12)

        # Tabs
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)

        self.tab_overview = ttk.Frame(self.tabs, padding=12)
        self.tab_drives = ttk.Frame(self.tabs, padding=12)
        self.tab_smart = ttk.Frame(self.tabs, padding=12)
        self.tab_logs = ttk.Frame(self.tabs, padding=12)

        self.tabs.add(self.tab_overview, text="Overview")
        self.tabs.add(self.tab_drives, text="Drives")
        self.tabs.add(self.tab_smart, text="SMART Health")
        self.tabs.add(self.tab_logs, text="Logs")

        # Overview UI
        self.overview_text = tk.Text(self.tab_overview, height=18, wrap="word")
        self.overview_text.pack(fill="both", expand=True)

        # Drives UI (table)
        cols = ("Drive", "Mount", "FS", "Total", "Used", "Free", "Use%")
        self.drive_tree = ttk.Treeview(self.tab_drives, columns=cols, show="headings", height=12)
        for c in cols:
            self.drive_tree.heading(c, text=c)
            self.drive_tree.column(c, width=120, anchor="w")
        self.drive_tree.column("Mount", width=160)
        self.drive_tree.pack(fill="both", expand=True)

        # SMART UI
        self.smart_text = tk.Text(self.tab_smart, height=18, wrap="word")
        self.smart_text.pack(fill="both", expand=True)

        # Logs UI
        self.log_text = tk.Text(self.tab_logs, height=18, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        # Footer Buttons
        footer = ttk.Frame(self, padding=12)
        footer.pack(fill="x")
        self.btn_refresh = ttk.Button(footer, text="Refresh Now", command=self.refresh_all)
        self.btn_refresh.pack(side="left")

        self.btn_export = ttk.Button(footer, text="Export Report (JSON)", command=self.export_report)
        self.btn_export.pack(side="left", padx=8)

        self.lbl_status = ttk.Label(footer, text="Ready")
        self.lbl_status.pack(side="right")

        self.report_cache = {}

        # Initial refresh + auto timer
        self.refresh_all()
        self._stop = False
        threading.Thread(target=self.auto_refresh_loop, daemon=True).start()

    def log(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")

    def auto_refresh_loop(self):
        # refresh every 5 seconds
        while not self._stop:
            time.sleep(5)
            self.refresh_overview(light=True)

    def on_close(self):
        self._stop = True
        self.destroy()

    def refresh_all(self):
        self.lbl_status.config(text="Refreshing...")
        self.refresh_overview(light=False)
        self.refresh_drives()
        self.refresh_smart()
        self.lbl_status.config(text="Updated")

    def refresh_overview(self, light: bool):
        # light=True => fast updates (cpu/ram)
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5 if not light else None)
            vm = psutil.virtual_memory()

            # CPU temperature via WMI (not always supported, depends on hardware)
            cpu_temp = safe_run(lambda: self.get_cpu_temp_wmi(), default=None)

            lines = []
            lines.append(f"System: {platform.platform()}")
            lines.append(f"CPU Usage: {cpu_percent:.1f}%")
            if cpu_temp is not None:
                lines.append(f"CPU Temp: {cpu_temp:.1f} °C")
            else:
                lines.append("CPU Temp: Not available (hardware/WMI support required)")

            lines.append("")
            lines.append(f"RAM Total: {human_bytes(vm.total)}")
            lines.append(f"RAM Used : {human_bytes(vm.used)} ({vm.percent:.1f}%)")
            lines.append(f"RAM Free : {human_bytes(vm.available)}")

            # Disk IO summary
            dio = psutil.disk_io_counters()
            if dio:
                lines.append("")
                lines.append(f"Disk Read : {human_bytes(dio.read_bytes)} (total since boot)")
                lines.append(f"Disk Write: {human_bytes(dio.write_bytes)} (total since boot)")

            # Uptime
            boot = psutil.boot_time()
            up_sec = time.time() - boot
            hrs = int(up_sec // 3600)
            lines.append("")
            lines.append(f"Uptime: ~{hrs} hours")

            text = "\n".join(lines)

            self.overview_text.delete("1.0", "end")
            self.overview_text.insert("1.0", text)

            self.report_cache["overview"] = {
                "system": platform.platform(),
                "cpu_usage_percent": cpu_percent,
                "cpu_temp_c": cpu_temp,
                "ram_total": vm.total,
                "ram_used": vm.used,
                "ram_available": vm.available,
                "ram_percent": vm.percent,
                "uptime_hours": hrs
            }

        except Exception as e:
            self.log(f"Overview refresh error: {e}")

    def refresh_drives(self):
        try:
            for i in self.drive_tree.get_children():
                self.drive_tree.delete(i)

            parts = psutil.disk_partitions(all=False)
            drives_data = []
            for p in parts:
                if "cdrom" in p.opts.lower():
                    continue
                usage = safe_run(lambda: psutil.disk_usage(p.mountpoint), default=None)
                if not usage:
                    continue

                row = (
                    p.device,
                    p.mountpoint,
                    p.fstype,
                    human_bytes(usage.total),
                    human_bytes(usage.used),
                    human_bytes(usage.free),
                    f"{usage.percent:.1f}%"
                )
                self.drive_tree.insert("", "end", values=row)
                drives_data.append({
                    "device": p.device,
                    "mount": p.mountpoint,
                    "fstype": p.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                })

            self.report_cache["drives"] = drives_data
            self.log("Drives refreshed.")
        except Exception as e:
            self.log(f"Drives refresh error: {e}")

    def refresh_smart(self):
        try:
            smartctl = find_smartctl_path()
            if not smartctl:
                self.smart_text.delete("1.0", "end")
                self.smart_text.insert("1.0",
                    "smartctl not found in bundle.\n"
                    "If you built from GitHub Actions, smartctl should be included.\n"
                )
                self.report_cache["smart"] = {"error": "smartctl not found"}
                return

            summary = get_smart_summary(smartctl_path=smartctl)

            pretty = json.dumps(summary, indent=2, ensure_ascii=False)
            self.smart_text.delete("1.0", "end")
            self.smart_text.insert("1.0", pretty)

            self.report_cache["smart"] = summary
            self.log("SMART refreshed.")
        except Exception as e:
            self.log(f"SMART refresh error: {e}")

    def export_report(self):
        try:
            out = {
                "app": APP_NAME,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "report": self.report_cache
            }
            fname = f"ds_health_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Exported", f"Report saved as:\n{os.path.abspath(fname)}")
            self.log(f"Report exported: {fname}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.log(f"Export error: {e}")

    def get_cpu_temp_wmi(self):
        # Many PCs won't provide CPU temp via this class. We'll try common WMI sources.
        w = wmi.WMI(namespace="root\\WMI")
        temps = []
        # MSAcpi_ThermalZoneTemperature returns tenths of Kelvin
        for t in w.MSAcpi_ThermalZoneTemperature():
            c = (t.CurrentTemperature / 10.0) - 273.15
            if 0 < c < 120:
                temps.append(c)
        if temps:
            return sum(temps) / len(temps)
        return None


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
