"""
WhatsApp Sender — Task 2
Modes:
  --dry-run  (default): log every message to file/console, no actual sending
  --live:    send 1-2 real messages via whatsapp-web.js (Playwright + WA Web)

Input: CSV with columns [phone, message]  OR  the parkings CSV from Task 1
       (in which case a template message is generated per parking)
"""

import asyncio
import csv
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("whatsapp_sender.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

DRY_RUN_LOG = "dry_run_messages.log"


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Message:
    phone: str          # international format, e.g. +77001234567
    text: str
    row_index: int = 0
    status: str = "pending"   # pending | sent | failed | skipped
    error: str = ""


# ── validation ────────────────────────────────────────────────────────────────

KZ_PHONE_RE = re.compile(r"^\+?[78]\d{10}$")
INTL_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def normalize_phone(raw: str) -> tuple[str, str]:
    """
    Returns (normalized_e164, error_str).
    Normalizes KZ numbers starting with 8 → +7.
    """
    clean = re.sub(r"[\s\-\(\)\.]+", "", raw.strip())
    if not clean:
        return "", "empty phone number"
    # KZ shorthand: 8XXXXXXXXXX → +7XXXXXXXXXX
    if re.match(r"^8\d{10}$", clean):
        clean = "+7" + clean[1:]
    elif re.match(r"^7\d{10}$", clean):
        clean = "+" + clean
    elif not clean.startswith("+"):
        clean = "+" + clean

    if not INTL_PHONE_RE.match(clean):
        return "", f"invalid format: '{raw}'"
    return clean, ""


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_messages_from_csv(path: str, template: Optional[str] = None) -> list[Message]:
    """
    Load messages from CSV.
    Expected columns: phone, message  OR  phone + parking fields (use template).
    """
    messages = []
    p = Path(path)
    if not p.exists():
        log.error(f"File not found: {path}")
        sys.exit(1)

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.lower() for h in (reader.fieldnames or [])]

        has_message_col = "message" in headers
        has_name_col = "name" in headers
        has_phone_col = "phone" in headers or "телефон" in headers or "номер" in headers

        if not has_phone_col:
            log.warning(
                "No 'phone' column found. "
                "If using the parking CSV, phone numbers aren't in 2GIS data — "
                "this is expected. Demonstrating dry-run with placeholder numbers."
            )

        for i, row in enumerate(reader, start=2):
            # Get phone
            phone_raw = (
                row.get("phone") or row.get("Phone") or
                row.get("телефон") or row.get("номер") or
                "+77000000001"  # placeholder for parking data without phones
            )
            phone, err = normalize_phone(phone_raw)

            # Get or build message text
            if has_message_col:
                text = row.get("message", "").strip()
            elif template:
                text = template.format(**{k.lower(): v for k, v in row.items()})
            elif has_name_col:
                name = row.get("name", row.get("Name", "Объект"))
                address = row.get("address", row.get("Address", ""))
                hours = row.get("hours", "")
                text = (
                    f"Здравствуйте! Информация о парковке:\n"
                    f"📍 {name}\n"
                    f"🗺 {address}\n"
                    f"🕐 {hours or 'часы не указаны'}\n"
                    f"Источник: 2ГИС"
                )
            else:
                text = "Тестовое сообщение от парсера 2ГИС"

            msg = Message(phone=phone, text=text, row_index=i, error=err)
            if err:
                msg.status = "skipped"
            messages.append(msg)

    log.info(f"Loaded {len(messages)} records from {path}")
    return messages


# ── dry-run sender ────────────────────────────────────────────────────────────

def run_dry(messages: list[Message]) -> list[Message]:
    """Simulate sending — write everything to log file."""
    log.info(f"DRY-RUN mode: logging {len(messages)} messages (no actual sending)")

    with open(DRY_RUN_LOG, "w", encoding="utf-8") as out:
        out.write(f"# Dry-run log — {datetime.now().isoformat()}\n\n")
        for msg in messages:
            if msg.status == "skipped":
                line = f"[SKIPPED] row={msg.row_index} phone_raw='{msg.phone}' error='{msg.error}'"
                log.warning(line)
                out.write(line + "\n\n")
                continue

            out.write(f"[WOULD SEND]\n")
            out.write(f"  TO:   {msg.phone}\n")
            out.write(f"  TEXT: {msg.text}\n")
            out.write(f"  ROW:  {msg.row_index}\n\n")

            msg.status = "dry-run-ok"
            log.info(f"  → {msg.phone}: {msg.text[:60]}...")

    sent = sum(1 for m in messages if m.status == "dry-run-ok")
    skipped = sum(1 for m in messages if m.status == "skipped")
    log.info(f"Dry-run complete: {sent} logged, {skipped} skipped (invalid phone)")
    log.info(f"Full log written to {DRY_RUN_LOG}")
    return messages


