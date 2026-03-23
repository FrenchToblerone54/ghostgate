# گوست‌گیت - پنل مدیریت اشتراک VPN

**[📖 English](README.md)**

گوست‌گیت یک پنل فروش و مدیریت اشتراک برای پنل‌های VPN [3x-ui](https://github.com/MHSanaei/3x-ui) است. این پنل ربات تلگرام برای مدیریت اشتراک‌ها، پنل مدیریت وب و همگام‌سازی خودکار ترافیک در چندین نود را فراهم می‌کند.

## ویژگی‌ها

- **پشتیبانی از چندین نود** - مدیریت اشتراک‌ها در چندین سرور 3x-ui با محدودیت داده مشترک

- **ربات تلگرام** - ایجاد، ویرایش، حذف و مانیتور اشتراک‌ها از طریق دستورات ربات

- **پنل مدیریت وب** - مانیتورینگ بلادرنگ سیستم، مدیریت اشتراک، مدیریت نود، لاگ‌ها

- **همگام‌سازی خودکار** - کارگر پس‌زمینه مصرف ترافیک را همگام می‌کند و محدودیت‌های داده/انقضا را اعمال می‌کند

- **لینک‌های اشتراک** - آدرس‌های اشتراک VLESS و VMess استاندارد با QR کد

- **پشتیبانی از پروکسی خارجی** - تنظیمات external proxy در 3x-ui را برای CDN رعایت می‌کند

- **فایل باینری کامپایل شده** - Linux amd64 و arm64 (سازگار با Ubuntu 22.04+)، نیازی به Python در سرور نیست

- **سرویس systemd** - شروع خودکار، راه‌اندازی مجدد، لاگ‌نویسی

- **به‌روزرسانی خودکار** - به‌روزرسانی خودکار فایل باینری از طریق GitHub؛ به‌روزرسانی دستی با `ghostgate update` یا از صفحه Settings

- **عملیات دسته‌جمعی** - حذف، فعال یا غیرفعال کردن چندین اشتراک همزمان از پنل وب

- **نصب آسان** - اسکریپت نصب یک دستوری با تنظیمات تعاملی

## شروع سریع

```bash
wget https://raw.githubusercontent.com/frenchtoblerone54/ghostgate/main/scripts/install.sh -O install.sh
chmod +x install.sh
sudo ./install.sh
```

آدرس پنل نشان داده شده در پایان را ذخیره کنید — این مسیر دسترسی به پنل مدیریت شماست.

## دستورات ربات

```
/create [--comment نام] [--note X] [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--ip N] [--nodes 1,2|all|none]
/delete <آیدی یا کامنت>
/stats <آیدی یا کامنت>
/list [صفحه]
/edit <آیدی یا کامنت> [--comment X] [--note X] [--data GB] [--days N] [--firstuse-days N] [--firstuse-seconds N] [--no-firstuse] [--remove-data GB] [--remove-days N] [--no-expire] [--ip N] [--enable] [--disable]
/regen <آیدی یا کامنت>
/configs <آیدی یا کامنت>
/nodes
/addnode --name X --addr http://... --user X --pass X --inbound N [--proxy http://...] [--multiplier N]
/editnode <id> [--name X] [--addr X] [--user X] [--pass X] [--proxy X] [--enable] [--disable]
/delnode <id>
/subnodes [node_id]
/addsubnode --node N --inbound N [--name X] [--multiplier N]
/editsubnode <id> [--name X] [--inbound N] [--multiplier N] [--enable] [--disable] [--move-up] [--move-down]
/delsubnode <id>
```

فعال/غیرفعال کردن نود یا ساب‌نود باعث حذف یا بازسازی کلاینت‌های آن در 3x-ui می‌شود. صفحه اشتراک در مرورگر، کانفیگ‌های منفرد هر نود را با QR کد نمایش می‌دهد.

## تنظیمات

تمام تنظیمات در `/opt/ghostgate/.env` ذخیره می‌شوند. همچنین می‌توان آن‌ها را از صفحه Settings در پنل وب ویرایش کرد (برای اعمال تغییرات نیاز به راه‌اندازی مجدد است).

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `BASE_URL` | | آدرس عمومی سرور (مثلاً `https://your-domain.com`) |
| `BOT_TOKEN` | | توکن ربات تلگرام از @BotFather |
| `ADMIN_ID` | | آیدی تلگرام شما |
| `PANEL_PATH` | خودکار | مسیر مخفی برای پنل وب |
| `HOST` | `127.0.0.1` | هاست شنود |
| `PORT` | `5000` | پورت شنود |
| `SYNC_INTERVAL` | `20` | فاصله همگام‌سازی ترافیک به ثانیه |
| `BOT_PROXY` | | پروکسی HTTP برای ربات تلگرام (اختیاری) |
| `UPDATE_PROXY` | | پروکسی HTTP برای به‌روزرسان خودکار (اختیاری) |
| `PANEL_THREADS` | `8` | تعداد thread های Waitress |
| `DB_PATH` | `/opt/ghostgate/ghostgate.db` | مسیر دیتابیس SQLite |
| `LOG_FILE` | `/var/log/ghostgate.log` | مسیر فایل لاگ |
| `AUTO_UPDATE` | `false` | فعال‌سازی به‌روزرسانی خودکار باینری |
| `UPDATE_CHECK_INTERVAL` | `300` | فاصله بررسی به‌روزرسانی به ثانیه |

## REST API

پنل وب یک REST API در آدرس `/{panel_path}/api/` ارائه می‌دهد. امنیت آن از طریق مسیر مخفی پنل تأمین می‌شود — نیازی به توکن احراز هویت جداگانه نیست. همین API توسط خود پنل وب استفاده می‌شود.

### اشتراک‌ها

| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/subscriptions` | لیست اشتراک‌ها. پارامترها: `page`، `per_page` (0 = همه)، `search` |
| `GET` | `/api/subscriptions/stream` | SSE stream — فقط اشتراک‌های تغییرکرده/حذف‌شده هر ۵ ثانیه |
| `POST` | `/api/subscriptions` | ایجاد اشتراک و افزودن به نودها. Body: `comment`، `data_gb`، `days`، `ip_limit`، `node_ids`، `show_multiplier`، `expire_after_first_use_seconds` |
| `GET` | `/api/subscriptions/<id>` | دریافت اشتراک همراه با لیست نودها |
| `PUT` | `/api/subscriptions/<id>` | ویرایش فیلدها: `comment`، `data_gb`، `days`، `ip_limit`، `enabled`، `show_multiplier`، `expire_after_first_use_seconds`، `remove_days`، `remove_expiry`، `remove_data_limit` |
| `DELETE` | `/api/subscriptions/<id>` | حذف اشتراک و حذف کلاینت از تمام نودها |
| `GET` | `/api/subscriptions/<id>/stats` | دریافت آمار ترافیک |
| `GET` | `/api/subscriptions/<id>/qr` | تصویر PNG کد QR برای لینک اشتراک |
| `POST` | `/api/subscriptions/<id>/nodes` | افزودن نود(ها) به اشتراک موجود |
| `DELETE` | `/api/subscriptions/<id>/nodes/<node_id>` | حذف یک نود از اشتراک |
| `POST` | `/api/subscriptions/<id>/regen-id` | بازسازی nanoid اشتراک (کلاینت‌های XUI به‌روز می‌شوند). پاسخ: `{new_id, url}` |

**ایجاد اشتراک — بدنه درخواست:**
```json
{
  "comment": "علی رضایی",
  "data_gb": 10,
  "days": 30,
  "ip_limit": 2,
  "node_ids": [1, 2]
}
```

**ایجاد اشتراک — پاسخ:**
```json
{
  "id": "abc123...",
  "uuid": "xxxxxxxx-...",
  "url": "https://your-domain.com/sub/abc123...",
  "errors": []
}
```

آرایه `errors` نودهایی را که دریافت کلاینت در آن‌ها ناموفق بوده نشان می‌دهد — اشتراک در هر صورت در دیتابیس ذخیره می‌شود.

### نودها

| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/nodes` | لیست تمام نودها (بدون رمز عبور) |
| `POST` | `/api/nodes` | افزودن نود |
| `PUT` | `/api/nodes/<id>` | ویرایش فیلدهای نود. پشتیبانی از `enabled` (0 یا 1) برای غیرفعال/فعال کردن نود |
| `DELETE` | `/api/nodes/<id>` | حذف نود |
| `GET` | `/api/nodes/<id>/test` | تست اتصال و دسترسی به inbound |

**افزودن نود — بدنه درخواست:**
```json
{
  "name": "آلمان ۱",
  "address": "http://1.2.3.4:54321",
  "username": "admin",
  "password": "secret",
  "inbound_id": 1,
  "proxy_url": null
}
```

**افزودن نود(ها) به اشتراک — بدنه درخواست:**
```json
{ "node_ids": [1, 2] }
```

نودهایی که از قبل به اشتراک اختصاص دارند بدون خطا نادیده گرفته می‌شوند.

### عملیات دسته‌جمعی

| متد | مسیر | توضیح |
|---|---|---|
| `POST` | `/api/bulk/nodes` | افزودن یا حذف یک نود از چندین اشتراک به‌صورت همزمان |
| `POST` | `/api/bulk/delete` | حذف چندین اشتراک و حذف کلاینت‌های آن‌ها از تمام نودها |
| `POST` | `/api/bulk/toggle` | فعال یا غیرفعال کردن چندین اشتراک |
| `POST` | `/api/bulk/extend` | افزودن داده (GB) و/یا روز به چندین اشتراک |
| `POST` | `/api/bulk/data` | ضرب یا تقسیم محدودیت داده چندین اشتراک در یک ضریب |
| `POST` | `/api/bulk/note` | تنظیم یا پاک‌کردن یادداشت چندین اشتراک |

**بدنه درخواست `/api/bulk/nodes`:**
```json
{
  "sub_ids": ["abc123", "def456"],
  "node_ids": [1],
  "action": "add"
}
```

`action` باید `"add"` یا `"remove"` باشد. پاسخ: `{"ok": true, "errors": [...]}`.

**بدنه درخواست `/api/bulk/delete`:**
```json
{ "sub_ids": ["abc123", "def456"] }
```

پاسخ: `{"ok": true, "deleted": 2}`.

**بدنه درخواست `/api/bulk/toggle`:**
```json
{ "sub_ids": ["abc123", "def456"], "enabled": false }
```

پاسخ: `{"ok": true}`.

**بدنه درخواست `/api/bulk/extend`:**
```json
{ "sub_ids": ["abc123", "def456"], "data_gb": 10, "days": 30 }
```

هر دو فیلد `data_gb` و `days` اختیاری و افزایشی هستند — داده به محدودیت فعلی اضافه می‌شود و روزها از انقضای فعلی (یا از الان در صورت نداشتن انقضا) افزوده می‌شوند. **مقادیر منفی کاهش می‌دهند** — مثلاً `"data_gb": -5` پنج گیگابایت کم می‌کند (کف صفر)، `"days": -7` هفت روز از انقضای فعلی کم می‌کند (در صورت نداشتن انقضا نادیده گرفته می‌شود). با `"remove_expiry": true` انقضا حذف می‌شود (اولویت بر `days`). با `"remove_data_limit": true` محدودیت داده حذف می‌شود (اولویت بر `data_gb`). پاسخ: `{"ok": true}`.

**بدنه درخواست `/api/bulk/data`:**
```json
{ "sub_ids": ["abc123", "def456"], "factor": 2, "action": "multiply" }
```

`action` باید `"multiply"` (ضرب) یا `"divide"` (تقسیم) باشد. محدودیت داده هر اشتراک در ضریب `factor` ضرب یا تقسیم می‌شود. اشتراک‌های با داده نامحدود (0 GB) نادیده گرفته می‌شوند. پاسخ: `{"ok": true}`.

**بدنه درخواست `/api/bulk/note`:**
```json
{ "sub_ids": ["abc123", "def456"], "note": "یادداشت دسته‌جمعی" }
```

برای پاک‌کردن یادداشت، فیلد `note` را حذف کنید یا `null` بفرستید. پاسخ: `{"ok": true}`.

### سایر

| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/status` | متریک‌های سیستم (CPU، RAM، دیسک، شبکه، بار) |
| `GET` | `/api/update` | بررسی به‌روزرسانی. پاسخ: `{current, latest, update_available}` |
| `POST` | `/api/update` | دانلود و اعمال آخرین به‌روزرسانی، سپس راه‌اندازی مجدد |
| `GET` | `/api/settings` | دریافت تمام مقادیر تنظیمات `.env` |
| `POST` | `/api/settings` | ذخیره مقادیر تنظیمات (بیشتر تغییرات نیاز به راه‌اندازی مجدد دارند) |
| `POST` | `/api/restart` | راه‌اندازی مجدد سرویس GhostGate |
| `GET` | `/api/logs` | ۲۰۰ خط آخر لاگ (متن ساده) |
| `GET` | `/api/logs/stream` | جریان زنده لاگ (SSE، هر ۱۰ ثانیه در صورت سکوت `: heartbeat` ارسال می‌شود) |

### لینک اشتراک

آدرس اشتراک کاربر نهایی عمومی است و نیازی به احراز هویت ندارد:

```
https://your-domain.com/sub/<id>
```

این آدرس یک لیست کانفیگ VLESS و VMess به صورت متن ساده برمی‌گرداند که با کلاینت‌های VPN استاندارد سازگار است.

## تنظیمات nginx

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
    }
}
```

## مدیریت systemd

```bash
sudo systemctl status ghostgate
sudo systemctl restart ghostgate
sudo systemctl stop ghostgate
sudo journalctl -u ghostgate -f
```

## دستورات CLI

خروجی CLI با استفاده از کتابخانه [rich](https://github.com/Textualize/rich) رنگ‌آمیزی شده و با تم پنل هماهنگ است.

| دستور | توضیح |
|---|---|
| `ghostgate` | اجرای سرویس (حالت معمول) |
| `ghostgate --version` | نمایش نسخه و خروج |
| `ghostgate --generate-path` | تولید مسیر تصادفی جدید برای پنل و خروج |
| `ghostgate help` | نمایش راهنمای CLI و دستورات موجود |
| `ghostgate status` | نمایش وضعیت سیستم (CPU، RAM، دیسک، آپتایم) |
| `ghostgate list [--search X]` | لیست تمام اشتراک‌ها، با فیلتر جستجوی اختیاری |
| `ghostgate stats <آیدی\|کامنت>` | نمایش آمار ترافیک یک اشتراک |
| `ghostgate create --comment X [--data GB] [--days N] [--ip N] [--nodes 1,2\|all\|none]` | ایجاد اشتراک جدید |
| `ghostgate edit <آیدی\|کامنت> [--data GB] [--days N] [--remove-data GB] [--remove-days N] [--no-expire] [--comment X] [--ip N] [--enable] [--disable]` | ویرایش اشتراک موجود |
| `ghostgate regen <آیدی\|کامنت>` | بازسازی nanoid اشتراک (لینک قدیمی از کار می‌افتد) |
| `ghostgate delete <آیدی\|کامنت>` | حذف اشتراک و حذف کلاینت‌های آن از تمام نودها |
| `ghostgate nodes` | لیست تمام نودهای تنظیم‌شده |
| `ghostgate addnode --name X --addr http://host:port --user X --pass X --inbound N [--proxy http://...] [--multiplier N]` | افزودن نود |
| `ghostgate editnode <id> [--name X] [--addr X] [--user X] [--pass X] [--proxy X] [--enable] [--disable]` | ویرایش یا فعال/غیرفعال کردن نود (فعال/غیرفعال‌سازی کلاینت‌ها را حذف/بازسازی می‌کند) |
| `ghostgate delnode <id>` | حذف نود |
| `ghostgate subnodes [node_id]` | لیست ساب‌نودها |
| `ghostgate addsubnode --node N --inbound N [--name X] [--multiplier N]` | افزودن ساب‌نود |
| `ghostgate editsubnode <id> [--name X] [--inbound N] [--multiplier N] [--enable] [--disable] [--move-up] [--move-down]` | ویرایش ساب‌نود؛ تغییر multiplier مصرف قبلی را با نرخ قدیم نگه می‌دارد |
| `ghostgate delsubnode <id>` | حذف ساب‌نود |
| `ghostgate configs <آیدی\|کامنت>` | نمایش کانفیگ‌های هر نود برای یک اشتراک |
| `ghostgate bot [--enable\|--disable]` | نمایش یا تغییر وضعیت ربات تلگرام |
| `ghostgate update` | بررسی به‌روزرسانی و اعمال آن در صورت وجود |

**مثال‌ها:**

```bash
ghostgate list
ghostgate list --search علی
ghostgate stats abc123
ghostgate create --comment "علی رضایی" --data 50 --days 30 --ip 2 --nodes 1,2
ghostgate edit abc123 --data 100 --days 60
ghostgate edit abc123 --remove-data 5 --remove-days 7
ghostgate edit abc123 --disable
ghostgate regen abc123
ghostgate delete abc123
ghostgate nodes
ghostgate editnode 1 --disable
ghostgate editnode 1 --enable
ghostgate status
ghostgate update
ghostgate --version
ghostgate --generate-path
```

## بیلد از سورس

```bash
pip install -r requirements.txt pyinstaller
./build/build.sh
```

یا با Docker (توصیه شده برای سازگاری GLIBC با Ubuntu 22.04):

```bash
./build/build-docker.sh
```

فایل باینری در پوشه `dist/` ایجاد می‌شود.

## کانال تلگرام

برای دریافت به‌روزرسانی‌ها و اطلاعیه‌ها به کانال تلگرام بپیوندید: [@GhostSoftDev](https://t.me/GhostSoftDev)

## مجوز

MIT License - جزئیات در فایل LICENSE
