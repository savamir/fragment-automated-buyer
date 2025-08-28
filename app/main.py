import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.clients.fragment import FragmentNumbersClient
from app.clients.fragment_usernames import FragmentUsernamesClient
from app.services.monitor import NumbersMonitor
from app.utils.ton import TON

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fragment Buyer API", version="1.0.0")


class AppState:
    def __init__(self):
        self.fragment_client: Optional[FragmentNumbersClient] = None
        self.fragment_usernames_client: Optional[FragmentUsernamesClient] = None
        self.monitor: Optional[NumbersMonitor] = None
        self.ton: Optional[TON] = None
        self.monitor_should_stop: bool = False
        self.buy_in_progress: bool = False


app_state = AppState()


class FragmentError(Exception):
    pass


class InsufficientBalanceError(Exception):
    pass


class PurchaseError(Exception):
    pass


def get_fragment_client() -> FragmentNumbersClient:
    if app_state.fragment_client is None:
        cookies_raw = os.getenv("FRAGMENT_COOKIES", "")
        cookies = {}
        if cookies_raw:
            for pair in cookies_raw.split(";"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookies[k.strip()] = v.strip()
        app_state.fragment_client = FragmentNumbersClient(cookies=cookies)
    return app_state.fragment_client


def get_fragment_usernames_client() -> FragmentUsernamesClient:
    if app_state.fragment_usernames_client is None:
        cookies_raw = os.getenv("FRAGMENT_COOKIES", "")
        cookies = {}
        if cookies_raw:
            for pair in cookies_raw.split(";"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookies[k.strip()] = v.strip()
        app_state.fragment_usernames_client = FragmentUsernamesClient(cookies=cookies)
    return app_state.fragment_usernames_client


async def get_ton_instance() -> TON:
    if app_state.ton is None:
        app_state.ton = TON()
    return app_state.ton


@asynccontextmanager
async def purchase_lock():
    if app_state.buy_in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Purchase already in progress"
        )
    app_state.buy_in_progress = True
    try:
        yield
    finally:
        app_state.buy_in_progress = False


class MonitorStartRequest(BaseModel):
    max_price_ton: int = Field(..., gt=0, description="Maximum price in TON")
    interval_sec: int = Field(
        default=1, ge=1, le=60, description="Monitoring interval in seconds"
    )


class UsernameMonitorStartRequest(BaseModel):
    max_price_ton: int = Field(..., gt=0, description="Maximum price in TON")
    interval_sec: int = Field(
        default=1, ge=1, le=60, description="Monitoring interval in seconds"
    )


class BuyRequest(BaseModel):
    number_id: str = Field(..., description="Number ID to purchase")
    bid_ton: Optional[int] = Field(None, gt=0, description="Bid amount in TON")


class BuyUsernameRequest(BaseModel):
    username_id: str = Field(..., description="Username ID to purchase")
    bid_ton: Optional[int] = Field(None, gt=0, description="Bid amount in TON")


class BuyResponse(BaseModel):
    status: str
    tx: dict


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "fragment-buyer"}


@app.get("/numbers")
async def list_numbers() -> list:
    try:
        client = get_fragment_client()
        return await client.list_sales()
    except Exception as e:
        logger.error(f"Failed to list numbers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "list_numbers_failed",
                "message": "Failed to retrieve numbers list",
                "details": str(e),
            },
        )


@app.get("/usernames")
async def list_usernames() -> list:
    try:
        client = get_fragment_usernames_client()
        return await client.list_sales()
    except Exception as e:
        logger.error(f"Failed to list usernames: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "list_usernames_failed",
                "message": "Failed to retrieve usernames list",
                "details": str(e),
            },
        )


async def validate_affordability(
    max_price: int, balance_ton: float, item_type: str = "items"
) -> None:
    if balance_ton < max_price:
        raise InsufficientBalanceError(
            f"Insufficient balance. Need at least {max_price} TON for the cheapest {item_type}, but have {balance_ton:.2f} TON"
        )


