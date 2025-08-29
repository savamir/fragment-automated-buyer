import json
import re
from typing import Dict, List, Optional

import httpx
from aiocache import SimpleMemoryCache, cached
from bs4 import BeautifulSoup

SALE_URL = "https://fragment.com/numbers?filter=sale"
NUMBER_URL = "https://fragment.com/number/{number_id}"
API_URL = "https://fragment.com/api"

_price_num_re = re.compile(r"(\d+)")


class FragmentNumbersClient:
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
        rows = soup.select("table tr.tm-row-selectable")
        sales: List[Dict] = []
        for row in rows:
            link = row.select_one("td a.table-cell")
            price_cell = row.select_one(".icon-before.icon-ton")
            status_cell = row.select_one(
                ".tm-status-avail, .tm-status-sold, .tm-status-bid"
            )
            if not link or not price_cell:
                continue

            href = link.get("href") or ""
            number_id = href.split("/")[-1]
            number_text = row.select_one(".table-cell-value")
            number_str = number_text.get_text(strip=True) if number_text else None
            price_str = price_cell.get_text(strip=True)
            price_int = self._parse_price(price_str)
            status = status_cell.get_text(strip=True) if status_cell else None

            sales.append(
                {
                    "id": number_id,
                    "url": NUMBER_URL.format(number_id=number_id),
                    "number": number_str,
                    "price_ton": price_str,
                    "price_ton_int": price_int,
                    "status": status,
                }
            )
        return sales

    async def get_number_info(self, number_id: str) -> Dict:
        url = NUMBER_URL.format(number_id=number_id)
        r = await self._client.get(url, cookies=self._cookies)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.select_one(".tm-section-title")
        buy_btn = soup.select_one(".btn.btn-primary, button.btn-primary")

        api_hash = None
        for s in soup.find_all("script"):
            txt = (s.string or s.text or "").strip()
            if not txt:
                continue
            m = re.search(r"api\?hash=([a-f0-9]{16,})", txt)
            if m:
                api_hash = m.group(1)
                break

        return {
            "id": number_id,
            "title": title.get_text(strip=True) if title else None,
            "can_buy": bool(buy_btn),
            "url": url,
            "api_hash": api_hash,
        }

    async def api_get_bid_link(
        self,
        number_id: str,
        bid_ton: int,
        account: dict,
        device: dict,
        api_hash: Optional[str],
    ) -> Dict:
        if not api_hash:
            info = await self.get_number_info(number_id)
            api_hash = info.get("api_hash")

        params = {"hash": api_hash} if api_hash else {}
        data = {
            "method": "getBidLink",
            "transaction": 1,
            "type": 3,
            "username": number_id,
            "bid": bid_ton,
            "account": json.dumps(account),
            "device": json.dumps(device),
        }

        r = await self._client.post(
            API_URL, params=params, data=data, cookies=self._cookies
        )
        r.raise_for_status()

        js: dict = r.json()
        tx = js.get("transaction", {})
        msgs = tx.get("messages", [])
        if not msgs:
            raise RuntimeError("No messages in getBidLink response")

        msg: dict = msgs[0]
        address = msg.get("address")
        amount = int(msg.get("amount")) if msg.get("amount") else None
        payload = msg.get("payload") or ""
        if not address or not amount:
            raise RuntimeError("Incomplete message in getBidLink response")

        return {"address": address, "amount_nano": amount, "payload_b64": payload}
