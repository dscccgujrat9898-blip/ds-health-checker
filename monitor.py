import time
import platform
import psutil
import wmi
from smart import find_smartctl_path, get_smart_summary

def human_bytes(num: float) -> str:
    step = 1024.0
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if num < step:
            return f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} EB"

def get_uptime_hours() -> int:
    boot = psutil.boot_time()
    up_sec = time.time() - boot
    return int(up_sec // 3600)

def get_drives_usage():
    drives = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts.lower():
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        drives.append({
            "device": p.device,
            "mount": p.mountpoint,
            "fstype": p.fstype,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": usage.percent
        })
    return drives

def get_openhardwaremonitor_cpu_temp():
    # Works if LibreHardwareMonitor/OpenHardwareMonitor is running (WMI enabled)
    try:
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        temps = []
        for s in w.Sensor():
            if str(s.SensorType) == "Temperature" and "CPU" in str(s.Name):
                if s.Value is not None:
                    temps.append(float(s.Value))
        if temps:
            return sum(temps) / len(temps)
    except Exception:
        pass
    return None

def get_acpi_temp_fallback():
    # Often unreliable; fallback only
    try:
        w = wmi.WMI(namespace="root\\WMI")
        temps = []
        for t in w.MSAcpi_ThermalZoneTemperature():
            c = (t.CurrentTemperature / 10.0) - 273.15
            if 0 < c < 120:
                temps.append(c)
        if temps:
            return sum(temps) / len(temps)
    except Exception:
        pass
    return None

def get_cpu_temp():
    t = get_openhardwaremonitor_cpu_temp()
    if t is not None:
        return t
    return get_acpi_temp_fallback()

def get_snapshot(include_smart=True):
    cpu_percent = psutil.cpu_percent(interval=0.3)
    vm = psutil.virtual_memory()
    dio = psutil.disk_io_counters()
    uptime_h = get_uptime_hours()
    cpu_temp = get_cpu_temp()

    snap = {
        "system": platform.platform(),
        "cpu_usage_percent": cpu_percent,
        "cpu_temp_c": cpu_temp,
        "ram_total": vm.total,
        "ram_used": vm.used,
        "ram_available": vm.available,
        "ram_percent": vm.percent,
        "disk_read_bytes_total": dio.read_bytes if dio else None,
        "disk_write_bytes_total": dio.write_bytes if dio else None,
        "uptime_hours": uptime_h,
        "drives": get_drives_usage(),
    }

    if include_smart:
        smartctl = find_smartctl_path()
        if smartctl:
            snap["smart"] = get_smart_summary(smartctl_path=smartctl)
        else:
            snap["smart"] = {"error": "smartctl not found"}
    return snap

def format_overview(snap):
    lines = []
    lines.append(f"System: {snap['system']}")
    lines.append(f"CPU Usage: {snap['cpu_usage_percent']:.1f}%")
    if snap["cpu_temp_c"] is None:
        lines.append("CPU Temp: Not available (install/run LibreHardwareMonitor for accurate temp)")
    else:
        lines.append(f"CPU Temp: {snap['cpu_temp_c']:.1f} °C")
    lines.append("")
    lines.append(f"RAM Total: {human_bytes(snap['ram_total'])}")
    lines.append(f"RAM Used : {human_bytes(snap['ram_used'])} ({snap['ram_percent']:.1f}%)")
    lines.append(f"RAM Free : {human_bytes(snap['ram_available'])}")
    lines.append("")
    if snap["disk_read_bytes_total"] is not None:
        lines.append(f"Disk Read : {human_bytes(snap['disk_read_bytes_total'])} (total since boot)")
        lines.append(f"Disk Write: {human_bytes(snap['disk_write_bytes_total'])} (total since boot)")
    lines.append("")
    lines.append(f"Uptime: ~{snap['uptime_hours']} hours")
    return "\n".join(lines)