async def validate_balance_for_monitoring(
    max_price_ton: int, balance_ton: float, item_type: str = "items"
) -> None:
    if balance_ton < max_price_ton:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_balance_for_monitoring",
                "message": f"Insufficient balance to monitor {item_type} up to {max_price_ton} TON",
                "required_balance": max_price_ton,
                "current_balance": balance_ton,
                "shortage": max_price_ton - balance_ton,
                "item_type": item_type,
            },
        )


async def pre_check_affordability(
    max_price_ton: int, item_type: str = "items"
) -> float:
    try:
        ton = await get_ton_instance()
        balance_nano = await ton.get_balance_nano()
        balance_ton = balance_nano / 1_000_000_000

        logger.info(
            f"Pre-checking {item_type} affordability for max price: {max_price_ton} TON"
        )
        logger.info(f"Current wallet balance: {balance_ton:.2f} TON")

        await validate_balance_for_monitoring(max_price_ton, balance_ton, item_type)

        client = (
            get_fragment_client()
            if item_type == "items"
            else get_fragment_usernames_client()
        )
        listings = await client.list_sales()

        affordable_items = [
            item
            for item in listings
            if item.get("price_ton_int") is not None
            and item.get("price_ton_int") <= max_price_ton
        ]

        if not affordable_items:
            logger.info(
                f"No {item_type} found within price range (max: {max_price_ton} TON), but will start monitoring anyway"
            )
            return balance_ton

        affordable_items.sort(key=lambda x: x.get("price_ton_int", float("inf")))
        cheapest_price = affordable_items[0].get("price_ton_int")

        logger.info(
            f"Found {len(affordable_items)} {item_type} within price range. Cheapest: {cheapest_price} TON"
        )

        await validate_affordability(cheapest_price, balance_ton, item_type)

        logger.info(
            f"✅ {item_type.capitalize()} pre-check passed: Can afford {item_type} up to {max_price_ton} TON"
        )
        return balance_ton

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pre-check {item_type} affordability: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "pre_check_failed",
                "message": f"Failed to pre-check {item_type} affordability",
                "details": str(e),
                "item_type": item_type,
            },
        )


