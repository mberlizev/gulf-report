import os
import asyncio
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand
import anthropic

load_dotenv(Path(__file__).parent / ".env")

bot = Bot(token=os.environ["BOT_TOKEN"])
dp = Dispatcher()
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

WEBAPP_URL = "https://mberlizev.github.io/gulf-report/uae_telegram.html"
CLAUDE_CLI = "/Users/mikhailberlizev/.local/bin/claude"
WORK_DIR = str(Path.home() / "Desktop" / "Claude_Fabric")

dashboard_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(
        text="Open Dashboard",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )]
])

OWNER_USERNAME = "kosmos_mb"
owner_chat_id = None  # int, auto-saved on first owner message

# --- Crypto alert settings ---
ARB_CHECK_INTERVAL = 180  # seconds between checks
SPREAD_THRESHOLD = 0.15   # % — alert if cross-exchange spread exceeds this
FUNDING_THRESHOLD = 50.0  # annualised % — alert if funding rate exceeds this
BASIS_THRESHOLD = 0.3     # % — alert if spot/futures basis exceeds this
CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
PAIR_DISPLAY = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "XRPUSDT": "XRP"}

PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
}

SYSTEM_PROMPT = (
    "Ты — Anna, AI-ассистент. Отвечай кратко и по делу на русском языке. "
    "Если спрашивают про дашборд ПВО ОАЭ — скажи использовать команду /uae_dashboard."
)

# Per-user state
histories: dict[int, list[dict]] = {}
MAX_HISTORY = 20

# Owner session ID for claude CLI conversation continuity
owner_session_id: str = ""


def fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


async def check_crypto_spreads():
    """Check cross-exchange spreads, funding rates, basis. Returns list of alert strings."""
    alerts = []

    try:
        binance_raw, bybit_raw, funding_raw = await asyncio.gather(
            asyncio.to_thread(fetch_json, "https://api.binance.com/api/v3/ticker/bookTicker"),
            asyncio.to_thread(fetch_json, "https://api.bybit.com/v5/market/tickers?category=spot"),
            asyncio.to_thread(fetch_json, "https://fapi.binance.com/fapi/v1/premiumIndex"),
        )
    except Exception as e:
        print(f"[crypto] fetch error: {e}")
        return []

    binance = {t["symbol"]: t for t in binance_raw}
    bybit = {t["symbol"]: t for t in bybit_raw["result"]["list"]}
    funding = {t["symbol"]: t for t in funding_raw}

    for sym in CRYPTO_PAIRS:
        name = PAIR_DISPLAY[sym]
        b = binance.get(sym)
        by = bybit.get(sym)

        # Cross-exchange spread
        if b and by:
            b_bid, b_ask = float(b["bidPrice"]), float(b["askPrice"])
            by_bid, by_ask = float(by["bid1Price"]), float(by["ask1Price"])
            spread_a = (by_bid - b_ask) / b_ask * 100  # buy Binance, sell Bybit
            spread_b = (b_bid - by_ask) / by_ask * 100  # buy Bybit, sell Binance
            best = max(spread_a, spread_b)
            if best > SPREAD_THRESHOLD:
                direction = "Binance->Bybit" if spread_a >= spread_b else "Bybit->Binance"
                alerts.append(f"📊 {name} спред {best:+.3f}% ({direction})")

        # Funding rate
        f = funding.get(sym)
        if f:
            rate = float(f["lastFundingRate"])
            annual = rate * 3 * 365 * 100
            if abs(annual) > FUNDING_THRESHOLD:
                alerts.append(f"💰 {name} funding {annual:+.1f}% годовых")

        # Basis
        if b and f:
            spot_mid = (float(b["bidPrice"]) + float(b["askPrice"])) / 2
            mark = float(f["markPrice"])
            basis = (mark - spot_mid) / spot_mid * 100
            if abs(basis) > BASIS_THRESHOLD:
                alerts.append(f"📐 {name} basis {basis:+.3f}% (спот vs фьючерс)")

    return alerts


async def crypto_alert_loop():
    """Background loop: check spreads every N seconds, notify owner."""
    await asyncio.sleep(10)  # wait for bot to start
    print(f"[crypto] alert loop started, interval={ARB_CHECK_INTERVAL}s")
    while True:
        if owner_chat_id:
            try:
                alerts = await check_crypto_spreads()
                if alerts:
                    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
                    msg = f"🚨 Крипто-алерт ({now}):\n\n" + "\n".join(alerts)
                    await bot.send_message(owner_chat_id, msg)
                    print(f"[crypto] sent {len(alerts)} alerts")
                else:
                    print(f"[crypto] check ok, no alerts")
            except Exception as e:
                print(f"[crypto] error: {e}")
        else:
            print("[crypto] waiting for owner to /start bot...")
        await asyncio.sleep(ARB_CHECK_INTERVAL)


