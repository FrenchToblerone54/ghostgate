import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class XUIClient:
    def __init__(self, address, username, password, proxy_url=None):
        self.base = address.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False
        if proxy_url:
            self.session.proxies = {"http": proxy_url, "https": proxy_url}
        self._login()

    def _login(self):
        self.session.post(f"{self.base}/login", json={"username": self.username, "password": self.password}, timeout=10)

    def get_inbound(self, inbound_id):
        r = self.session.get(f"{self.base}/panel/api/inbounds/get/{inbound_id}", timeout=10)
        data = r.json()
        return data.get("obj") if data.get("success") else None

    def add_client(self, inbound_id, client_obj):
        settings = json.dumps({"clients": [client_obj]})
        r = self.session.post(f"{self.base}/panel/api/inbounds/addClient",
            json={"id": inbound_id, "settings": settings}, timeout=10)
        return r.json().get("success", False)

    def update_client(self, inbound_id, client_uuid, client_obj):
        settings = json.dumps({"clients": [client_obj]})
        r = self.session.post(f"{self.base}/panel/api/inbounds/updateClient/{client_uuid}",
            json={"id": inbound_id, "settings": settings}, timeout=10)
        return r.json().get("success", False)

    def delete_client(self, inbound_id, client_uuid):
        r = self.session.post(f"{self.base}/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}", timeout=10)
        return r.json().get("success", False)

    def get_client_traffic(self, email):
        r = self.session.get(f"{self.base}/panel/api/inbounds/getClientTraffics/{email}", timeout=10)
        data = r.json()
        return data.get("obj") if data.get("success") else None

    def get_client_by_email(self, inbound_id, email):
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return None
        clients = json.loads(inbound.get("settings", "{}")).get("clients", [])
        return next((c for c in clients if c.get("email") == email), None)

    def set_client_enabled(self, inbound_id, client_uuid, email, enabled):
        client = self.get_client_by_email(inbound_id, email)
        if not client:
            return False
        client["enable"] = enabled
        return self.update_client(inbound_id, client_uuid, client)

    def make_client(self, email, client_uuid, expire_ms=0, ip_limit=0, sub_id="", comment=""):
        return {
            "id": client_uuid,
            "flow": "",
            "email": email,
            "limitIp": ip_limit,
            "totalGB": 0,
            "expiryTime": expire_ms,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
            "comment": comment or ""
        }

    def test_connection(self):
        try:
            self._login()
            return True
        except Exception:
            return False
