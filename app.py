import os
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from monitor import get_snapshot, human_bytes
from cleanup import cleanup_temp_files, open_windows_security, defender_quick_scan, defender_full_scan, defender_status
from tray import TrayController

APP_NAME = "DS Drive Health Checker"

# Alert thresholds (you can tune)
TH_CPU = 90
TH_RAM = 90
TH_DISK_FREE_PCT = 10
TH_CPU_TEMP = 85  # requires hardware temp source to show

def resource_path(relative: str) -> str:
    base = getattr(__import__("sys"), "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)

class Card(ttk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, padding=12)
        self["style"] = "Card.TFrame"
        self.title = ttk.Label(self, text=title, style="CardTitle.TLabel")
        self.title.pack(anchor="w")
        self.body = ttk.Frame(self, style="CardBody.TFrame")
        self.body.pack(fill="both", expand=True, pady=(8,0))

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1080x680")
        self.minsize(980, 620)

        self._stop = False
        self.last_alert_ts = 0

        self._build_styles()

        header = ttk.Frame(self, padding=14)
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(header, text="CPU • RAM • HDD/SSD • SMART • Temperature • Tray Alerts",
                  font=("Segoe UI", 10)).pack(side="left", padx=12)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)

        self.tab_dashboard = ttk.Frame(self.tabs, padding=10)
        self.tab_drives = ttk.Frame(self.tabs, padding=10)
        self.tab_smart = ttk.Frame(self.tabs, padding=10)
        self.tab_tools = ttk.Frame(self.tabs, padding=10)
        self.tab_logs = ttk.Frame(self.tabs, padding=10)

        self.tabs.add(self.tab_dashboard, text="Dashboard")
        self.tabs.add(self.tab_drives, text="Drives")
        self.tabs.add(self.tab_smart, text="SMART Health")
        self.tabs.add(self.tab_tools, text="Tools")
        self.tabs.add(self.tab_logs, text="Logs")

        # Dashboard layout (cards)
        grid = ttk.Frame(self.tab_dashboard)
        grid.pack(fill="both", expand=True)

        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        self.card_cpu = Card(grid, "CPU")
        self.card_ram = Card(grid, "RAM")
        self.card_disk = Card(grid, "Disk Summary")
        self.card_status = Card(grid, "Status")

        self.card_cpu.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.card_ram.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self.card_disk.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.card_status.grid(row=1, column=1, sticky="nsew", padx=6, pady=6)

        # CPU card
        self.cpu_label = ttk.Label(self.card_cpu.body, text="CPU Usage: --%", style="Big.TLabel")
        self.cpu_label.pack(anchor="w")
        self.cpu_bar = ttk.Progressbar(self.card_cpu.body, mode="determinate", maximum=100)
        self.cpu_bar.pack(fill="x", pady=8)
        self.cpu_temp_label = ttk.Label(self.card_cpu.body, text="CPU Temp: --", style="Small.TLabel")
        self.cpu_temp_label.pack(anchor="w")

        # RAM card
        self.ram_label = ttk.Label(self.card_ram.body, text="RAM Usage: --%", style="Big.TLabel")
        self.ram_label.pack(anchor="w")
        self.ram_bar = ttk.Progressbar(self.card_ram.body, mode="determinate", maximum=100)
        self.ram_bar.pack(fill="x", pady=8)
        self.ram_detail = ttk.Label(self.card_ram.body, text="-- / --", style="Small.TLabel")
        self.ram_detail.pack(anchor="w")

        # Disk card
        self.disk_text = tk.Text(self.card_disk.body, height=10, wrap="word")
        self.disk_text.pack(fill="both", expand=True)

        # Status card
        self.status_text = tk.Text(self.card_status.body, height=10, wrap="word")
        self.status_text.pack(fill="both", expand=True)

        # Drives tab table
        cols = ("Drive", "Mount", "FS", "Total", "Used", "Free", "Use%")
        self.drive_tree = ttk.Treeview(self.tab_drives, columns=cols, show="headings", height=16)
        for c in cols:
            self.drive_tree.heading(c, text=c)
            self.drive_tree.column(c, width=140, anchor="w")
        self.drive_tree.column("Mount", width=180)
        self.drive_tree.pack(fill="both", expand=True)

        # SMART tab
        self.smart_text = tk.Text(self.tab_smart, height=20, wrap="word")
        self.smart_text.pack(fill="both", expand=True)

        # Tools tab
        tools = ttk.Frame(self.tab_tools)
        tools.pack(fill="x")

        ttk.Label(tools, text="Cleanup (Safe temp/cache):", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0,6))
        ttk.Button(tools, text="Clean Temp/Cache", command=self.do_cleanup).grid(row=1, column=0, sticky="w")
        ttk.Button(tools, text="Export Report (JSON)", command=self.export_report).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Separator(self.tab_tools).pack(fill="x", pady=14)

        sec = ttk.Frame(self.tab_tools)
        sec.pack(fill="x")
        ttk.Label(sec, text="Windows Security (Built-in Defender):", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0,6))
        ttk.Button(sec, text="Open Windows Security", command=self.do_open_security).grid(row=1, column=0, sticky="w")
        ttk.Button(sec, text="Defender Quick Scan", command=self.do_defender_quick).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(sec, text="Defender Full Scan", command=self.do_defender_full).grid(row=1, column=2, sticky="w", padx=8)
        ttk.Button(sec, text="Check Defender Status", command=self.do_defender_status).grid(row=1, column=3, sticky="w", padx=8)

        self.tools_out = tk.Text(self.tab_tools, height=12, wrap="word")
        self.tools_out.pack(fill="both", expand=True, pady=10)

        # Logs tab
        self.log_text = tk.Text(self.tab_logs, height=20, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        # Footer
        footer = ttk.Frame(self, padding=12)
        footer.pack(fill="x")
        ttk.Button(footer, text="Refresh Now", command=self.refresh_all).pack(side="left")
        self.lbl_status = ttk.Label(footer, text="Ready")
        self.lbl_status.pack(side="right")

        self.report_cache = {}

        # Tray
        icon_path = resource_path("assets/ds.ico") if os.path.exists(resource_path("assets/ds.ico")) else None
        if icon_path:
            self.tray = TrayController(
                icon_path=icon_path,
                on_open=self.bring_to_front,
                on_quit=self.safe_quit
            )
            self.tray.run_detached()
        else:
            self.tray = None

        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        self.refresh_all()
        threading.Thread(target=self.auto_loop, daemon=True).start()

    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        s.configure("CardBody.TFrame", background="#ffffff")
        s.configure("CardTitle.TLabel", background="#ffffff", font=("Segoe UI", 12, "bold"))
        s.configure("Big.TLabel", background="#ffffff", font=("Segoe UI", 16, "bold"))
        s.configure("Small.TLabel", background="#ffffff", font=("Segoe UI", 10))

    def log(self, msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")

    def bring_to_front(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def minimize_to_tray(self):
        # minimize instead of closing
        self.withdraw()
        if self.tray:
            self.tray.notify(APP_NAME, "Running in tray. Right-click tray icon for options.")

    def safe_quit(self):
        self._stop = True
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.destroy()

    def auto_loop(self):
        while not self._stop:
            time.sleep(3)
            try:
                self.refresh_dashboard_only()
            except Exception:
                pass

    def refresh_all(self):
        self.lbl_status.config(text="Refreshing...")
        snap = get_snapshot(include_smart=True)
        self.report_cache = snap
        self.render_dashboard(snap)
        self.render_drives(snap)
        self.render_smart(snap)
        self.render_status(snap)
        self.check_alerts(snap)
        self.lbl_status.config(text="Updated")

    def refresh_dashboard_only(self):
        snap = get_snapshot(include_smart=False)
        # keep last smart, but refresh realtime
        if "smart" in self.report_cache:
            snap["smart"] = self.report_cache["smart"]
        self.report_cache.update(snap)
        self.render_dashboard(self.report_cache)
        self.render_status(self.report_cache)
        self.check_alerts(self.report_cache)

    def render_dashboard(self, snap):
        cpu = snap["cpu_usage_percent"]
        ram = snap["ram_percent"]
        self.cpu_label.config(text=f"CPU Usage: {cpu:.1f}%")
        self.cpu_bar["value"] = cpu

        t = snap.get("cpu_temp_c")
        if t is None:
            self.cpu_temp_label.config(text="CPU Temp: Not available (run LibreHardwareMonitor for accurate temp)")
        else:
            self.cpu_temp_label.config(text=f"CPU Temp: {t:.1f} °C")

        self.ram_label.config(text=f"RAM Usage: {ram:.1f}%")
        self.ram_bar["value"] = ram
        self.ram_detail.config(text=f"{human_bytes(snap['ram_used'])} / {human_bytes(snap['ram_total'])}")

        # Disk summary
        self.disk_text.delete("1.0", "end")
        lines = []
        for d in snap["drives"][:10]:
            free_pct = (d["free"] / d["total"] * 100) if d["total"] else 0
            lines.append(f"{d['mount']}  Free: {human_bytes(d['free'])} ({free_pct:.1f}%)  Used: {d['percent']:.1f}%")
        if not lines:
            lines = ["No drives detected."]
        self.disk_text.insert("1.0", "\n".join(lines))

    def render_status(self, snap):
        self.status_text.delete("1.0", "end")
        lines = []
        lines.append(f"Uptime: ~{snap['uptime_hours']} hours")
        if snap.get("disk_read_bytes_total") is not None:
            lines.append(f"Disk Read (since boot): {human_bytes(snap['disk_read_bytes_total'])}")
            lines.append(f"Disk Write(since boot): {human_bytes(snap['disk_write_bytes_total'])}")
        lines.append("")
        lines.append("Tip: For best temperature readings, run LibreHardwareMonitor with WMI enabled.")
        self.status_text.insert("1.0", "\n".join(lines))

    def render_drives(self, snap):
        for i in self.drive_tree.get_children():
            self.drive_tree.delete(i)
        for d in snap["drives"]:
            free_pct = (d["free"] / d["total"] * 100) if d["total"] else 0
            self.drive_tree.insert("", "end", values=(
                d["device"],
                d["mount"],
                d["fstype"],
                human_bytes(d["total"]),
                human_bytes(d["used"]),
                human_bytes(d["free"]) + f" ({free_pct:.1f}%)",
                f"{d['percent']:.1f}%"
            ))

    def render_smart(self, snap):
        self.smart_text.delete("1.0", "end")
        self.smart_text.insert("1.0", json.dumps(snap.get("smart", {}), indent=2, ensure_ascii=False))

    def check_alerts(self, snap):
        # prevent spam (cooldown 30s)
        now = time.time()
        if now - self.last_alert_ts < 30:
            return

        alerts = []
        if snap["cpu_usage_percent"] >= TH_CPU:
            alerts.append(f"High CPU usage: {snap['cpu_usage_percent']:.1f}%")
        if snap["ram_percent"] >= TH_RAM:
            alerts.append(f"High RAM usage: {snap['ram_percent']:.1f}%")
        t = snap.get("cpu_temp_c")
        if t is not None and t >= TH_CPU_TEMP:
            alerts.append(f"High CPU temperature: {t:.1f} °C")

        for d in snap["drives"]:
            try:
                free_pct = (d["free"] / d["total"] * 100) if d["total"] else 100
                if free_pct <= TH_DISK_FREE_PCT:
                    alerts.append(f"Low disk space: {d['mount']} free {free_pct:.1f}%")
            except Exception:
                pass

        if alerts:
            msg = " | ".join(alerts[:3])
            self.log("ALERT: " + msg)
            if self.tray:
                self.tray.notify(APP_NAME, msg)
            self.last_alert_ts = now

    def export_report(self):
        try:
            fname = f"ds_health_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(self.report_cache, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Exported", f"Saved:\n{os.path.abspath(fname)}")
            self.log(f"Exported report: {fname}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.log(f"Export error: {e}")

    def do_cleanup(self):
        self.tools_out.delete("1.0", "end")
        self.tools_out.insert("1.0", "Cleaning temp/cache...\n")
        self.update()
        try:
            res = cleanup_temp_files()
            self.tools_out.insert("end", json.dumps(res, indent=2))
            self.log(f"Cleanup done. Deleted ~{human_bytes(res['total_deleted_bytes'])}")
            if self.tray:
                self.tray.notify(APP_NAME, f"Cleanup done: ~{human_bytes(res['total_deleted_bytes'])} deleted")
        except Exception as e:
            self.tools_out.insert("end", f"\nError: {e}")
            self.log(f"Cleanup error: {e}")

    def do_open_security(self):
        ok = open_windows_security()
        if not ok:
            messagebox.showwarning("Info", "Could not open Windows Security.")
        else:
            self.log("Opened Windows Security.")

    def do_defender_quick(self):
        ok = defender_quick_scan()
        self.log("Defender Quick Scan started." if ok else "Defender Quick Scan failed.")

    def do_defender_full(self):
        ok = defender_full_scan()
        self.log("Defender Full Scan started." if ok else "Defender Full Scan failed.")

    def do_defender_status(self):
        out = defender_status()
        self.tools_out.delete("1.0", "end")
        if out:
            self.tools_out.insert("1.0", out)
            self.log("Fetched Defender status.")
        else:
            self.tools_out.insert("1.0", "Could not read Defender status (may be disabled or permissions).")
            self.log("Defender status read failed.")

if __name__ == "__main__":
    app = App()
    app.mainloop()
