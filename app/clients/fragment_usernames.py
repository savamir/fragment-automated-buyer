import re
import json
import base64
import urllib.parse
from typing import List, Dict, Optional

import httpx
from bs4 import BeautifulSoup
from aiocache import cached, SimpleMemoryCache

SALE_URL = "https://fragment.com/?sort=price_asc&filter=sale"
USERNAME_URL = "https://fragment.com/username/{username_id}"
API_URL = "https://fragment.com/api"

_price_num_re = re.compile(r"(\d+)")


class FragmentUsernamesClient:
    def __init__(self, cookies: Optional[Dict[str, str]] = None):
        self._client = httpx.AsyncClient(
            timeout=20, headers={"User-Agent": "Mozilla/5.0"}
        )
        self._cookies = cookies or {}

    async def close(self):
        await self._client.aclose()

    @cached(ttl=5, cache=SimpleMemoryCache)
    async def fetch_sale_html(self) -> str:
        r = await self._client.get(SALE_URL, cookies=self._cookies)
        r.raise_for_status()
        return r.text

    def _parse_price(self, cell_text: str) -> Optional[int]:
        cleaned = cell_text.replace(",", "").replace(" ", "")
        m = _price_num_re.search(cleaned)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    async def list_sales(self) -> List[Dict]:
        html = await self.fetch_sale_html()
        soup = BeautifulSoup(html, "html.parser")
        
        table = soup.select_one("table")
        if not table:
            return []
            
        rows = table.select("tr")
        sales: List[Dict] = []
        
        for row in rows:
            if row.select_one("th"):
                continue
                
            username_link = row.select_one("td a[href*='/username/']")
            if not username_link:
                continue
                
            href = username_link.get("href") or ""
            username_id = href.split("/")[-1]
            
            username_text = username_link.get_text(strip=True)
            if username_text.startswith("@"):
                username_text = username_text[1:]
            
            price_cell = None
            for cell in row.select("td"):
                cell_text = cell.get_text(strip=True)
                if "TON" in cell_text or self._parse_price(cell_text):
                    price_cell = cell
                    break
            
            if not price_cell:
                continue
                
            price_str = price_cell.get_text(strip=True)
            price_int = self._parse_price(price_str)
            
            status_cell = row.select_one("td")
            status = status_cell.get_text(strip=True) if status_cell else "For sale"
            
            sales.append({
                "id": username_id,
                "url": USERNAME_URL.format(username_id=username_id),
                "username": username_text,
                "price_ton": price_str,
                "price_ton_int": price_int,
                "status": status,
            })
        
        return sales

    async def get_username_info(self, username_id: str) -> Dict:
        url = USERNAME_URL.format(username_id=username_id)
        r = await self._client.get(url, cookies=self._cookies)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        title = soup.select_one("h1, .tm-section-title")
        buy_btn = soup.select_one(".btn.btn-primary, button.btn-primary")
        
        api_hash = None
        for s in soup.find_all('script'):
            txt = (s.string or s.text or '').strip()
            if not txt:
                continue
            m = re.search(r"api\?hash=([a-f0-9]{16,})", txt)
            if m:
                api_hash = m.group(1)
                break
                
        return {
            "id": username_id,
            "title": title.get_text(strip=True) if title else None,
            "can_buy": bool(buy_btn),
            "url": url,
            "api_hash": api_hash,
        }

    async def prepare_purchase(self, username_id: str) -> Dict:
        url = USERNAME_URL.format(username_id=username_id)
        r = await self._client.get(url, cookies=self._cookies)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        buy_btn = soup.select_one(
            "button[data-address][data-amount][data-payload], a[data-address][data-amount][data-payload]"
        )
        if buy_btn:
            address = buy_btn.get("data-address")
            amount_raw = buy_btn.get("data-amount") or "0"
            payload_b64 = buy_btn.get("data-payload") or ""
            try:
                amount_nano = int(str(amount_raw).strip())
            except Exception:
                amount_nano = None
            if address and amount_nano:
                return {
                    "address": address,
                    "amount_nano": amount_nano,
                    "payload_b64": payload_b64,
                    "source": "data-attrs",
                }

        for a in soup.select('a[href], button[href]'):
            href = a.get('href') or ''
            if not href:
                continue
            if href.startswith('ton://') or 'tonkeeper' in href or 'tonhub' in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                address = None
                amount_nano = None
                payload_b64 = ''
                if parsed.scheme == 'ton' and parsed.netloc == 'transfer':
                    address = parsed.path.lstrip('/')
                    if 'amount' in qs:
                        try:
                            amount_nano = int(qs['amount'][0])
                        except Exception:
                            amount_nano = None
                    if 'bin' in qs:
                        payload_b64 = qs['bin'][0]
                    if address and amount_nano:
                        return {
                            'address': address,
                            'amount_nano': amount_nano,
                            'payload_b64': payload_b64,
                            'source': 'ton-transfer-url',
                        }
                if 'connect' in href or 'tonkeeper' in href:
                    try:
                        decoded = urllib.parse.unquote(href)
                        m = re.search(r"\{\s*\"messages\"\s*:\s*\[(.*?)\]", decoded)
                        if m:
                            inner = decoded[decoded.find('{'):]
                            jstart = inner
                            for end in range(len(jstart), max(len(jstart)-1, len(jstart)-1), -1):
                                pass
                            data = json.loads(jstart)
                            msg = data.get('messages', [{}])[0]
                            address = msg.get('address')
                            amount_nano = int(msg.get('amount')) if msg.get('amount') else None
                            payload_b64 = msg.get('payload') or ''
                            if address and amount_nano:
                                return {
                                    'address': address,
                                    'amount_nano': amount_nano,
                                    'payload_b64': payload_b64,
                                    'source': 'tonconnect-url',
                                }
                    except Exception:
                        pass

        for script in soup.find_all("script"):
            txt = script.string or script.text or ""
            if not txt:
                continue
            if "data-address" in txt or "payload" in txt or "amount" in txt:
                addr_m = re.search(r"([A-Z0-9_-]{48,66})", txt)
                amt_m = re.search(r"\b(\d{6,})\b", txt)
                payload_m = re.search(r"([A-Za-z0-9+/=]{16,})", txt)
                address = addr_m.group(1) if addr_m else None
                amount_nano = int(amt_m.group(1)) if amt_m else None
                payload_b64 = payload_m.group(1) if payload_m else ""
                if address and amount_nano:
                    return {
                        "address": address,
                        "amount_nano": amount_nano,
                        "payload_b64": payload_b64,
                        "source": "inline-script",
                    }

        raise RuntimeError("Failed to extract purchase parameters; login/session likely required")

    async def api_get_bid_link(self, username_id: str, bid_ton: int, account: dict, device: dict, api_hash: Optional[str]) -> Dict:
        if not api_hash:
            info = await self.get_username_info(username_id)
            api_hash = info.get("api_hash")
        params = {"hash": api_hash} if api_hash else {}
        data = {
            "method": "getBidLink",
            "transaction": 1,
            "type": 1,
            "username": username_id,
            "bid": bid_ton,
            "account": json.dumps(account),
            "device": json.dumps(device),
        }
        r = await self._client.post(API_URL, params=params, data=data, cookies=self._cookies)
        r.raise_for_status()
        js = r.json()
        tx = js.get("transaction", {})
        msgs = tx.get("messages", [])
        if not msgs:
            raise RuntimeError("No messages in getBidLink response")
        msg = msgs[0]
        address = msg.get("address")
        amount = int(msg.get("amount")) if msg.get("amount") else None
        payload = msg.get("payload") or ""
        if not address or not amount:
            raise RuntimeError("Incomplete message in getBidLink response")
        return {"address": address, "amount_nano": amount, "payload_b64": payload}
