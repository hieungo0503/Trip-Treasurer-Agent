# Zalo OA API — Quirks & Reference

## Signature Verification

```python
import hmac, hashlib

def verify_zalo_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """
    Zalo gửi header X-ZEvent-Signature = mac(app_secret, body).
    Verify HMAC-SHA256.
    """
    expected = hmac.new(
        app_secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**Quirk:** Zalo có thể gửi cùng 1 event nhiều lần nếu server respond chậm.
Luôn dùng idempotency key (`event_id` hoặc `id` trong payload).

## Gửi tin nhắn text

```python
async def send_text(zalo_user_id: str, text: str, access_token: str):
    """Gửi text message tới user."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://openapi.zalo.me/v3.0/oa/message/cs",
            headers={
                "access_token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "recipient": {"user_id": zalo_user_id},
                "message": {"text": text},
            },
            timeout=10,
        )
    return resp.json()
```

**Quirk:** Text message giới hạn 2000 ký tự. Nếu bot reply dài → tự động split.

```python
MAX_ZALO_TEXT = 1800  # Buffer 200 ký tự

def split_long_message(text: str) -> list[str]:
    if len(text) <= MAX_ZALO_TEXT:
        return [text]
    parts = []
    while text:
        parts.append(text[:MAX_ZALO_TEXT])
        text = text[MAX_ZALO_TEXT:]
    return parts
```

## Download ảnh từ user

```python
async def download_image(attachment_id: str, access_token: str) -> bytes:
    """Download ảnh user gửi."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://openapi.zalo.me/v2.0/oa/message/attachment",
            params={"attachment_id": attachment_id},
            headers={"access_token": access_token},
            timeout=30,
        )
    return resp.content
```

**Quirk:** URL ảnh trong webhook có expiry ~1 giờ. Download ngay hoặc lưu attachment_id để download sau qua API.

## Refresh Access Token

```python
async def refresh_access_token(
    app_id: str,
    app_secret: str,
    refresh_token: str,
) -> dict:
    """
    Refresh Zalo OA access token.
    Access token expire sau 90 ngày (nếu dùng liên tục).
    Refresh token expire sau 90 ngày KHÔNG dùng.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth.zaloapp.com/v4/oa/access_token",
            data={
                "app_id": app_id,
                "app_secret": app_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data["expires_in"],
    }
```

Cron job `scripts/refresh_zalo_token.py` chạy mỗi 60 ngày.

## Webhook Payload Schema

```python
class ZaloWebhookPayload(BaseModel):
    event_name: str       # "user_send_text" | "user_send_image" | "follow" | "unfollow"
    event_id: str         # unique per event
    timestamp: int        # ms since epoch
    sender: ZaloSender    # user_id, display_name
    recipient: ZaloRecipient  # oa_id
    message: ZaloMessage | None = None
    attachments: list[ZaloAttachment] | None = None

class ZaloSender(BaseModel):
    id: str        # zalo_user_id của người gửi

class ZaloMessage(BaseModel):
    text: str | None = None
    attachments: list | None = None

class ZaloAttachment(BaseModel):
    type: str           # "image" | "gif" | "audio" | "video" | "file"
    payload: dict       # {"attachment_id": "...", "url": "...", "description": "..."}
```

## Rate Limits Zalo OA

- Send message: 10 requests/giây, 100.000 messages/ngày (free OA)
- Upload: 5 MB / request
- Webhook delivery: Zalo retry 3 lần nếu không nhận 200 OK

## Event Types quan trọng

| event_name | Khi nào | Xử lý |
|---|---|---|
| `user_send_text` | User gõ text | Parse intent → handle |
| `user_send_image` | User gửi ảnh | Download → OCR → handle |
| `follow` | User follow OA | Gửi welcome message |
| `unfollow` | User unfollow | Log, không gửi gì |
| `user_send_sticker` | Sticker | Bỏ qua hoặc reply "😊" |
| `user_send_gif` | GIF | Bỏ qua |

## Bắt đầu conversation với user (ping trực tiếp)

Khi admin thêm member cũ vào trip mới, bot cần ping user:

```python
async def ping_existing_member(
    zalo_user_id: str,
    trip_name: str,
    required_amount: int,
    admin_name: str,
):
    """Bot chủ động nhắn user (chỉ được nếu user đã từng tương tác với OA)."""
    text = (
        f"👋 Chào! {admin_name} vừa thêm bạn vào chuyến mới:\n"
        f"📍 {trip_name}\n"
        f"💰 Vui lòng nạp {format_money(required_amount)} và xác nhận:\n"
        f"Gõ: \"ok đã nạp {format_money_compact(required_amount)}\""
    )
    await send_text(zalo_user_id, text, access_token)
```

**Quirk quan trọng:** Bot chỉ được phép gửi tin chủ động cho user đã từng tương tác (follow OA hoặc gửi tin trước). Nếu user chưa bao giờ nhắn → 403 error → chỉ có thể đợi user tự nhắn.
