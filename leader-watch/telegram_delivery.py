"""Explicit destination only. Secrets stay in environment, never in logs."""
import hashlib
import json
import os
import urllib.request
from pathlib import Path


def send_once(text, asof, state_dir, checkpoint=None):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        raise RuntimeError('Telegram bot token and destination must be configured in secret storage')
    if len(text.encode('utf-16-le')) // 2 > 4096:
        raise ValueError('Telegram message exceeds limit')
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination_hash = hashlib.sha256(chat.encode()).hexdigest()[:16]
    receipt = directory / f'{asof}-{destination_hash}.json'
    # Exclusive reservation also blocks retry after an ambiguous network response.
    try:
        with receipt.open('x', encoding='utf-8') as f:
            json.dump({'status': 'pending', 'asof': asof, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()}, f)
    except FileExistsError:
        status = json.loads(receipt.read_text(encoding='utf-8'))['status']
        if status == 'sent':
            return 'already_sent'
        raise RuntimeError('Previous delivery status uncertain; inspect destination before retry')
    if checkpoint:
        checkpoint()  # Persist reservation remotely before the network side effect.
    payload = json.dumps({'chat_id': chat, 'text': text, 'link_preview_options': {'is_disabled': True}}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise ValueError('Rejected')
        message_id = result['result']['message_id']
    except Exception:
        # Never propagate exceptions that might contain a URL with the bot token.
        raise RuntimeError('Telegram delivery not confirmed; automatic resend blocked') from None
    temp = receipt.with_suffix('.tmp')
    temp.write_text(json.dumps({'status': 'sent', 'asof': asof, 'message_id': message_id}), encoding='utf-8')
    temp.replace(receipt)
    if checkpoint:
        checkpoint()
    return 'sent'
