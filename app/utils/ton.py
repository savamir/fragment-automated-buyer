import base64
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pytoniq import Address, Cell, LiteClient, WalletV4R2

load_dotenv()

logger = logging.getLogger(__name__)

LITE_SERVER = os.getenv("TON_LITE_SERVER", "mainnet_config").strip("\"'")
SEED_PHRASE = os.getenv("SEED_PHRASE", "").strip("\"'")


class TONError(Exception):
    pass


class TON:
    def __init__(self):
        self._client: Optional[LiteClient] = None
        self._wallet: Optional[WalletV4R2] = None

    async def _ensure(self) -> None:
        if self._client is None:
            try:
                self._client = LiteClient.from_mainnet_config(
                    ls_i=5, trust_level=2, timeout=20
                )
                await self._client.connect()
                logger.info("TON LiteClient connected")
            except Exception as e:
                logger.error(f"Failed to connect to TON LiteClient: {e}")
                raise TONError(f"Failed to connect to TON network: {e}")

        if self._wallet is None:
            if not SEED_PHRASE:
                raise TONError("SEED_PHRASE not set")
            try:
                self._wallet = await WalletV4R2.from_mnemonic(
                    provider=self._client,
                    mnemonics=SEED_PHRASE.split(),
                    version="V4R2",
                    wc=0,
                )
                logger.info("TON wallet initialized")
            except Exception as e:
                logger.error(f"Failed to initialize wallet: {e}")
                raise TONError(f"Failed to initialize wallet: {e}")

    async def transfer(
        self, to_bounceable: str, amount_nano: int, payload_b64: str = ""
    ) -> Dict[str, Any]:
        try:
            await self._ensure()
            to_addr = Address(to_bounceable)

            payload_bytes = base64.b64decode(payload_b64) if payload_b64 else b""
            body = None
            if payload_bytes:
                body = Cell.from_boc(payload_bytes)[0]

            wallet = self._wallet

            try:
                bal = await self.get_balance_nano()
                if bal < amount_nano:
                    logger.warning(
                        f"Insufficient balance: need {amount_nano}, have {bal}"
                    )
                    return {
                        "ok": False,
                        "error": "insufficient_balance",
                        "amount_nano": amount_nano,
                        "balance_nano": bal,
                        "to": to_bounceable,
                    }
            except Exception as e:
                logger.error(f"Balance check failed: {e}")
                return {
                    "ok": False,
                    "error": "balance_check_failed",
                    "amount_nano": amount_nano,
                    "to": to_bounceable,
                    "details": str(e),
                }

            try:
                await self._client.get_account_state(wallet.address)
            except Exception:
                pass

            msg = wallet.create_wallet_internal_message(
                destination=to_addr,
                value=amount_nano,
                body=body,
                state_init=None,
            )

            last_err = None
            for attempt in range(3):
                try:
                    logger.info(f"Attempting transfer (attempt {attempt + 1}/3)")
                    res = await wallet.raw_transfer(
                        msgs=[msg], seqno_from_get_meth=True
                    )

                    if res and str(res) != "None":
                        logger.info(f"Transfer successful: {res}")
                        return {
                            "ok": True,
                            "amount_nano": amount_nano,
                            "to": to_bounceable,
                            "result": str(res),
                        }
                    else:
                        logger.warning(f"Transfer failed: {res}")
                        return {
                            "ok": False,
                            "error": "transfer_failed",
                            "amount_nano": amount_nano,
                            "to": to_bounceable,
                            "result": str(res),
                        }

                except Exception as e:
                    last_err = e
                    logger.warning(f"Transfer attempt {attempt + 1} failed: {e}")
                    try:
                        await self._client.get_account_state(wallet.address)
                    except Exception:
                        pass
            else:
                try:
                    logger.info("Attempting external transfer as fallback")
                    ext = await wallet.transfer(
                        destination=to_addr,
                        amount=amount_nano,
                        body=body,
                    )
                    await self._client.send_external_message(ext)
                    logger.info("External transfer successful")
                    return {
                        "ok": True,
                        "amount_nano": amount_nano,
                        "to": to_bounceable,
                        "result": "external_message_sent",
                    }
                except Exception as e:
                    logger.error(f"External transfer failed: {e}")
                    return {
                        "ok": False,
                        "error": "external_transfer_failed",
                        "amount_nano": amount_nano,
                        "to": to_bounceable,
                        "details": str(e),
                    }

        except Exception as e:
            logger.error(f"Transfer operation failed: {e}")
            return {
                "ok": False,
                "error": "all_transfer_attempts_failed",
                "amount_nano": amount_nano,
                "to": to_bounceable,
                "details": str(e),
            }

    async def get_address(self) -> str:
        try:
            await self._ensure()
            return self._wallet.address.to_str(
                is_user_friendly=True, is_bounceable=False
            )
        except Exception as e:
            logger.error(f"Failed to get address: {e}")
            raise TONError(f"Failed to get address: {e}")

    async def get_balance_nano(self) -> int:
        try:
            await self._ensure()
            state = await self._client.get_account_state(self._wallet.address)

            balance = None

            if isinstance(state, dict):
                balance = state.get("balance")

            if balance is None:
                balance = getattr(state, "balance", None)

            if balance is None and hasattr(state, "balance"):
                balance = state.balance

            if balance is None:
                try:
                    balance = state.balance
                except:
                    pass

            if balance is not None:
                return int(balance)
            else:
                logger.warning(f"Could not extract balance from state: {type(state)}")
                return 0

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0

    async def get_fragment_account_payload(self, chain: str = "-239") -> Dict[str, str]:
        try:
            await self._ensure()
            wallet = self._wallet

            address = wallet.address.to_str(is_user_friendly=False, is_bounceable=False)
            state_init_boc_b64 = base64.b64encode(
                wallet.state_init.serialize().to_boc()
            ).decode()
            public_key_hex = wallet.public_key.hex()

            return {
                "address": address,
                "chain": chain,
                "walletStateInit": state_init_boc_b64,
                "publicKey": public_key_hex,
            }
        except Exception as e:
            logger.error(f"Failed to get fragment account payload: {e}")
            raise TONError(f"Failed to get fragment account payload: {e}")

    @staticmethod
    def default_device_payload() -> Dict[str, Any]:
        return {
            "platform": "windows",
            "appName": "tonkeeper",
            "appVersion": "4.2.4",
            "maxProtocolVersion": 2,
            "features": [
                "SendTransaction",
                {
                    "name": "SendTransaction",
                    "maxMessages": 255,
                    "extraCurrencySupported": True,
                },
                {"name": "SignData", "types": ["text", "binary", "cell"]},
            ],
        }