@app.post("/monitor-numbers/start")
async def start_monitor(body: MonitorStartRequest) -> Dict[str, Any]:
    try:
        balance_ton = await pre_check_affordability(body.max_price_ton, "items")

        async def process_listings():
            try:
                if app_state.monitor_should_stop:
                    logger.info("Monitor stopped due to insufficient funds")
                    return

                client = get_fragment_client()
                ton = await get_ton_instance()

                listings = await client.list_sales()
                affordable_items = [
                    item
                    for item in listings
                    if item.get("price_ton_int") is not None
                    and item.get("price_ton_int") <= body.max_price_ton
                ]

                if not affordable_items:
                    logger.info("No affordable items found")
                    return

                affordable_items.sort(
                    key=lambda x: x.get("price_ton_int", float("inf"))
                )
                cheapest_item = affordable_items[0]
                price = cheapest_item.get("price_ton_int")

                try:
                    current_balance = await ton.get_balance_nano()
                    current_balance_ton = current_balance / 1_000_000_000
                    logger.info(f"💰 Current balance: {current_balance_ton:.2f} TON")

                    if current_balance_ton < price:
                        logger.info(
                            f"💰 Insufficient balance for {price} TON item, stopping monitor"
                        )
                        app_state.monitor_should_stop = True
                        return

                except Exception as e:
                    logger.warning(f"Could not check current balance: {e}")

                logger.info(
                    f"🎯 FOUND NUMBER TARGET: {cheapest_item.get('id')} for {price} TON"
                )

                async with purchase_lock():
                    try:
                        buy_request = BuyRequest(
                            number_id=cheapest_item.get("id"), bid_ton=price
                        )

                        result = await asyncio.wait_for(
                            buy_number(buy_request), timeout=60.0
                        )
                        logger.info(f"✅ NUMBER PURCHASE SUCCESS: {result}")

                        try:
                            remaining_balance = await ton.get_balance_nano()
                            remaining_ton = remaining_balance / 1_000_000_000
                            logger.info(
                                f"💰 Remaining balance: {remaining_ton:.2f} TON"
                            )

                            if remaining_ton < 1.0:
                                logger.info("💰 Low balance, stopping number monitor")
                                app_state.monitor_should_stop = True
                            else:
                                logger.info(
                                    "🔄 Sufficient balance remaining, will continue monitoring numbers..."
                                )

                        except Exception as e:
                            logger.warning(f"Could not check remaining balance: {e}")
                            logger.info("🔄 Will continue monitoring numbers anyway...")

                    except asyncio.TimeoutError:
                        logger.error(
                            "❌ NUMBER PURCHASE TIMEOUT: Function took too long"
                        )
                    except HTTPException as e:
                        logger.error(
                            f"❌ NUMBER PURCHASE FAILED (HTTP {e.status_code}): {e.detail}"
                        )
                        if e.status_code == 402:
                            logger.info(
                                "💰 Stopping number monitor due to insufficient balance"
                            )
                            app_state.monitor_should_stop = True
                        else:
                            logger.info(
                                "🔄 Number purchase failed, will try again in next cycle"
                            )
                    except Exception as e:
                        logger.error(f"❌ NUMBER PURCHASE ERROR: {e}")
                        logger.info(
                            "🔄 Number purchase error, will try again in next cycle"
                        )

            except Exception as e:
                logger.error(f"process_listings error: {e}")

        app_state.monitor = NumbersMonitor(
            get_fragment_client(),
            on_new_listing=lambda item: asyncio.create_task(process_listings()),
            interval_sec=body.interval_sec,
        )
        await app_state.monitor.start()

        return {
            "status": "started",
            "type": "numbers",
            "interval_sec": body.interval_sec,
            "max_price_ton": body.max_price_ton,
            "balance_ton": balance_ton,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "monitor_start_failed",
                "message": "Failed to start numbers monitor",
                "details": str(e),
                "type": "numbers",
            },
        )


@app.post("/monitor-numbers/stop")
async def stop_monitor() -> Dict[str, str]:
    try:
        if app_state.monitor is not None:
            await app_state.monitor.stop()
            app_state.monitor = None
        app_state.monitor_should_stop = False
        return {"status": "stopped", "type": "numbers"}
    except Exception as e:
        logger.error(f"Failed to stop monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "monitor_stop_failed",
                "message": "Failed to stop numbers monitor",
                "details": str(e),
                "type": "numbers",
            },
        )