# ── live sender (WhatsApp Web via Playwright) ─────────────────────────────────

async def run_live(messages: list[Message], limit: int = 2) -> list[Message]:
    """
    Send up to `limit` real messages via WhatsApp Web.
    Requires: playwright install chromium
    First run: scan QR code with your phone.
    Session is saved to ./wa_session/ for reuse.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    to_send = [m for m in messages if m.status == "pending"][:limit]
    log.info(f"LIVE mode: sending {len(to_send)} message(s)")

    session_dir = Path("./wa_session")
    session_dir.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=False,   # must be visible to scan QR on first run
            args=["--no-sandbox"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        log.info("Opening WhatsApp Web...")
        await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")

        # Wait for QR scan or already-logged-in state (up to 60s)
        log.info("Waiting for WhatsApp Web to load (scan QR if prompted)...")
        try:
            await page.wait_for_selector(
                '[data-testid="default-user"], [data-testid="chat-list"]',
                timeout=90_000,
            )
            log.info("WhatsApp Web loaded successfully.")
        except Exception:
            log.error("WhatsApp Web did not load in time. Check if QR was scanned.")
            await browser.close()
            return messages

        for msg in to_send:
            try:
                phone_digits = re.sub(r"[^\d]", "", msg.phone)
                url = f"https://web.whatsapp.com/send?phone={phone_digits}&text="
                log.info(f"Opening chat with {msg.phone}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(4000)

                # Type the message
                input_box = page.locator('[data-testid="conversation-compose-box-input"]')
                await input_box.wait_for(timeout=15_000)
                await input_box.click()
                await input_box.type(msg.text, delay=30)
                await page.wait_for_timeout(500)

                # Send
                send_btn = page.locator('[data-testid="send"]')
                await send_btn.click()
                await page.wait_for_timeout(2000)

                msg.status = "sent"
                log.info(f"✅ Sent to {msg.phone}")

            except Exception as e:
                msg.status = "failed"
                msg.error = str(e)
                log.error(f"❌ Failed to send to {msg.phone}: {e}")

            # Rate limit: wait between messages
            time.sleep(3)

        await browser.close()

    sent = sum(1 for m in messages if m.status == "sent")
    failed = sum(1 for m in messages if m.status == "failed")
    log.info(f"Live send complete: {sent} sent, {failed} failed")
    return messages


# ── result report ─────────────────────────────────────────────────────────────

def print_summary(messages: list[Message]):
    counts: dict[str, int] = {}
    for m in messages:
        counts[m.status] = counts.get(m.status, 0) + 1
    print("\n── Summary ───────────────────────────────")
    for status, count in sorted(counts.items()):
        print(f"  {status:<16} {count}")
    print("──────────────────────────────────────────\n")


def save_results_json(messages: list[Message], path: str = "send_results.json"):
    data = [
        {"row": m.row_index, "phone": m.phone, "status": m.status, "error": m.error}
        for m in messages
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"Results saved → {path}")


# ── entry point ───────────────────────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="WhatsApp bulk sender (dry-run by default)")
    parser.add_argument("csv", help="Input CSV file (phone + message, or parking CSV)")
    parser.add_argument(
        "--live", action="store_true",
        help="Actually send messages (default is dry-run)"
    )
    parser.add_argument(
        "--live-limit", type=int, default=2,
        help="Max messages to send in live mode (default 2)"
    )
    parser.add_argument(
        "--template", default=None,
        help="Message template with {field} placeholders matching CSV column names"
    )
    args = parser.parse_args()

    messages = load_messages_from_csv(args.csv, template=args.template)

    if args.live:
        log.warning(
            "LIVE MODE ACTIVE — messages will be sent to real numbers. "
            f"Limit: {args.live_limit}"
        )
        messages = await run_live(messages, limit=args.live_limit)
    else:
        log.info("DRY-RUN mode (default). Pass --live to actually send.")
        messages = run_dry(messages)

    print_summary(messages)
    save_results_json(messages)


if __name__ == "__main__":
    asyncio.run(main())