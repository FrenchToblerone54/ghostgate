import os
import sys
import time
import hashlib
import shutil
import threading
import logging
import requests

VERSION = "0.4.0"
GITHUB_REPO = "frenchtoblerone54/ghostgate"
_logger = logging.getLogger("updater")

def _ver_gt(a, b):
    return tuple(int(x) for x in a.lstrip("v").split(".")) > tuple(int(x) for x in b.lstrip("v").split("."))

def _proxies():
    p = os.getenv("UPDATE_PROXY", "").strip()
    return {"http": p, "https": p} if p else None

def check_update():
    if not getattr(sys, "frozen", False):
        return {"current": VERSION, "latest": VERSION, "update_available": False}
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10, proxies=_proxies())
        data = r.json()
        latest = data.get("tag_name", VERSION).lstrip("v")
        return {"current": VERSION, "latest": latest, "update_available": _ver_gt(latest, VERSION)}
    except Exception:
        return {"current": VERSION, "latest": None, "update_available": False}

def apply_update():
    if not getattr(sys, "frozen", False):
        return False
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10, proxies=_proxies())
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
        with requests.get(bin_url, stream=True, timeout=120, proxies=_proxies()) as dl:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(dl.raw, f)
        sha_expected = requests.get(sha_url, timeout=10, proxies=_proxies()).text.split()[0]
        sha_actual = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
        if sha_actual != sha_expected:
            os.unlink(tmp)
            _logger.error("Update checksum mismatch, aborting")
            return False
        os.chmod(tmp, 0o755)
        os.replace(tmp, sys.executable)
        _logger.info(f"Updated to v{latest}")
        return True
    except Exception as e:
        _logger.error(f"Update failed: {e}")
        return False

def restart_self():
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv[1:])

def start_auto_update():
    def _loop():
        info = check_update()
        if info.get("update_available"):
            _logger.info(f"Update available: v{info['latest']} (current: v{info['current']})")
        if os.getenv("AUTO_UPDATE", "false").lower() != "true":
            return
        if info.get("update_available"):
            if apply_update():
                restart_self()
        while True:
            time.sleep(int(os.getenv("UPDATE_CHECK_INTERVAL", "300")))
            if apply_update():
                restart_self()
    threading.Thread(target=_loop, daemon=True).start()