@app.post("/monitor-usernames/start")
async def start_username_monitor(body: UsernameMonitorStartRequest) -> Dict[str, Any]:
    try:
        balance_ton = await pre_check_affordability(body.max_price_ton, "usernames")

        async def process_username_listings():
            try:
                if app_state.monitor_should_stop:
                    logger.info("Username monitor stopped due to insufficient funds")
                    return

                client = get_fragment_usernames_client()
                ton = await get_ton_instance()

                listings = await client.list_sales()
                affordable_items = [
                    item
                    for item in listings
                    if item.get("price_ton_int") is not None
                    and item.get("price_ton_int") <= body.max_price_ton
                ]

                if not affordable_items:
                    logger.info("No affordable usernames found")
                    return

                affordable_items.sort(
                    key=lambda x: x.get("price_ton_int", float("inf"))
                )
                cheapest_item = affordable_items[0]
                price = cheapest_item.get("price_ton_int")

                try:
                    current_balance = await ton.get_balance_nano()
                    current_balance_ton = current_balance / 1_000_000_000
                    logger.info(f"💰 Current balance: {current_balance_ton:.2f} TON")

                    if current_balance_ton < price:
                        logger.info(
                            f"💰 Insufficient balance for {price} TON username, stopping monitor"
                        )
                        app_state.monitor_should_stop = True
                        return

                except Exception as e:
                    logger.warning(f"Could not check current balance: {e}")

                logger.info(
                    f"🎯 FOUND USERNAME TARGET: {cheapest_item.get('username')} ({cheapest_item.get('id')}) for {price} TON"
                )

                async with purchase_lock():
                    try:
                        buy_request = BuyUsernameRequest(
                            username_id=cheapest_item.get("id"), bid_ton=price
                        )

                        result = await asyncio.wait_for(
                            buy_username(buy_request), timeout=60.0
                        )
                        logger.info(f"✅ USERNAME PURCHASE SUCCESS: {result}")

                        try:
                            remaining_balance = await ton.get_balance_nano()
                            remaining_ton = remaining_balance / 1_000_000_000
                            logger.info(
                                f"💰 Remaining balance: {remaining_ton:.2f} TON"
                            )

                            if remaining_ton < 1.0:
                                logger.info("💰 Low balance, stopping username monitor")
                                app_state.monitor_should_stop = True
                            else:
                                logger.info(
                                    "🔄 Sufficient balance remaining, will continue monitoring usernames..."
                                )

                        except Exception as e:
                            logger.warning(f"Could not check remaining balance: {e}")
                            logger.info(
                                "🔄 Will continue monitoring usernames anyway..."
                            )

                    except asyncio.TimeoutError:
                        logger.error(
                            "❌ USERNAME PURCHASE TIMEOUT: Function took too long"
                        )
                    except HTTPException as e:
                        logger.error(
                            f"❌ USERNAME PURCHASE FAILED (HTTP {e.status_code}): {e.detail}"
                        )
                        if e.status_code == 402:
                            logger.info(
                                "💰 Stopping username monitor due to insufficient balance"
                            )
                            app_state.monitor_should_stop = True
                        else:
                            logger.info(
                                "🔄 Username purchase failed, will try again in next cycle"
                            )
                    except Exception as e:
                        logger.error(f"❌ USERNAME PURCHASE ERROR: {e}")
                        logger.info(
                            "🔄 Username purchase error, will try again in next cycle"
                        )

            except Exception as e:
                logger.error(f"process_username_listings error: {e}")

        app_state.monitor = NumbersMonitor(
            get_fragment_usernames_client(),
            on_new_listing=lambda item: asyncio.create_task(
                process_username_listings()
            ),
            interval_sec=body.interval_sec,
        )
        await app_state.monitor.start()

        return {
            "status": "started",
            "type": "usernames",
            "interval_sec": body.interval_sec,
            "max_price_ton": body.max_price_ton,
            "balance_ton": balance_ton,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start username monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "monitor_start_failed",
                "message": "Failed to start usernames monitor",
                "details": str(e),
                "type": "usernames",
            },
        )


@app.post("/monitor-usernames/stop")
async def stop_username_monitor() -> Dict[str, str]:
    try:
        if app_state.monitor is not None:
            await app_state.monitor.stop()
            app_state.monitor = None
        app_state.monitor_should_stop = False
        return {"status": "stopped", "type": "usernames"}
    except Exception as e:
        logger.error(f"Failed to stop username monitor: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "monitor_stop_failed",
                "message": "Failed to stop usernames monitor",
                "details": str(e),
                "type": "usernames",
            },
        )


