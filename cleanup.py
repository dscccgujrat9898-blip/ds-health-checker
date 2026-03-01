import os
import shutil
import subprocess
from pathlib import Path

SAFE_TARGETS = [
    Path(os.environ.get("TEMP", "")),
    Path(os.environ.get("TMP", "")),
    Path(r"C:\Windows\Temp"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Temp",
]

def _safe_delete_path(p: Path) -> int:
    deleted = 0
    if not p.exists() or not p.is_dir():
        return 0
    for item in p.glob("*"):
        try:
            if item.is_file() or item.is_symlink():
                size = item.stat().st_size
                item.unlink(missing_ok=True)
                deleted += size
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass
    return deleted

def cleanup_temp_files() -> dict:
    total_deleted = 0
    details = []
    for t in SAFE_TARGETS:
        if str(t).strip() == "" or str(t) in ["\\", "/"]:
            continue
        before = _dir_size(t)
        deleted_bytes = _safe_delete_path(t)
        after = _dir_size(t)
        total_deleted += deleted_bytes
        details.append({"path": str(t), "before": before, "after": after, "deleted": deleted_bytes})
    return {"total_deleted_bytes": total_deleted, "details": details}

def _dir_size(p: Path) -> int:
    s = 0
    try:
        if not p.exists():
            return 0
        for f in p.rglob("*"):
            try:
                if f.is_file():
                    s += f.stat().st_size
            except Exception:
                pass
    except Exception:
        pass
    return s

def open_windows_security():
    # Opens Windows Security UI
    try:
        subprocess.Popen(["cmd", "/c", "start", "windowsdefender:"], shell=False)
        return True
    except Exception:
        return False

def defender_quick_scan():
    # Uses built-in Defender cmdlets (works if Defender present)
    ps = 'PowerShell -NoProfile -ExecutionPolicy Bypass -Command "Start-MpScan -ScanType QuickScan"'
    try:
        subprocess.Popen(ps, shell=True)
        return True
    except Exception:
        return False

def defender_full_scan():
    ps = 'PowerShell -NoProfile -ExecutionPolicy Bypass -Command "Start-MpScan -ScanType FullScan"'
    try:
        subprocess.Popen(ps, shell=True)
        return True
    except Exception:
        return False

def defender_status():
    # Reads Defender status (best effort)
    ps = 'PowerShell -NoProfile -ExecutionPolicy Bypass -Command "Get-MpComputerStatus | Select-Object AMServiceEnabled,AntispywareEnabled,AntivirusEnabled,RealTimeProtectionEnabled,FullScanAge,QuickScanAge | ConvertTo-Json"'
    try:
        out = subprocess.check_output(ps, shell=True, text=True, encoding="utf-8", errors="ignore").strip()
        return out
    except Exception:
        return None
