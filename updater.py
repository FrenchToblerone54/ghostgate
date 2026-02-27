import os
import sys
import time
import hashlib
import shutil
import threading
import logging
import requests

VERSION = "0.7.3"
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
        if r.status_code != 200:
            _logger.warning(f"Failed to check for updates: HTTP {r.status_code}")
            return {"current": VERSION, "latest": None, "update_available": False}
        data = r.json()
        latest = data.get("tag_name", "").lstrip("v")
        if not latest:
            _logger.warning("No tag_name in release data")
            return {"current": VERSION, "latest": None, "update_available": False}
        if _ver_gt(latest, VERSION):
            _logger.info(f"New version available: v{latest} (current: v{VERSION})")
        else:
            _logger.debug(f"Already up to date: v{VERSION}")
        return {"current": VERSION, "latest": latest, "update_available": _ver_gt(latest, VERSION)}
    except Exception as e:
        _logger.error(f"Error checking for updates: {e}")
        return {"current": VERSION, "latest": None, "update_available": False}

def apply_update():
    if not getattr(sys, "frozen", False):
        return False
    try:
        r = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10, proxies=_proxies())
        if r.status_code != 200:
            _logger.warning(f"Failed to fetch release info: HTTP {r.status_code}")
            return False
        data = r.json()
        latest = data.get("tag_name", "").lstrip("v")
        if not latest or not _ver_gt(latest, VERSION):
            return False
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        bin_url = assets.get("ghostgate")
        sha_url = assets.get("ghostgate.sha256")
        if not bin_url or not sha_url:
            _logger.warning("Release assets not found (ghostgate / ghostgate.sha256)")
            return False
        _logger.info(f"Downloading update from {bin_url}")
        tmp = sys.executable + ".new"
        with requests.get(bin_url, stream=True, timeout=120, proxies=_proxies()) as dl:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(dl.raw, f)
        sha_r = requests.get(sha_url, timeout=10, proxies=_proxies())
        if sha_r.status_code == 200:
            sha_expected = sha_r.text.split()[0]
            sha_actual = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
            if sha_actual != sha_expected:
                os.unlink(tmp)
                _logger.error("Checksum verification failed, aborting update")
                return False
            _logger.info("Checksum verified")
        else:
            _logger.warning("Could not download checksum, skipping verification")
        os.chmod(tmp, 0o755)
        os.replace(tmp, sys.executable)
        _logger.info(f"Successfully updated to v{latest}, restarting...")
        return True
    except Exception as e:
        _logger.error(f"Error downloading update: {e}")
        return False

def restart_self():
    time.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv[1:])

def start_auto_update():
    interval = int(os.getenv("UPDATE_CHECK_INTERVAL", "300"))
    def _loop():
        _logger.info(f"Auto-update checker started (interval: {interval}s, current version: v{VERSION})")
        _logger.info("Checking for updates on startup...")
        info = check_update()
        if os.getenv("AUTO_UPDATE", "false").lower() != "true":
            return
        if info.get("update_available"):
            _logger.info(f"Updating to v{info['latest']}...")
            if apply_update():
                _logger.info("Update complete, restarting...")
                restart_self()
        while True:
            time.sleep(interval)
            if apply_update():
                _logger.info("Update complete, restarting...")
                restart_self()
    threading.Thread(target=_loop, daemon=True).start()