async def run_claude_local(prompt):
    """Run claude CLI locally, resuming conversation if session exists."""
    global owner_session_id

    t0 = time.time()
    cmd = [CLAUDE_CLI, "-p", prompt, "--dangerously-skip-permissions", "--output-format", "json"]
    if owner_session_id:
        cmd.extend(["--resume", owner_session_id])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORK_DIR,
    )
    stdout, stderr = await proc.communicate()
    elapsed = time.time() - t0
    raw = stdout.decode("utf-8").strip()

    text = ""
    usage_line = ""
    try:
        data = json.loads(raw)
        text = data.get("result", "")
        # Save session for continuity
        sid = data.get("session_id", "")
        if sid:
            owner_session_id = sid
        # Usage stats
        usage = data.get("usage", {})
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cost = data.get("total_cost_usd", 0)
        usage_line = f"\n\n---\n📊 {inp}+{out} tok · ${cost:.4f} · {elapsed:.1f}s"
    except (json.JSONDecodeError, KeyError):
        text = raw

    if not text and stderr:
        text = "Ошибка: " + stderr.decode("utf-8").strip()[-500:]

    return (text or "Пустой ответ."), usage_line


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global owner_chat_id
    is_owner = (message.from_user.username == OWNER_USERNAME)
    if is_owner:
        owner_chat_id = message.chat.id
        await message.answer(
            "Привет, Михаил! Я подключена к локальному Claude Code.\n\n"
            "У меня есть доступ к файлам, терминалу, вебу.\n"
            "/uae_dashboard — дашборд ПВО ОАЭ\n"
            "/crypto — проверить спреды прямо сейчас\n"
            "/new — новый диалог\n\n"
            "Крипто-алерты включены (каждые 3 мин)."
        )
    else:
        await message.answer(
            "Hi! I'm Anna — your UAE situation assistant.\n\n"
            "This bot provides verified, factual data only — "
            "no clickbait, no fear-mongering.\n\n"
            "📊 /uae_dashboard — live air defence stats, "
            "school updates, economy, flights & visas\n\n"
            "Or just ask me anything.",
            reply_markup=dashboard_kb,
        )


@dp.message(Command("new"))
async def cmd_new(message: types.Message):
    global owner_session_id
    if message.from_user.username == OWNER_USERNAME:
        owner_session_id = ""
        await message.answer("Контекст сброшен. Новый диалог.")


@dp.message(Command("crypto"))
async def cmd_crypto(message: types.Message):
    global owner_chat_id
    if message.from_user.username != OWNER_USERNAME:
        return
    owner_chat_id = message.chat.id
    await message.answer("Проверяю спреды...")
    alerts = await check_crypto_spreads()
    if alerts:
        now = datetime.now(timezone.utc).strftime("%H:%M UTC")
        await message.answer(f"🚨 Крипто ({now}):\n\n" + "\n".join(alerts))
    else:
        await message.answer("Всё спокойно — спреды, фандинг и базис в норме.")


@dp.message(Command("uae_dashboard"))
async def cmd_dashboard(message: types.Message):
    await message.answer(
        "Дашборд ПВО ОАЭ — актуальные данные по перехватам, "
        "потерям и сравнению с другими конфликтами.",
        reply_markup=dashboard_kb,
    )


@dp.message()
async def any_message(message: types.Message):
    if not message.text:
        return

    global owner_chat_id
    is_owner = (message.from_user.username == OWNER_USERNAME)
    if is_owner and not owner_chat_id:
        owner_chat_id = message.chat.id
    print(f"[{message.from_user.username}] owner={is_owner} session={owner_session_id[:12] if owner_session_id else 'new'}")

    if is_owner:
        try:
            reply, usage_line = await run_claude_local(message.text)
            reply += usage_line
        except Exception as e:
            reply = f"Ошибка: {e}"

        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                await message.answer(reply[i:i+4000])
        else:
            await message.answer(reply)
    else:
        uid = message.from_user.id
        if uid not in histories:
            histories[uid] = []

        histories[uid].append({"role": "user", "content": message.text})
        if len(histories[uid]) > MAX_HISTORY:
            histories[uid] = histories[uid][-MAX_HISTORY:]

        try:
            resp = await asyncio.to_thread(
                claude.messages.create,
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=histories[uid],
            )
            reply = resp.content[0].text
            inp = resp.usage.input_tokens
            out = resp.usage.output_tokens
            p = PRICING["claude-sonnet-4-20250514"]
            cost = (inp * p["input"] + out * p["output"]) / 1_000_000
            reply += f"\n\n---\n📊 {inp}+{out} tok · ${cost:.4f}"
        except Exception as e:
            reply = f"Ошибка: {e}"

        histories[uid].append({"role": "assistant", "content": reply})
        await message.answer(reply)


async def main():
    print("Bot started (local Claude mode for owner)")
    await bot.set_my_commands([
        BotCommand(command="start", description="Start / restart the bot"),
        BotCommand(command="uae_dashboard", description="Live air defence dashboard"),
    ])
    asyncio.create_task(crypto_alert_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
