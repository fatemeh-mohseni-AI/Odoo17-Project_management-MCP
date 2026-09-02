# MCP مدیریت پروژه Odoo 17

این پروژه یک MCP Server برای اتصال Codex به اپ رسمی **Project** در Odoo 17 است. ارتباط با Odoo از
API رسمی XML-RPC انجام می‌شود، به ماژول سفارشی نیاز ندارد و با Odoo نصب‌شده روی Docker سازگار است.

## قابلیت‌های اصلی

- نمایش فقط پروژه‌هایی که ID آن‌ها در `ODOO_ALLOWED_PROJECT_IDS` قرار دارد
- لیست، ساخت و ویرایش پروژه با Feature Flag جداگانه
- مشاهدهٔ برد پروژه و ستون‌هایی مانند Backlog و In Progress
- ساخت، ویرایش، جابه‌جایی، آرشیو و حذف تسک
- تعیین Developer، توضیحات، تخمین زمانی، Deadline، Priority، Tag و Milestone
- ساخت Subtask و تعریف وابستگی/Blocked By
- تغییر مستقل ستون Kanban و State داخلی تسک
- ثبت Comment در Chatter
- گزارش سادهٔ Workload براساس تعداد تسک و ساعت تخمینی
- ثبت و ویرایش Timesheet در صورت فعال بودن قابلیت رسمی Timesheets اودو

هیچ ابزار عمومی برای انتخاب دلخواه model، method یا domain اودو وجود ندارد؛ بنابراین AI نمی‌تواند
از این MCP برای دسترسی آزاد به بخش‌های دیگر ERP استفاده کند.

## شروع سریع — روش پیشنهادی Docker

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
```

داخل `.env` اطلاعات اودو و ID پروژه‌های مجاز را وارد کنید:

```dotenv
ODOO_URL=http://odoo:8069
ODOO_DB=company
ODOO_USERNAME=ai-project-service@example.com
ODOO_API_KEY=your-odoo-api-key
ODOO_ALLOWED_PROJECT_IDS=12,34
ODOO_ALLOWED_ASSIGNEE_USER_IDS=7,19
```

نام Docker network اودو را پیدا کنید، سپس image را بسازید:

```bash
docker inspect <odoo-container-name> \
  --format '{{range $name, $network := .NetworkSettings.Networks}}{{$name}} {{end}}'
export ODOO_DOCKER_NETWORK=odoo_default
docker compose build
```

برای بررسی اتصال و پیدا کردن IDهای پروژه و کاربران:

```bash
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp check
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp discover-projects
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp discover-users
```

پس از قرار دادن IDهای مجاز در `.env`، اجرای دستی سرور Dockerized با فرمان زیر ممکن است:

```bash
docker compose run --rm -T odoo-project-mcp
```

این فرمان خروجی عادی چاپ نمی‌کند و منتظر ارتباط MCP روی stdin می‌ماند. روش شمارهٔ ۱ Docker و روش
شمارهٔ ۲ نصب مستقیم Python/`uv`، همراه با تنظیم کامل Codex، در
[راهنمای نصب](docs/INSTALLATION.md) آمده است.

## نکات امنیتی مهم

- ساخت پروژه و حذف دائمی به‌صورت پیش‌فرض خاموش‌اند.
- برای حذف دائمی هم Feature Flag و هم عبارت تأیید دقیق همان رکورد لازم است.
- بهتر است به‌جای حذف، از Archive استفاده شود.
- اکانت Odoo باید یک Service Account جدا با حداقل دسترسی باشد.
- allowlist داخل MCP مکمل Record Ruleهای Odoo است و جای آن‌ها را نمی‌گیرد.
- Stageهای سراسری یا Stageهای مشترک با پروژهٔ غیرمجاز از طریق MCP ویرایش نمی‌شوند.
- برای اتصال داخل Docker، مقدار `ODOO_URL` معمولاً شبیه `http://odoo:8069` است، نه localhost.

مستندات: [نصب](docs/INSTALLATION.md) · [معماری فنی](docs/TECHNICAL.md) ·
[فهرست ابزارها](docs/TOOLS.md) · [امنیت](docs/SECURITY.md)
