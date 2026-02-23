import os
import sys
import time
import hashlib
import shutil
import threading
import logging
import requests

VERSION = "0.1.0"
GITHUB_REPO = "frenchtoblerone54/ghostgate"
_logger = logging.getLogger("updater")

def _ver_gt(a, b):
    return tuple(int(x) for x in a.lstrip("v").split(".")) > tuple(int(x) for x in b.lstrip("v").split("."))

def check_update():
    if not getattr(sys, "frozen", False):
        return {"current": VERSION, "latest": VERSION, "update_available": False}
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10)
        data = r.json()
        latest = data.get("tag_name", VERSION).lstrip("v")
        return {"current": VERSION, "latest": latest, "update_available": _ver_gt(latest, VERSION)}
    except Exception:
        return {"current": VERSION, "latest": None, "update_available": False}

def apply_update():
    if not getattr(sys, "frozen", False):
        return False
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10)
        data = r.json()
        latest = data.get("tag_name", VERSION).lstrip("v")
        if not _ver_gt(latest, VERSION):
            return False
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        bin_url = assets.get("ghostgate")
        sha_url = assets.get("ghostgate.sha256")
        if not bin_url or not sha_url:
            return False
        tmp = sys.executable + ".new"
        with requests.get(bin_url, stream=True, timeout=120) as dl:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(dl.raw, f)
        sha_expected = requests.get(sha_url, timeout=10).text.split()[0]
        sha_actual = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
        if sha_actual != sha_expected:
            os.unlink(tmp)
            _logger.error("Update checksum mismatch, aborting")
            return False
        os.chmod(tmp, 0o755)
        os.replace(tmp, sys.executable)
        _logger.info(f"Updated to v{latest}, restarting...")
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        _logger.error(f"Update failed: {e}")
        return False

def start_auto_update():
    if os.getenv("AUTO_UPDATE", "false").lower() != "true":
        return
    def _loop():
        time.sleep(60)
        while True:
            apply_update()
            time.sleep(int(os.getenv("UPDATE_CHECK_INTERVAL", "3600")))
    threading.Thread(target=_loop, daemon=True).start()
