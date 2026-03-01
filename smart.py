import os
import re
import json
import subprocess
from typing import Dict, Any, List, Optional


def resource_path(relative: str) -> str:
    # PyInstaller friendly
    base = getattr(__import__("sys"), "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)


def find_smartctl_path() -> Optional[str]:
    # Try bundled path first
    cand1 = resource_path("smartmontools/smartctl.exe")
    if os.path.exists(cand1):
        return cand1
    # Try local PATH (dev mode)
    for p in ["smartctl.exe", "smartctl"]:
        try:
            r = subprocess.run([p, "-h"], capture_output=True, text=True)
            if r.returncode in (0, 1, 2):
                return p
        except Exception:
            pass
    return None


def run(cmd: List[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    return out.strip()


def parse_smartctl_devices(output: str) -> List[str]:
    # Extract /dev/sdX like - but on Windows it's usually: "\\.\PhysicalDrive0"
    devs = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith(r"\\.\PhysicalDrive"):
            devs.append(line.split()[0])
    return list(dict.fromkeys(devs))


def extract_attr_value(text: str, attr_id: int) -> Optional[int]:
    # smartctl -A output: ID# ATTRIBUTE_NAME ... RAW_VALUE
    # Example: "  9 Power_On_Hours          0x0032   099   099   000    Old_age   Always       -       1234"
    patt = re.compile(rf"^\s*{attr_id}\s+.+\s+(\d+)\s*$", re.MULTILINE)
    m = patt.search(text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def extract_temperature(text: str) -> Optional[float]:
    # SATA often has attribute 194 or 190; NVMe has "Temperature:" line
    nvme = re.search(r"Temperature:\s*([0-9]+)\s*C", text)
    if nvme:
        return float(nvme.group(1))

    t194 = extract_attr_value(text, 194)
    if t194 is not None and 0 < t194 < 120:
        return float(t194)

    t190 = extract_attr_value(text, 190)
    if t190 is not None and 0 < t190 < 120:
        return float(t190)

    return None


def extract_health_status(text: str) -> str:
    # Look for overall-health
    m = re.search(r"SMART overall-health self-assessment test result:\s*(\w+)", text)
    if m:
        return m.group(1)
    m2 = re.search(r"SMART Health Status:\s*(\w+)", text)
    if m2:
        return m2.group(1)
    # NVMe:
    m3 = re.search(r"SMART overall-health.*:\s*(\w+)", text)
    if m3:
        return m3.group(1)
    return "UNKNOWN"


def extract_percentage_used_nvme(text: str) -> Optional[int]:
    # NVMe often includes "Percentage Used: 3%"
    m = re.search(r"Percentage Used:\s*([0-9]+)%", text)
    if m:
        return int(m.group(1))
    return None


def get_drive_info(smartctl: str, dev: str) -> Dict[str, Any]:
    info = run([smartctl, "-i", dev])
    health = run([smartctl, "-H", dev])
    attrs = run([smartctl, "-A", dev])
    nvme_full = run([smartctl, "-a", dev])  # richer for NVMe

    model = None
    serial = None

    for line in info.splitlines():
        if "Device Model:" in line or "Model Number:" in line:
            model = line.split(":", 1)[1].strip()
        if "Serial Number:" in line:
            serial = line.split(":", 1)[1].strip()

    poh = extract_attr_value(attrs, 9)
    pcy = extract_attr_value(attrs, 12)
    temp = extract_temperature(nvme_full + "\n" + attrs)

    status = extract_health_status(health + "\n" + nvme_full)

    # NVMe life
    percent_used = extract_percentage_used_nvme(nvme_full)
    # If percent_used = 3 => life remaining roughly 97%
    life_remaining = None
    if percent_used is not None:
        life_remaining = max(0, 100 - percent_used)

    return {
        "device": dev,
        "model": model,
        "serial": serial,
        "health": status,
        "power_on_hours": poh,
        "power_cycle_count": pcy,
        "temperature_c": temp,
        "nvme_percentage_used": percent_used,
        "life_remaining_percent_est": life_remaining,
        "raw": {
            "info": info[:4000],
            "health": health[:4000],
            "attrs": attrs[:4000],
        }
    }


def get_smart_summary(smartctl_path: str) -> Dict[str, Any]:
    devices_out = run([smartctl_path, "--scan-open"])
    devs = parse_smartctl_devices(devices_out)

    data = {"scan": devices_out[:4000], "drives": []}
    for d in devs:
        try:
            data["drives"].append(get_drive_info(smartctl_path, d))
        except Exception as e:
            data["drives"].append({"device": d, "error": str(e)})

    return data