@app.post("/buy-number", response_model=BuyResponse)
async def buy_number(body: BuyRequest) -> Dict[str, Any]:
    logger.info(
        f"🔧 BUY FUNCTION START: number_id={body.number_id}, bid_ton={body.bid_ton}"
    )

    try:
        client = get_fragment_client()
        ton = await get_ton_instance()

        bid = body.bid_ton
        if bid is None:
            logger.info("🔧 Getting bid from listings...")
            listings = await client.list_sales()
            match = next((x for x in listings if x.get("id") == body.number_id), None)
            if match and match.get("price_ton_int") is not None:
                bid = int(match["price_ton_int"])
                logger.info(f"🔧 Found bid: {bid}")
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="bid_ton is required or number must be present in current sales list",
                )

        logger.info("🔧 Getting account payload...")
        account = await ton.get_fragment_account_payload()
        logger.info("🔧 Getting device payload...")
        device = TON.default_device_payload()
        logger.info("🔧 Getting number info...")
        info = await asyncio.wait_for(
            client.get_number_info(body.number_id), timeout=10.0
        )
        logger.info("🔧 Getting bid link...")
        prep = await asyncio.wait_for(
            client.api_get_bid_link(
                number_id=body.number_id,
                bid_ton=bid,
                account=account,
                device=device,
                api_hash=info.get("api_hash"),
            ),
            timeout=10.0,
        )

        logger.info(
            f"🔧 BUY PREP: to={prep.get('address')} amount_nano={prep.get('amount_nano')}"
        )
        logger.info("🔧 Attempting transfer...")

        res = await asyncio.wait_for(
            ton.transfer(
                to_bounceable=prep["address"],
                amount_nano=prep["amount_nano"],
                payload_b64=prep.get("payload_b64", ""),
            ),
            timeout=30.0,
        )

        logger.info(f"🔧 Transfer result: {res}")

        if res.get("ok") is True:
            logger.info(f"🔧 BUY SUCCESS: {res}")
            return {"status": "sent", "tx": res}
        else:
            error_type = res.get("error", "unknown_error")
            logger.error(f"🔧 BUY FAILED: {error_type}")

            if error_type == "insufficient_balance":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "insufficient_balance",
                        "message": "Insufficient balance for purchase",
                        "required_amount": res.get("amount_nano", 0) / 1_000_000_000,
                        "current_balance": res.get("balance_nano", 0) / 1_000_000_000,
                        "shortage": (
                            res.get("amount_nano", 0) - res.get("balance_nano", 0)
                        )
                        / 1_000_000_000,
                        "item_type": "number",
                        "item_id": body.number_id,
                    },
                )
            elif error_type == "transfer_failed":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "transfer_failed",
                        "message": "TON transfer failed",
                        "result": res.get("result", "Unknown error"),
                        "item_type": "number",
                        "item_id": body.number_id,
                    },
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "transaction_failed",
                        "message": f"Transaction failed: {error_type}",
                        "error_type": error_type,
                        "details": res.get("details", "No details"),
                        "item_type": "number",
                        "item_id": body.number_id,
                    },
                )

    except asyncio.TimeoutError as e:
        logger.error(f"🔧 TIMEOUT in buy function: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "operation_timeout",
                "message": "Operation timed out",
                "details": str(e),
                "item_type": "number",
                "item_id": body.number_id,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔧 UNEXPECTED ERROR in buy function: {e}")
        msg = str(e)
        if "exit code -256" in msg or "seqno" in msg:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "wallet_not_activated",
                    "message": "Wallet is not activated or has insufficient balance",
                    "details": "Please fund the wallet, then retry",
                    "item_type": "number",
                    "item_id": body.number_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "unexpected_error",
                "message": "Unexpected error occurred",
                "details": msg,
                "item_type": "number",
                "item_id": body.number_id,
            },
        )


@app.post("/buy-username")
async def buy_username(body: BuyUsernameRequest) -> Dict[str, Any]:
    logger.info(
        f"🔧 BUY USERNAME FUNCTION START: username_id={body.username_id}, bid_ton={body.bid_ton}"
    )

    try:
        client = get_fragment_usernames_client()
        ton = await get_ton_instance()

        bid = body.bid_ton
        if bid is None:
            logger.info("🔧 Getting bid from listings...")
            listings = await client.list_sales()
            match = next((x for x in listings if x.get("id") == body.username_id), None)
            if match and match.get("price_ton_int") is not None:
                bid = int(match["price_ton_int"])
                logger.info(f"🔧 Found bid: {bid}")
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="bid_ton is required or username must be present in current sales list",
                )

        logger.info("🔧 Getting account payload...")
        account = await ton.get_fragment_account_payload()
        logger.info("🔧 Getting device payload...")
        device = TON.default_device_payload()
        logger.info("🔧 Getting username info...")
        info = await asyncio.wait_for(
            client.get_username_info(body.username_id), timeout=10.0
        )
        logger.info("🔧 Getting bid link...")
        prep = await asyncio.wait_for(
            client.api_get_bid_link(
                username_id=body.username_id,
                bid_ton=bid,
                account=account,
                device=device,
                api_hash=info.get("api_hash"),
            ),
            timeout=10.0,
        )

        logger.info(
            f"🔧 BUY PREP: to={prep.get('address')} amount_nano={prep.get('amount_nano')}"
        )
        logger.info("🔧 Attempting transfer...")

        res = await asyncio.wait_for(
            ton.transfer(
                to_bounceable=prep["address"],
                amount_nano=prep["amount_nano"],
                payload_b64=prep.get("payload_b64", ""),
            ),
            timeout=30.0,
        )

        logger.info(f"🔧 Transfer result: {res}")

        if res.get("ok") is True:
            logger.info(f"🔧 BUY USERNAME SUCCESS: {res}")
            return {"status": "sent", "tx": res}
        else:
            error_type = res.get("error", "unknown_error")
            logger.error(f"🔧 BUY USERNAME FAILED: {error_type}")

            if error_type == "insufficient_balance":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail={
                        "error": "insufficient_balance",
                        "message": "Insufficient balance for purchase",
                        "required_amount": res.get("amount_nano", 0) / 1_000_000_000,
                        "current_balance": res.get("balance_nano", 0) / 1_000_000_000,
                        "shortage": (
                            res.get("amount_nano", 0) - res.get("balance_nano", 0)
                        )
                        / 1_000_000_000,
                        "item_type": "username",
                        "item_id": body.username_id,
                    },
                )
            elif error_type == "transfer_failed":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "transfer_failed",
                        "message": "TON transfer failed",
                        "result": res.get("result", "Unknown error"),
                        "item_type": "username",
                        "item_id": body.username_id,
                    },
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "transaction_failed",
                        "message": f"Transaction failed: {error_type}",
                        "error_type": error_type,
                        "details": res.get("details", "No details"),
                        "item_type": "username",
                        "item_id": body.username_id,
                    },
                )

    except asyncio.TimeoutError as e:
        logger.error(f"🔧 TIMEOUT in buy username function: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "operation_timeout",
                "message": "Operation timed out",
                "details": str(e),
                "item_type": "username",
                "item_id": body.username_id,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"🔧 UNEXPECTED ERROR in buy username function: {e}")
        msg = str(e)
        if "exit code -256" in msg or "seqno" in msg:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "wallet_not_activated",
                    "message": "Wallet is not activated or has insufficient balance",
                    "details": "Please fund the wallet, then retry",
                    "item_type": "username",
                    "item_id": body.username_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "unexpected_error",
                "message": "Unexpected error occurred",
                "details": msg,
                "item_type": "username",
                "item_id": body.username_id,
            },
        )


@app.get("/wallet")
async def wallet_info() -> Dict[str, Any]:
    try:
        ton = await get_ton_instance()
        addr = await ton.get_address()
        bal = await ton.get_balance_nano()
        return {"address": addr, "balance_nano": bal}
    except Exception as e:
        logger.error(f"Failed to get wallet info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "wallet_info_failed",
                "message": "Failed to retrieve wallet information",
                "details": str(e),
            },
        )
