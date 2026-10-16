# YouTube → Facebook Page — Implementation Plan

> สำหรับผู้ลงมือทำ: ทำทีละ checkbox ตามลำดับ อ่านข้อจำกัดร่วมก่อนเขียนโค้ด ห้ามเปิดการเผยแพร่จริงระหว่างทดสอบ ใช้ TDD และ commit ย่อยบน `main`; ไม่สร้าง branch/worktree โดยพลการ

## Goal

สร้างระบบ Python + Django + SQLite ที่ตรวจวิดีโอสาธารณะใหม่ของช่อง YouTube ที่ผู้ใช้ดูแล รับไฟล์ต้นฉบับหรือไฟล์ที่ผู้ใช้ดาวน์โหลดผ่าน YouTube Studio แยกแนวตั้ง/คลิปสี่เหลี่ยมสั้นเพื่ออัปโหลดวิดีโอ และแนวนอนเพื่อโพสต์ชื่อคลิปพร้อมรูปปกบน Facebook Page โดยไม่โพสต์ซ้ำ

## Current context / assumptions

ตรวจ workspace วันที่ 2026-10-16:

- Workspace: `C:/Users/win01/Desktop/Projects/katy404_notify_social` เป็น Git repository ว่าง อยู่บน `main` และยังไม่มี commit ไม่มีโค้ดเดิมให้รักษา
- เครื่องที่ตรวจเป็น Windows/Git Bash มี `uv`; `python --version` ที่รันจริงตอบ `Python 3.11.16` อย่าอ้างอิงเวอร์ชันจากข้อความ environment แทนการตรวจ ใช้ `uv run` หลังสร้าง environment ของโครงการ
- เอกสารนี้เป็น deliverable ของรอบ PLAN เท่านั้น ยังไม่ได้ติดตั้ง dependency, สร้าง Django project, ทดสอบโค้ด, ขอ token หรือโพสต์จริง ตัวอย่าง output ต่อจากนี้คือผลที่คาดหวัง ไม่ใช่ผลที่รันแล้ว
- ผู้ใช้ยืนยัน: ต้นทางเป็นช่องที่ตนเป็นเจ้าของ/ดูแลเท่านั้น; สนใจคลิปสาธารณะใหม่ในแต่ละวัน: แนวตั้ง/Shorts ให้อัปโหลดวิดีโอ ส่วนแนวนอนให้โพสต์แจ้งเตือนชื่อคลิปและรูปปกโดยไม่อัปโหลดวิดีโอ
- ผู้ใช้ยืนยันภายหลัง: ใช้ไฟล์ต้นฉบับ หรือไฟล์ที่ดาวน์โหลดผ่าน YouTube Studio ให้ระบบอัปโหลดต่อ ไม่ทำ downloader อัตโนมัติ ไม่ติดตั้ง `yt-dlp` ไม่ดึง browser cookies
- ผู้ใช้ยืนยัน: ตัดการโพสต์แท็บ Posts/Community ของ YouTube ออกทั้งหมด ไม่ต้องสร้าง draft หรือทำ browser automation ทดแทน
- สมมติสำหรับ v1: Facebook เป็น **Page video ปกติ** ไม่ใช่สัญญาว่าจะอยู่ในแท็บ Reels; ถ้าต้องการ Reels endpoint โดยเฉพาะต้องแยกแผนเพิ่ม
- สมมติสำหรับ v1: ตรวจวันละครั้ง 09:00 Asia/Bangkok; ประมวลผลไฟล์/คิวทุก 5 นาที ปรับเวลาได้ใน scheduler ไม่ต้องแก้ business logic
- รองรับหลายช่อง โดยแต่ละช่องผูกกับหนึ่ง Page; หลายช่องใช้ Page เดียวกันได้ แต่ยังไม่ทำ fan-out หนึ่งช่องไปหลาย Page
- การแจ้งเตือนแนวนอนเป็น photo post บน Facebook Page; Django Admin ยังใช้ติดตาม `waiting_file` และข้อผิดพลาด ไม่รวม LINE/Telegram/email
- ข้อความแนวนอนต้องเป็น `{ชื่อคลิป}\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย` แล้วแนบรูปปกเป็นภาพจริงหนึ่งภาพ ไม่พิมพ์ `{รูปปกคลิปแนวนอน}` เป็นข้อความ ไม่เติม URL/ข้อความเกริ่น/แท็กอื่น และไม่แก้ `#short` เป็น `#shorts`
- กรณีแนวนอนไม่มี original ผู้ดูแลยืนยัน `landscape_confirmed=True` ใน Admin หลังตรวจคลิปจริงหรือข้อมูลใน Studio ได้ ไม่เดาจากรูปปก; จึงโพสต์รูปได้โดยไม่ต้องอัปโหลดไฟล์วิดีโอเข้าแอป
- ชื่อ identifier, model field, environment variable และ column ใช้ภาษาอังกฤษ ข้อความใช้งาน/README ใช้ภาษาไทยได้

## Research findings and implementation boundaries

1. YouTube Data API มีการอ่าน channels, uploads playlist และ video metadata แต่ไม่มี video-file download endpoint ใน API reference ที่ตรวจ ส่วน Community Posts ก็ไม่มี create endpoint ที่อ้างอิงได้ จึงไม่นำมาอยู่ในขอบเขต.[1]
2. Developer Policies หมวด III.E.1 ห้าม API client ดาวน์โหลด/เก็บสำเนา audiovisual content โดยไม่มีการอนุมัติเป็นลายลักษณ์อักษรจาก YouTube การดูแลช่องไม่เท่ากับการอนุมัตินี้ การตัด downloader ออกจาก v1 เป็นการตัดสินใจที่ผู้ใช้ยืนยันแล้ว.[2]
3. YouTube Help รองรับดาวน์โหลดวิดีโอที่ตนเองอัปโหลดผ่าน Studio และ Google Takeout; ไฟล์จาก Studio อาจเป็น 720p หรือ 360p และมีเงื่อนไขที่ทำให้ดาวน์โหลดไม่ได้ จึงควรใช้ไฟล์ต้นฉบับเป็นอันดับแรก.[3]
4. Shorts ปัจจุบันอาจเป็นสี่เหลี่ยมหรือแนวตั้งและยาวได้ถึง 3 นาที มีข้อยกเว้นตามวันอัปโหลด/ประเภทช่อง ห้ามนิยามว่า Shorts = ไม่เกิน 60 วินาที และห้ามใช้ `#shorts`, URL `/shorts/` หรือ thumbnail เป็นหลักฐาน aspect ratio.[4]
5. อ่าน uploads playlist ผ่าน `channels.list(part=contentDetails)`, paginate `playlistItems.list(maxResults=50)` แล้ว batch `videos.list(part=snippet,status,contentDetails,liveStreamingDetails)` ไม่ใช้ `search.list` และไม่ตัดรายการเพียงหน้าแรก.[5][6][7]
6. Page video publishing ใช้ Page access token ของผู้ทำ `CREATE_CONTENT` โดยเอกสารเฉพาะ Video API ระบุ `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`; เอกสาร Posts ทั่วไปมีรายการ permission ต่างออกไป ดังนั้นต้องตรวจ permission ของ app/Graph version จริงผ่าน smoke gate ไม่เพิ่ม permission ตามการคาดเดา.[8][9][10]
7. Facebook รับไฟล์ผ่าน `source` multipart หรือ `file_url` ที่เป็น URL ไฟล์จริง ไม่ใช่ URL watch page ของ YouTube v1 ใช้ multipart streaming จากไฟล์ local และจำกัดขนาดเอง.[9]
8. SQLite เหมาะกับงานเล็กที่มี writer จำกัด ไม่ถือว่า `select_for_update()` ให้ row lock บน SQLite ใช้ worker เดียวและ interprocess file lock; ไม่ถือ transaction ระหว่าง HTTP หรือ ffprobe.[12]

## Architecture / proposed approach

ใช้ Django Admin เป็นหน้าจัดการช่อง, Page, วิดีโอ, การแนบไฟล์ และประวัติงาน โดยเก็บ metadata/สถานะใน `db.sqlite3` และเก็บไฟล์ใน private `media/` ไม่เก็บ binary ในฐานข้อมูล ใช้ management commands สองตัวสำหรับสแกน YouTube รายวันและประมวลผลคิว โดยใช้ SQLite unique constraints ร่วมกับ file lock ป้องกันการทำงานซ้อน ไม่มี Celery, Redis, SPA หรือ public webhook ใน v1 การเผยแพร่ Facebook ต้องได้รับ remote ID แล้วอ่าน object นั้นกลับมาตรวจ ก่อนแยกสถานะว่า remote object ตรวจพบแล้วและก่อนให้ผู้ใช้ตรวจการมองเห็นจริง

### Alternatives considered

- **เลือก:** polling รายวัน + original files + Django Admin: ตรงความถี่ที่ผู้ใช้ระบุ ทำงานในเครื่องได้ ไม่ต้องมี public HTTPS callback
- WebSub: แจ้งเตือนได้เร็ว แต่ต้องมี public callback, renew lease และแยกการแก้ชื่อ/คำอธิบายออกจาก upload event จึงยังไม่จำเป็น
- downloader นอกทางการ: ไม่เลือกตามคำตอบล่าสุดของผู้ใช้และข้อจำกัดด้าน policy

## Global constraints / product rules

- Python `3.13.x`; Django `>=5.2,<5.3`; dependency ที่ resolve จริงต้องเก็บใน `uv.lock` ไม่สมมติ patch version ล่าสุด
- Database เป็น `django.db.backends.sqlite3`; database file ชื่อ `db.sqlite3`; timeout 30 วินาที ใช้ local disk ไม่ใช้ network share
- เวลาใน DB เป็น timezone-aware UTC; แสดงผลด้วย `Asia/Bangkok`
- Page มี `auto_publish=False`, `post_link=False`, `post_video=True`, `post_photo=True` เป็นค่าเริ่มต้น Global `LIVE_PUBLISH=0` เป็นค่าเริ่มต้น
- `process_jobs` เป็น preview โดยค่าเริ่มต้น เผยแพร่ได้เมื่อมี `--publish`, `LIVE_PUBLISH=1`, Page เปิด `auto_publish` และทุกสิทธิ์/ไฟล์ผ่านแล้วเท่านั้น
- ไม่สแกนคลิปย้อนหลังเพื่อโพสต์อัตโนมัติในการเปิดครั้งแรก: baseline snapshot แรกบันทึกสิ่งที่มีอยู่ทั้งหมด แต่ไม่สร้างงาน
- หลัง baseline: video ID ที่พบเป็นสาธารณะใหม่สร้างรายการรอไฟล์ แม้เป็นวิดีโอเก่าที่เพิ่งเปลี่ยนเป็น public; เปลี่ยนชื่อหรือคำอธิบายไม่สร้างงานเพิ่ม
- ตรวจ public status จาก YouTube อีกครั้งก่อน POST แต่ละครั้ง; live, upcoming และ live replay ถูกข้ามใน v1
- API key metadata ที่ใช้ไม่มี aspect ratio ของไฟล์ที่เชื่อถือได้ทั่วไป: ตรวจจาก original ด้วย ffprobe หรือให้เจ้าของยืนยันว่าเป็นแนวนอนใน Admin; ถ้ายังไม่รู้ให้รอไฟล์/ยืนยัน ไม่ใช้สัดส่วน thumbnail ตัดสิน orientation
- Eligibility เชิงบรรณาธิการ: `display_height > display_width` **หรือ** `display_height == display_width and duration <= 180` ไม่อ้างว่าเป็น Shorts classification อย่างเป็นทางการ
- รับ MP4/H.264 และ audio AAC หรือไม่มี audio เท่านั้น; duration มากกว่า 0 ถึง 1800 วินาที; ขนาดไม่เกิน `250 * 1024 * 1024` bytes นี่คือเพดานของแอป ไม่ใช่เพดานของ Facebook
- ไม่ transcode, crop, ตัดเสียง หรือดัดแปลงคลิปอัตโนมัติ หาก format ไม่รองรับให้ผู้ใช้ส่งไฟล์ใหม่
- ผู้แนบไฟล์ต้องยืนยัน `rights_confirmed` และ `file_matches_video`; กรณี photo จากการยืนยันแนวนอนต้องยืนยันสิทธิ์ใช้รูปปกผ่าน `rights_confirmed` แต่ไม่ต้องมี original/file_matches_video; การเป็นเจ้าของช่องไม่ได้พิสูจน์สิทธิ์เพลงข้ามแพลตฟอร์ม
- เมื่อรับไฟล์แล้วอัปโหลดซ้ำไปหลายแพลตฟอร์ม ควรใช้ original ที่เก็บไว้ตั้งแต่กระบวนการผลิต ไม่ดาวน์โหลดจาก watch URL
- job identity คือ `(video_id, page_id, kind)` โดย `kind` เป็น `video`, `photo` หรือ `link`; แนวนอนสร้าง `photo` เท่านั้น ไม่มี video upload และไม่มี link post แม้เปิด `post_link`; แนวตั้งสร้าง native video และเพิ่ม link post ได้เฉพาะเมื่อเปิดชัดเจน
- เส้นทางหลัก video/photo ต่อ `(video_id,page_id)` มีได้เพียงหนึ่งแบบ ถ้าเปลี่ยนไฟล์/การยืนยันจน route เปลี่ยนหลังสร้างงาน ให้ `needs_review` ไม่สร้างงานอีกแบบ ไม่เปลี่ยนโพสต์ที่ส่งไปแล้ว
- เลือกรูปปกจาก `snippet.thumbnails` เฉพาะ URL ที่ API คืนมาจริง เรียง maxres→standard→high→medium→default ไม่ประกอบ URL maxres เอง ไม่ครอป/ยืดรูป ถ้าไม่มีรูปให้รอ `waiting_thumbnail` ไม่ fallback เป็นข้อความล้วน.[15]
- Photo post ใช้ `POST /{page-id}/photos` โดยส่ง `url`, `message` ตาม format และ `published=true`; บันทึก `post_id` เป็น remote_id สำหรับอ่าน Page post กลับ ไม่สับสนกับ photo object `id`.[14]
- ไม่รับประกัน exactly-once ระหว่าง SQLite และ Facebook หาก POST กำกวมต้องหยุด `needs_review` ไม่ POST ซ้ำอัตโนมัติ
- API tokens อยู่ใน `.env`/environment ไม่อยู่ใน SQLite, admin forms, log, plan, test artifact หรือ Git
- Graph version pin เป็น `v26.0` ตาม reference ที่ตรวจ ต้องผ่าน live read-only permission gate ก่อนใช้จริง ห้ามเปลี่ยน version อัตโนมัติ.[9]
- รักษา `main`; commit ระบุไฟล์ ไม่ใช้ `git add .`; มี issue จึงใช้ `Refs #N` โดยแทน N ด้วย issue จริง ห้ามประดิษฐ์ issue number และห้ามใช้ auto-close keyword

## File map

```text
pyproject.toml
uv.lock
.gitignore
.env.example
manage.py                         # generated by startproject
config/__init__.py                # generated
config/settings.py                # settings + dotenv + sqlite + private media
config/urls.py                    # /admin/ only
config/asgi.py                    # generated
config/wsgi.py                    # generated
social/apps.py                    # generated
social/models.py                  # Page, Channel, Video, PublishJob
social/admin.py                   # staff UI, no network side effects
social/templates/social/private_file_widget.html # private original input
social/validators.py              # literal ID/env validation
social/media.py                   # ffprobe, eligibility, video/photo routing
social/notifications.py           # exact caption and thumbnail URL selection
social/youtube.py                 # public metadata API only
social/facebook.py                # multipart POST + exact-target GET
social/locking.py                 # one process lock for scan/work/reconcile
social/services.py                # snapshot ingestion, file preparation, dispatch
social/management/commands/scan_channels.py
social/management/commands/process_jobs.py
social/management/commands/reconcile_job.py
social/management/commands/check_integrations.py
social/management/commands/backup_state.py
social/migrations/0001_initial.py  # generated from model code
social/__init__.py
social/management/__init__.py
social/management/commands/__init__.py
social/migrations/__init__.py
scripts/scan.cmd
scripts/process.cmd
README.md
RUNBOOK.md
tests/conftest.py
tests/test_settings.py
tests/test_models.py
tests/test_media.py
tests/test_notifications.py
tests/test_youtube.py
tests/test_discovery.py
tests/test_facebook.py
tests/test_jobs.py
tests/test_commands.py
tests/test_admin.py
tests/test_backup.py
```

## TDD execution convention

ทุก implementation task ด้านล่างมีขั้นย่อยที่ควรใช้ 2–5 นาทีต่อขั้น ไม่พยายามเขียน subsystem ทั้งก้อนในขั้นเดียว:

1. เขียน test ที่ให้ไว้ในไฟล์ที่ระบุ **ก่อน** production code ของ task นั้น
2. รันคำสั่งเฉพาะ test: ต้อง FAIL ด้วย missing behavior/import/assertion ของ task นั้น ถ้า fail เพราะ toolchain/dependency ให้แก้ environment ก่อน ไม่นับเป็น RED
3. เพิ่ม production code เฉพาะ task ใช้บล็อก reference ที่ให้ไว้หรือ scaffold command ที่ระบุ ห้ามใส่ stub คืนค่าตายตัวเพื่อผ่าน test
4. รันคำสั่งเดิมจน PASS แล้วรัน `uv run pytest -q` ก่อน commit; test network ทุกอันใช้ mock ห้ามมีเงินจริง/โพสต์จริง
5. `git add <explicit task files>` และ `git commit -m '<message>'`; output คาดหวังคือ commit บน `[main ...]` โดยไม่มี generated DB/media/token ติดไปด้วย

Reference blocks ในเอกสารนี้คือเนื้อหาเป้าหมายสำหรับการลงมือทำภายหลัง ไม่ใช่ไฟล์ที่สร้างแล้ว ห้ามคัดลอก code ทุก block มาลงก่อน RED ของ task นั้น

## Step-by-step tasks

### Task 01 — Reproducible environment and generated Django scaffold

Files: `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `manage.py`, `config/*`, `social/apps.py`, package `__init__.py` files, `tests/test_settings.py`.

- [ ] สร้าง `pyproject.toml` ตามนี้ แล้วรัน bootstrap commands (เป็น setup exception ก่อน RED แรก):

```toml
[project]
name = "katy404-notify-social"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
  "Django>=5.2,<5.3",
  "requests>=2.32,<3",
  "requests-toolbelt>=1,<2",
  "python-dotenv>=1,<2",
  "filelock>=3.16,<4",
  "waitress>=3,<4",
  "tzdata>=2025.1",
]
[dependency-groups]
dev = [
  "pytest>=8,<10", "pytest-django>=4.9,<5",
  "responses>=0.25,<1", "pytest-socket>=0.7,<1",
]
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["test_*.py"]
addopts = "--disable-socket"
```

```bash
uv python install 3.13
uv sync
uv run django-admin startproject config .
uv run python manage.py startapp social
```

Expected: commands exit 0; `uv run python --version` เป็น `Python 3.13.*`; `uv run python -m django --version` เป็น `5.2.*` และมี `uv.lock` อย่ารัน scaffold ทับหากมีไฟล์แล้ว

- [ ] สร้าง `.gitignore`:

```gitignore
.venv/
.env
*.sqlite3
*.sqlite3-*
media/
backups/
.runtime/
.pytest_cache/
__pycache__/
*.py[cod]
```

- [ ] RED `tests/test_settings.py`:

```python
from django.conf import settings

def test_local_sqlite_and_timezone():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert settings.DATABASES["default"]["OPTIONS"]["timeout"] == 30
    assert settings.TIME_ZONE == "Asia/Bangkok"
    assert "social" in settings.INSTALLED_APPS
    assert settings.MEDIA_ROOT.name == "media"
```

Run: `uv run pytest tests/test_settings.py -q`; expected RED เพราะ timeout/timezone/app ยังเป็น scaffold default

- [ ] GREEN แก้ `config/settings.py`: คง Django settings ที่ generated ไว้; เพิ่ม import และบล็อกต่อไปนี้ท้ายไฟล์ เพื่อ override ค่า default:

```python
import os
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

load_dotenv(BASE_DIR / ".env", override=False)
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "") or "development-only-do-not-deploy"
if not DEBUG and SECRET_KEY == "development-only-do-not-deploy":
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required")
ALLOWED_HOSTS = [x.strip() for x in os.getenv(
    "DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost"
).split(",") if x.strip()]
INSTALLED_APPS = [*INSTALLED_APPS, "social"]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
    "OPTIONS": {"timeout": 30},
}}
TIME_ZONE = "Asia/Bangkok"
USE_TZ = True
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/private-media/"
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
```

`MEDIA_URL` เป็น storage setting เท่านั้น **อย่า**เพิ่ม URL pattern เสิร์ฟ media และอย่าใช้ `static(settings.MEDIA_URL, ...)` คง `/admin/` จาก generated `config/urls.py` ไว้เพียงเส้นทางเดียว

- [ ] `.env.example` ต้องเป็นค่าตัวอย่าง ไม่มี secret จริง:

```dotenv
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
YOUTUBE_API_KEY=
FB_GRAPH_VERSION=v26.0
FB_PAGE_TOKEN_MAIN=
LIVE_PUBLISH=0
FFPROBE_BIN=ffprobe
```

`DJANGO_SECRET_KEY` ว่างหรือไม่ได้ตั้งจะใช้ development sentinel; เมื่อ `DJANGO_DEBUG=0` settings ต้องปฏิเสธ sentinel ตาม code ข้างบน

- [ ] GREEN: `uv run pytest tests/test_settings.py -q` → `1 passed`; `uv run python manage.py check` → `System check identified no issues`.
- [ ] Commit: `chore: bootstrap Django SQLite application` (ระบุ scaffold files, config, tests, dependency files และ `.gitignore` เท่านั้น)

### Task 02 — Validate identifiers without silently repairing them

Files: `social/validators.py`, `tests/test_models.py`.

- [ ] RED:

```python
import pytest
from django.core.exceptions import ValidationError
from social.validators import channel_id_validator, video_id_validator

@pytest.mark.parametrize("value", [" UC" + "a" * 22, "@example", "UCshort"])
def test_channel_ids_are_literal(value):
    with pytest.raises(ValidationError):
        channel_id_validator(value)

def test_identifiers_accept_documented_shape():
    channel_id_validator("UC" + "a" * 22)
    video_id_validator("a" * 11)
```

Run `uv run pytest tests/test_models.py -q` → missing import RED

- [ ] GREEN `social/validators.py`:

```python
from django.core.validators import RegexValidator

channel_id_validator = RegexValidator(r"\AUC[A-Za-z0-9_-]{22}\Z", "Invalid channel ID")
video_id_validator = RegexValidator(r"\A[A-Za-z0-9_-]{11}\Z", "Invalid video ID")
page_id_validator = RegexValidator(r"\A[0-9]+\Z", "Invalid Page ID")
token_env_validator = RegexValidator(r"\AFB_PAGE_TOKEN_[A-Z0-9_]+\Z", "Invalid token environment name")
```

- [ ] Run same command → all PASS; commit `feat: validate literal source identifiers`.

### Task 03 — SQLite persistence and deduplication constraints

Files: `social/models.py`, `social/migrations/0001_initial.py`, append `tests/test_models.py`.

- [ ] RED:

```python
from django.db import IntegrityError, transaction
from social.models import Page, Channel, Video, PublishJob

@pytest.mark.django_db
def test_job_is_unique_per_video_page_kind():
    page = Page.objects.create(page_id="123", name="Test")
    channel = Channel.objects.create(channel_id="UC" + "a" * 22, page=page)
    video = Video.objects.create(video_id="a" * 11, channel=channel)
    PublishJob.objects.create(video=video, page=page, kind="video")
    with pytest.raises(IntegrityError), transaction.atomic():
        PublishJob.objects.create(video=video, page=page, kind="video")
    assert not page.auto_publish
    assert not page.post_link
    assert page.post_photo
```

Run `uv run pytest tests/test_models.py -q` → missing models RED

- [ ] GREEN `social/models.py`:

```python
import uuid
from pathlib import Path
from django.db import models
from .validators import (
    channel_id_validator, video_id_validator, page_id_validator, token_env_validator,
)

def original_path(instance, filename):
    return f"originals/{instance.video_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"

class Page(models.Model):
    page_id = models.CharField(max_length=40, unique=True, validators=[page_id_validator])
    name = models.CharField(max_length=200)
    token_env = models.CharField(max_length=100, default="FB_PAGE_TOKEN_MAIN", validators=[token_env_validator])
    auto_publish = models.BooleanField(default=False)
    post_video = models.BooleanField(default=True)
    post_link = models.BooleanField(default=False)
    post_photo = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Channel(models.Model):
    channel_id = models.CharField(max_length=24, unique=True, validators=[channel_id_validator])
    page = models.ForeignKey(Page, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    ownership_confirmed = models.BooleanField(default=False)
    baseline_at = models.DateTimeField(null=True, blank=True)
    last_scan_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.channel_id

class Video(models.Model):
    video_id = models.CharField(primary_key=True, max_length=11, validators=[video_id_validator])
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT)
    title = models.CharField(max_length=500, blank=True)
    thumbnail_url = models.URLField(max_length=2000, blank=True)
    landscape_confirmed = models.BooleanField(default=False)
    delivery_kind = models.CharField(max_length=10, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    source_checked_at = models.DateTimeField(null=True, blank=True)
    available = models.BooleanField(default=True)
    baseline = models.BooleanField(default=False)
    original = models.FileField(upload_to=original_path, blank=True)
    rights_confirmed = models.BooleanField(default=False)
    file_matches_video = models.BooleanField(default=False)
    state = models.CharField(max_length=30, default="waiting_file")
    checked_name = models.CharField(max_length=500, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    media_error = models.CharField(max_length=100, blank=True)

    @property
    def youtube_url(self):
        return f"https://www.youtube.com/watch?v={self.video_id}"

class PublishJob(models.Model):
    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        PHOTO = "photo", "Landscape thumbnail notification"
        LINK = "link", "Link"
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        VERIFYING = "verifying", "Verifying"
        SUCCEEDED = "succeeded", "Remote object verified"
        NEEDS_REVIEW = "needs_review", "Needs review"
        BLOCKED = "blocked", "Blocked"
        FAILED = "failed", "Failed"
    video = models.ForeignKey(Video, on_delete=models.PROTECT)
    page = models.ForeignKey(Page, on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    remote_id = models.CharField(max_length=100, blank=True)
    remote_url = models.URLField(blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    verify_attempts = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(null=True, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["video", "page", "kind"], name="unique_delivery",
        )]
```

- [ ] `uv run python manage.py makemigrations social` → `Create model Page/Channel/Video/PublishJob` และ constraint; `uv run python manage.py migrate` → migrations `OK`.
- [ ] `uv run pytest tests/test_models.py -q` → PASS; commit `feat: persist sources and unique delivery jobs` ไม่ add `db.sqlite3`.

### Task 04 — Media inspection and explicit editorial rule

Files: `social/media.py`, `tests/test_media.py`.

- [ ] RED tests:

```python
import json
from types import SimpleNamespace
import pytest
from social.media import probe, eligible

@pytest.mark.parametrize("w,h,d,want", [
    (1080,1920,60,True), (1080,1920,600,True),
    (1080,1080,180,True), (1080,1080,181,False),
    (1920,1080,30,False),
])
def test_editorial_filter(w,h,d,want):
    assert eligible(w,h,d) is want

def test_probe_respects_rotation(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"test-fixture-not-real-media")
    payload = {"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"30"},
        "streams":[{"codec_type":"video","codec_name":"h264","width":1920,
            "height":1080,"sample_aspect_ratio":"1:1","side_data_list":[{"rotation":90}]}]}
    monkeypatch.setattr("social.media.subprocess.run", lambda *a, **k:
        SimpleNamespace(stdout=json.dumps(payload), returncode=0))
    assert probe(path) == (1080,1920,30.0)
```

Run `uv run pytest tests/test_media.py -q` → RED

- [ ] GREEN `social/media.py`:

```python
import json
import math
import os
import subprocess
from fractions import Fraction
from pathlib import Path

MAX_BYTES = 250 * 1024 * 1024

def eligible(width: float, height: float, duration: float) -> bool:
    return height > width or (height == width and duration <= 180)

def probe(path: Path) -> tuple[float, float, float]:
    path = Path(path)
    if path.suffix.lower() != ".mp4" or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("invalid_file_size_or_extension")
    try:
        result = subprocess.run([
            os.getenv("FFPROBE_BIN", "ffprobe"), "-v", "error", "-show_streams",
            "-show_format", "-of", "json", str(path.resolve()),
        ], capture_output=True, text=True, check=True, timeout=30, shell=False)
        data = json.loads(result.stdout)
        videos = [s for s in data["streams"] if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic", 0)]
        if len(videos) != 1:
            raise ValueError("invalid_video_stream_count")
        stream = videos[0]
        if stream.get("codec_name") != "h264":
            raise ValueError("unsupported_video_codec")
        if any(s.get("codec_name") != "aac" for s in data["streams"]
               if s.get("codec_type") == "audio"):
            raise ValueError("unsupported_audio_codec")
        if "mp4" not in data["format"].get("format_name", "").split(","):
            raise ValueError("unsupported_container")
        sar = stream.get("sample_aspect_ratio", "1:1")
        sar = Fraction(sar.replace(":", "/"))
        width, height = float(stream["width"] * sar), float(stream["height"])
        rotation = next((int(float(s["rotation"])) for s in stream.get("side_data_list", [])
                         if "rotation" in s), int(float(stream.get("tags", {}).get("rotate", 0))))
        if rotation % 90:
            raise ValueError("unsupported_rotation")
        if rotation % 180:
            width, height = height, width
        duration = float(data["format"]["duration"])
        if not all(math.isfinite(x) and x > 0 for x in (width,height,duration)):
            raise ValueError("invalid_geometry_or_duration")
        if duration > 1800:
            raise ValueError("duration_limit")
        return width,height,duration
    except (KeyError, TypeError, ZeroDivisionError, json.JSONDecodeError,
            subprocess.SubprocessError, OSError) as exc:
        raise ValueError("invalid_media") from exc
```

- [ ] เพิ่ม parameterized RED/PASS cases ใน `tests/test_media.py` สำหรับ missing dimensions, `duration=NaN`, SAR `0:1`, unknown SAR `N/A`, timeout, HEVC, non-AAC, empty file และ 90°/270° rotation ข้อความผิดพลาดต้องเป็น code ไม่ใช่ subprocess stderr หรือ path ที่มีข้อมูลลับ
- [ ] Fix ขั้นนี้: `Fraction("N/A")` และ float conversion จะเกิด `ValueError` อยู่แล้วและถูก caller sanitize; assert แค่ exception class และไม่ log raw exception
- [ ] Run `uv run pytest tests/test_media.py -q` → PASS; commit `feat: inspect private originals before publishing`.

### Task 04A — Exact landscape caption, thumbnail selection, and routing

Files: `social/notifications.py`, append `social/media.py`, `tests/test_notifications.py`, append `tests/test_media.py`.

- [ ] RED `tests/test_notifications.py`:

```python
from social.notifications import landscape_message,choose_thumbnail

def test_landscape_caption_is_exact():
    assert landscape_message("ชื่อคลิปทดสอบ") == (
        "ชื่อคลิปทดสอบ\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"
    )

def test_thumbnail_falls_back_only_to_existing_api_urls():
    high = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
    assert choose_thumbnail({"high":{"url":high}}) == high
    assert choose_thumbnail({}) == ""
    assert choose_thumbnail({"maxres":{"url":"https://evil.example/picture.jpg"},
        "high":{"url":high}}) == high
```

`uv run pytest tests/test_notifications.py -q` → missing module RED.

- [ ] GREEN `social/notifications.py`:

```python
from urllib.parse import urlsplit

LANDSCAPE_TAG_LINE = "tag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"

def landscape_message(title: str) -> str:
    return f"{title}\n{LANDSCAPE_TAG_LINE}"

def valid_thumbnail_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in {"i.ytimg.com","i9.ytimg.com"}
            and not parsed.username and not parsed.password and parsed.port in {None,443})
    except (ValueError,TypeError):
        return False

def choose_thumbnail(thumbnails: dict) -> str:
    for key in ("maxres","standard","high","medium","default"):
        url = thumbnails.get(key,{}).get("url","")
        if url and valid_thumbnail_url(url):
            return url
    return ""
```

- [ ] RED append `tests/test_media.py`:

```python
from social.media import route_for_geometry

@pytest.mark.parametrize("geometry,want",[
    ((1920,1080,30),"photo"), ((1920,1080,600),"photo"),
    ((1080,1920,600),"video"), ((1080,1080,180),"video"),
    ((1080,1080,181),"skip"),
])
def test_geometry_selects_mutually_exclusive_delivery(geometry,want):
    assert route_for_geometry(*geometry) == want
```

- [ ] GREEN append `social/media.py`:

```python
def route_for_geometry(width: float,height: float,duration: float) -> str:
    if width > height:
        return "photo"
    return "video" if eligible(width,height,duration) else "skip"
```

- [ ] `uv run pytest tests/test_media.py tests/test_notifications.py -q` → PASS.
- [ ] Commit `feat: define exact landscape notification format`.

### Task 05 — Read-only YouTube API adapter

Files: `social/youtube.py`, `tests/test_youtube.py`.

- [ ] RED test pagination มากกว่าหนึ่งหน้า:

```python
from social.youtube import YouTube

def test_snapshot_follows_all_pages(monkeypatch):
    api = YouTube("fixture-key")
    channel = "UC" + "a" * 22
    seen = []
    def get(resource, **params):
        seen.append((resource,params))
        if resource == "channels":
            return {"items":[{"id":channel,"contentDetails":{"relatedPlaylists":{"uploads":"playlist"}}}]}
        if resource == "playlistItems":
            vid = "b"*11 if params.get("pageToken") else "a"*11
            result = {"items":[{"contentDetails":{"videoId":vid}}]}
            if not params.get("pageToken"):
                result["nextPageToken"] = "next"
            return result
        return {"items":[{"id":vid,"snippet":{"channelId":channel,"title":vid,
                "liveBroadcastContent":"none"},"status":{"privacyStatus":"public"}}
                for vid in params["id"].split(",")]}
    monkeypatch.setattr(api,"_get",get)
    assert set(api.snapshot(channel)) == {"a"*11,"b"*11}
    assert sum(name == "playlistItems" for name,_ in seen) == 2
```

Run `uv run pytest tests/test_youtube.py -q` → RED

- [ ] GREEN `social/youtube.py`:

```python
import requests
from .validators import channel_id_validator, video_id_validator
from .notifications import choose_thumbnail

class YouTube:
    def __init__(self, key: str):
        if not key:
            raise ValueError("youtube_key_missing")
        self.key = key
        self.session = requests.Session()

    def _get(self, resource: str, **params) -> dict:
        response = self.session.get(
            f"https://www.googleapis.com/youtube/v3/{resource}",
            params={**params,"key":self.key}, timeout=(10,60),
        )
        if response.status_code != 200:
            raise RuntimeError(f"youtube_http_{response.status_code}")
        return response.json()

    def details(self, ids: list[str], channel_id: str) -> dict[str,dict]:
        channel_id_validator(channel_id)
        found = {}
        for start in range(0,len(ids),50):
            batch = ids[start:start+50]
            for vid in batch:
                video_id_validator(vid)
            data = self._get("videos", part="snippet,status,contentDetails,liveStreamingDetails",
                             id=",".join(batch), maxResults=50)
            for item in data.get("items",[]):
                if item["id"] not in batch or item["snippet"]["channelId"] != channel_id:
                    raise ValueError("source_channel_mismatch")
                if item["status"]["privacyStatus"] != "public":
                    continue
                if item["snippet"].get("liveBroadcastContent","none") != "none":
                    continue
                if item.get("liveStreamingDetails"):
                    continue
                found[item["id"]] = {"title":item["snippet"]["title"],
                    "thumbnail_url":choose_thumbnail(item["snippet"].get("thumbnails",{}))}
        return found

    def snapshot(self, channel_id: str) -> dict[str,dict]:
        channel_id_validator(channel_id)
        data = self._get("channels",part="contentDetails",id=channel_id)
        if len(data.get("items",[])) != 1 or data["items"][0]["id"] != channel_id:
            raise ValueError("channel_not_found")
        playlist = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        ids, tokens, token = [], set(), None
        for _ in range(100):
            params = dict(part="contentDetails",playlistId=playlist,maxResults=50)
            if token:
                params["pageToken"] = token
            page = self._get("playlistItems",**params)
            ids.extend(item["contentDetails"]["videoId"] for item in page.get("items",[]))
            token = page.get("nextPageToken")
            if not token:
                return self.details(list(dict.fromkeys(ids)),channel_id)
            if token in tokens:
                raise ValueError("repeated_page_token")
            tokens.add(token)
        raise ValueError("snapshot_page_limit")
```

- [ ] เพิ่ม tests: `privacyStatus=unlisted/private`, live, upcoming, live replay → ไม่คืนรายการ; mismatch → exception; malformed literal ID → ไม่เรียก HTTP; HTTP 403/429/500 → sanitized RuntimeError; repeated token และครบ 100 หน้าแต่ยังมี next → fail ไม่คืน partial snapshot
- [ ] Run `uv run pytest tests/test_youtube.py -q` → PASS; commit `feat: discover public uploads through YouTube API`.

### Task 06 — Atomic baseline and daily ingestion

Files: เริ่ม `social/services.py`, `tests/test_discovery.py`.

- [ ] RED:

```python
from types import SimpleNamespace
import pytest
from django.utils import timezone
from social.models import Page,Channel,Video,PublishJob
from social.services import scan_channel

@pytest.mark.django_db
def test_first_snapshot_is_baseline_next_snapshot_is_new():
    p = Page.objects.create(page_id="123",name="Test")
    c = Channel.objects.create(channel_id="UC"+"a"*22,page=p,enabled=True,ownership_confirmed=True)
    api = SimpleNamespace(snapshot=lambda _: {"a"*11:{"title":"old"}})
    scan_channel(c,api,timezone.now())
    assert Video.objects.get(pk="a"*11).baseline
    api.snapshot = lambda _: {"a"*11:{"title":"edited"},"b"*11:{"title":"new"}}
    scan_channel(c,api,timezone.now())
    assert Video.objects.count() == 2
    assert not Video.objects.get(pk="b"*11).baseline
    assert Video.objects.get(pk="b"*11).state == "waiting_file"
    assert not PublishJob.objects.exists()
```

Run `uv run pytest tests/test_discovery.py -q` → RED

- [ ] GREEN เริ่ม `social/services.py`:

```python
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import Channel,Video,PublishJob
from .media import probe,eligible,route_for_geometry
from .notifications import landscape_message,valid_thumbnail_url

def scan_channel(channel, api, now):
    if not channel.enabled or not channel.ownership_confirmed:
        return
    snapshot = api.snapshot(channel.channel_id)  # All network before transaction.
    with transaction.atomic():
        fresh = Channel.objects.get(pk=channel.pk)
        baseline = fresh.baseline_at is None
        Video.objects.filter(channel=fresh).exclude(pk__in=snapshot).update(
            available=False,title="",thumbnail_url="",source_checked_at=now,
        )
        for vid, metadata in snapshot.items():
            video, created = Video.objects.get_or_create(video_id=vid,defaults={
                "channel":fresh,"baseline":baseline,
                "state":"baseline" if baseline else "waiting_file",
            })
            if video.channel_id != fresh.pk:
                raise ValueError("duplicate_id_different_channel")
            video.title = metadata["title"]
            video.thumbnail_url = metadata.get("thumbnail_url", "")
            video.available = True
            video.source_checked_at = now
            video.save(update_fields=["title","thumbnail_url","available","source_checked_at"])
        if baseline:
            fresh.baseline_at = now
        fresh.last_scan_at = now
        fresh.save(update_fields=["baseline_at","last_scan_at"])
```

- [ ] เพิ่ม tests: snapshot throws → baseline/last_scan ไม่เปลี่ยน; rename → ไม่สร้าง Video ใหม่; unavailable → title ว่าง; กลับเป็น public → ใช้ record เดิม; baseline ไม่ถูกนำไปโพสต์; ช่อง disabled/unconfirmed → ไม่เรียก api
- [ ] Run same test command → PASS; commit `feat: baseline channels without replaying old uploads`.

### Task 07 — Prepare originals and enqueue enabled delivery kinds

Files: เพิ่ม `social/services.py`, `tests/test_jobs.py`, `tests/conftest.py`.

- [ ] สร้าง shared fixture `tests/conftest.py`:

```python
from types import SimpleNamespace
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from social.models import Page,Channel,Video,PublishJob

@pytest.fixture
def bundle(db,settings,tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    p = Page.objects.create(page_id="123",name="Test",auto_publish=True)
    c = Channel.objects.create(channel_id="UC"+"a"*22,page=p,enabled=True,ownership_confirmed=True)
    v = Video.objects.create(video_id="a"*11,channel=c,title="clip",
        rights_confirmed=True,file_matches_video=True)
    v.original.save("original.mp4",SimpleUploadedFile("original.mp4",b"fixture"))
    return SimpleNamespace(page=p,channel=c,video=v)
```

- [ ] RED `tests/test_jobs.py`:

```python
from social.models import PublishJob
from social.services import prepare_video

def test_prepare_is_idempotent_and_does_not_make_link_by_default(bundle,monkeypatch):
    monkeypatch.setattr("social.services.probe",lambda _: (1080,1920,30))
    prepare_video(bundle.video)
    prepare_video(bundle.video)
    assert list(PublishJob.objects.values_list("kind",flat=True)) == ["video"]
```

Run `uv run pytest tests/test_jobs.py -q` → RED

- [ ] GREEN เพิ่ม `social/services.py`:

```python
def prepare_video(video):
    if video.baseline or not video.available:
        return
    route = ""
    if not video.original and not video.landscape_confirmed:
        video.state = "waiting_file"
    elif not video.rights_confirmed:
        video.state = "waiting_rights"
    elif video.landscape_confirmed:
        route = "photo"
        video.media_error = ""
    elif not video.file_matches_video:
        video.state = "waiting_rights"
    else:
        if video.checked_name != video.original.name:
            try:
                route = route_for_geometry(*probe(video.original.path))
                video.media_error = "not_supported_geometry" if route == "skip" else ""
                video.delivery_kind = route if route != "skip" else ""
            except (ValueError,OSError):
                video.media_error = "invalid_or_unsupported_media"
                video.delivery_kind = ""
            video.checked_name = video.original.name
        else:
            route = video.delivery_kind
        if video.media_error or not route:
            video.state = "rejected"
            route = ""
    page = video.channel.page
    if route:
        incompatible = PublishJob.objects.filter(video=video,page=page,
            kind__in=["video","photo"]).exclude(kind=route).exists()
        if incompatible:
            video.state,video.media_error = "needs_review","delivery_route_changed"
            route = ""
        else:
            video.delivery_kind = route
            video.state = "ready_photo" if route == "photo" else "ready"
            if route == "photo" and not valid_thumbnail_url(video.thumbnail_url):
                video.state = "waiting_thumbnail"
    video.prepared_at = timezone.now()
    video.save(update_fields=["state","delivery_kind","media_error","checked_name","prepared_at"])
    if video.state not in {"ready","ready_photo"}:
        return
    PublishJob.objects.filter(video=video,state="blocked",remote_id="",
        error_code="media_recheck_failed").update(state="pending",error_code="")
    kinds = [("photo",page.post_photo)] if route == "photo" else [
        ("video",page.post_video),("link",page.post_link)]
    for kind,enabled in kinds:
        if enabled:
            PublishJob.objects.get_or_create(video=video,page=page,kind=kind)
```

- [ ] เพิ่ม tests: ไม่มีไฟล์และไม่ได้ยืนยันแนวนอน, rights false, original file_matches false → jobs เป็นศูนย์; landscape ที่ตรวจผ่าน → photo อย่างเดียว; explicit post_link=True สำหรับแนวตั้ง → video/link อย่างละหนึ่ง แต่แนวนอนยัง photo เดียว; same file rejected ไม่ probe ซ้ำ; file replacement name ใหม่ probe ใหม่; baseline ไม่สร้างงาน
- [ ] Run `uv run pytest tests/test_jobs.py -q` → PASS; commit `feat: queue approved eligible originals exactly once`.

### Task 07A — Landscape photo-only acceptance tests

Files: append `tests/test_jobs.py`, `tests/test_facebook.py`; production changes belong to Tasks07–09 reference code.

- [ ] เขียน tests ต่อไปนี้ก่อนเพิ่ม branch `photo` ใน production code; ระหว่างรอ Task08–09 ให้รันเฉพาะ prepare test ก่อน แล้วรัน dispatch/adapter tests หลังถึง task นั้น อย่าเขียน production ทั้งหมดก่อน RED

Append `tests/test_jobs.py`:

```python
def test_confirmed_landscape_queues_photo_without_original(bundle,monkeypatch):
    bundle.video.original.delete(save=True)
    bundle.video.landscape_confirmed = True
    bundle.video.thumbnail_url = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
    bundle.video.save()
    bundle.page.post_link = True
    bundle.page.save()
    monkeypatch.setattr("social.services.probe",lambda *a: pytest.fail("no video file needed"))
    prepare_video(bundle.video)
    prepare_video(bundle.video)
    assert list(PublishJob.objects.values_list("kind",flat=True)) == ["photo"]
    bundle.video.refresh_from_db()
    assert bundle.video.state == "ready_photo"

def test_landscape_dispatch_sends_exact_photo_and_never_video(bundle,monkeypatch):
    from types import SimpleNamespace
    from django.utils import timezone
    from social.services import dispatch_job
    bundle.video.original.delete(save=True)
    bundle.video.landscape_confirmed = True
    bundle.video.thumbnail_url = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
    bundle.video.title = "ชื่อคลิป"
    bundle.video.save()
    prepare_video(bundle.video)
    sent = []
    def photo(message,url):
        sent.append((message,url))
        return "123_456"
    fb = SimpleNamespace(publish_photo=photo,
        publish_video=lambda *a: pytest.fail("must not upload landscape video"),
        publish_link=lambda *a: pytest.fail("must not create another link post"))
    yt = SimpleNamespace(details=lambda *a: {bundle.video.pk:{"title":"ชื่อคลิป",
        "thumbnail_url":bundle.video.thumbnail_url}})
    monkeypatch.setattr("social.services.probe",lambda *a: pytest.fail("orientation already confirmed"))
    job = PublishJob.objects.get()
    dispatch_job(job,yt,fb,timezone.now())
    job.refresh_from_db()
    dispatch_job(job,yt,fb,timezone.now())
    assert sent == [("ชื่อคลิป\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย",
        bundle.video.thumbnail_url)]
    assert job.remote_id == "123_456" and job.state == "verifying"
```

เพิ่ม `import pytest` ต้น `tests/test_jobs.py` (ยังไม่มี import นี้ใน Task07 เดิม)

Append `tests/test_facebook.py`:

```python
import json

@responses.activate
def test_photo_uses_page_post_id_and_exact_payload():
    api = Facebook("123","fixture-token","v26.0")
    image = "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"
    message = "ชื่อคลิป\ntag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย"
    responses.post("https://graph.facebook.com/v26.0/123/photos",
        json={"id":"456","post_id":"123_456"})
    assert api.publish_photo(message,image) == "123_456"
    assert json.loads(responses.calls[0].request.body) == {
        "message":message,"url":image,"published":True}
    assert len(responses.calls) == 1
```

- [ ] RED/PASS preparation: `uv run pytest tests/test_jobs.py -k confirmed_landscape -q`
- [ ] RED/PASS dispatch: `uv run pytest tests/test_jobs.py -k landscape_dispatch -q`
- [ ] RED/PASS adapter: `uv run pytest tests/test_facebook.py -k photo_uses -q`
- [ ] เพิ่ม regression tests: missing thumbnail→waiting_thumbnail,ไม่มีPOST; thumbnailหายก่อนส่ง→pending,ไม่มีPOST; public→privateก่อนส่ง→ไม่มีphoto; landscape/photo timeout→needs_reviewไม่resend; ชื่อเปลี่ยนก่อนส่งใช้ชื่อล่าสุดแต่ไม่เปลี่ยนแท็ก; แก้ route หลัง queued→needs_review ไม่สร้างงานอีกชนิด
- [ ] Commit `test: enforce landscape photo notifications without video uploads` หลัง reference implementation ของแต่ละส่วนผ่านแล้ว

### Task 08 — Facebook adapter with streaming multipart and exact-target readback

Files: `social/facebook.py`, `tests/test_facebook.py`.

- [ ] RED:

```python
import responses
from social.facebook import Facebook

@responses.activate
def test_link_fields_are_explicit_and_readback_uses_remote_id():
    api = Facebook("123","fixture-token","v26.0")
    responses.post("https://graph.facebook.com/v26.0/123/feed",json={"id":"123_456"})
    responses.get("https://graph.facebook.com/v26.0/123_456",json={
        "id":"123_456","from":{"id":"123"},"permalink_url":"https://www.facebook.com/123_456"})
    rid = api.publish_link("clip","https://www.youtube.com/watch?v="+"a"*11)
    result = api.verify(rid,"link")
    assert rid == "123_456"
    assert result is not None
    assert b'"published": true' in responses.calls[0].request.body
    assert responses.calls[0].request.headers["Authorization"] == "Bearer fixture-token"
```

Run `uv run pytest tests/test_facebook.py -q` → RED

- [ ] GREEN `social/facebook.py`:

```python
from pathlib import Path
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
from .validators import page_id_validator
from .notifications import valid_thumbnail_url

class Facebook:
    def __init__(self,page_id: str,token: str,version: str="v26.0"):
        page_id_validator(page_id)
        if not token or version != "v26.0":
            raise ValueError("facebook_configuration")
        self.page_id,self.version = page_id,version
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _json(self,response):
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"facebook_http_{response.status_code}")
        data = response.json()
        if "error" in data:
            raise RuntimeError("facebook_api_error")
        return data

    def publish_link(self,message: str,url: str) -> str:
        result = self._json(self.session.post(
            f"https://graph.facebook.com/{self.version}/{self.page_id}/feed",
            json={"message":message,"link":url,"published":True},
            timeout=(10,60),
        ))
        return str(result["id"])

    def publish_photo(self,message: str,thumbnail_url: str) -> str:
        if not valid_thumbnail_url(thumbnail_url):
            raise ValueError("invalid_thumbnail_url")
        result = self._json(self.session.post(
            f"https://graph.facebook.com/{self.version}/{self.page_id}/photos",
            json={"message":message,"url":thumbnail_url,"published":True},
            timeout=(10,60),
        ))
        # post_id is the Page post; result['id'] is the Photo object.
        return str(result["post_id"])

    def publish_video(self,path: Path,title: str,description: str) -> str:
        with Path(path).open("rb") as source:
            body = MultipartEncoder(fields={
                "source":("original.mp4",source,"video/mp4"),
                "title":title,"description":description,
                "published":"true","secret":"false","no_story":"false",
                "reference_only":"false",
            })
            result = self._json(self.session.post(
                f"https://graph-video.facebook.com/{self.version}/{self.page_id}/videos",
                data=body,headers={"Content-Type":body.content_type},timeout=(10,600),
            ))
        return str(result["id"])

    def verify(self,remote_id: str,kind: str) -> str | None:
        if not remote_id or not all(c in "0123456789_" for c in remote_id):
            raise ValueError("invalid_remote_id")
        fields = "id,from,source" if kind == "video" else "id,from,permalink_url"
        data = self._json(self.session.get(
            f"https://graph.facebook.com/{self.version}/{remote_id}",
            params={"fields":fields},timeout=(10,60),
        ))
        if str(data.get("id")) != remote_id or str(data.get("from",{}).get("id")) != self.page_id:
            raise ValueError("remote_owner_mismatch")
        if kind == "video":
            return f"https://www.facebook.com/watch/?v={remote_id}" if data.get("source") else None
        return data.get("permalink_url") or None
```

**Readback semantics:** Video reference ที่อ่านได้ระบุ `id`, `from`, `source` จึงใช้ fields เหล่านี้ ไม่เดา `status.video_status` จากบทความอื่น; `source` ไม่ว่างเป็นเพียงหลักฐานว่า remote video object มีไฟล์ที่อ่านได้ ไม่ใช่หลักฐานว่าบุคคลทั่วไปทุกคนดูได้ ต้องผ่าน manual visibility gate ใน Task 20 และอย่าเก็บ signed `source` URL ลง DB/log.[11][13]

- [ ] ปรับ test body ให้รองรับ bytes/str: `body = responses.calls[0].request.body; body = body.encode() if isinstance(body,str) else body` ก่อน assert; เป็น representation difference ไม่เปลี่ยน contract
- [ ] เพิ่ม video multipart test: monkeypatch `api.session.post` เก็บ `data.fields` แล้วคืน response dummy; assert `source[1]` เป็น file object ไม่ใช่ bytes, file ถูก close หลัง POST, `published/secret/no_story/reference_only` มีค่าตามข้างบน
- [ ] เพิ่ม readback tests: ID ไม่ตรง/owner ไม่ตรง → fail; video `source` ว่าง → None; HTTP 403/429/500 → sanitized error; remote id containing `/` → ไม่เรียก HTTP
- [ ] Run same command → PASS; commit `feat: publish Facebook Page content with verified object IDs`.

### Task 09 — Safe dispatch and ambiguous POST behavior

Files: เพิ่ม `social/services.py`, append `tests/test_jobs.py`.

- [ ] RED:

```python
from types import SimpleNamespace
from django.utils import timezone
from social.services import dispatch_job

def test_ambiguous_post_never_reposts(bundle,monkeypatch):
    monkeypatch.setattr("social.services.probe",lambda _: (1080,1920,30))
    prepare_video(bundle.video)
    job = PublishJob.objects.get()
    calls = []
    def send(*args):
        calls.append(args)
        raise TimeoutError("must not leak this text")
    fb = SimpleNamespace(publish_video=send)
    yt = SimpleNamespace(details=lambda *a: {bundle.video.pk:{"title":"clip"}})
    dispatch_job(job,yt,fb,timezone.now())
    job.refresh_from_db()
    assert job.state == "needs_review"
    dispatch_job(job,yt,fb,timezone.now())
    assert len(calls) == 1
    assert "must not leak" not in job.error_code
```

Run `uv run pytest tests/test_jobs.py -q` → RED

- [ ] GREEN เพิ่ม `social/services.py`:

```python
def dispatch_job(job,yt,fb,now):
    if job.state != "pending" or job.remote_id:
        return
    video = job.video
    page = job.page
    if not (page.auto_publish and video.channel.enabled and video.channel.ownership_confirmed):
        return
    if not video.rights_confirmed:
        return
    if job.kind != "photo" and not (video.file_matches_video and video.original):
        return
    if ((job.kind == "video" and not page.post_video)
        or (job.kind == "link" and not page.post_link)
        or (job.kind == "photo" and not page.post_photo)):
        return
    if video.channel.page_id != page.pk or video.baseline:
        return
    try:
        current = yt.details([video.pk],video.channel.channel_id)
    except Exception:
        job.error_code = "source_check_failed"
        job.save(update_fields=["error_code","updated_at"])
        return
    if video.pk not in current:
        video.available = False
        video.title = ""
        video.thumbnail_url = ""
        video.source_checked_at = now
        video.save(update_fields=["available","title","thumbnail_url","source_checked_at"])
        job.error_code = "source_not_public"
        job.save(update_fields=["error_code","updated_at"])
        return
    # A photo notification must never enter the video upload path.
    try:
        if video.landscape_confirmed:
            route = "photo"
        else:
            if not video.original or not video.file_matches_video:
                raise ValueError("orientation_unconfirmed")
            route = route_for_geometry(*probe(video.original.path))
        expected_route = "video" if job.kind == "link" else job.kind
        if route != expected_route:
            raise ValueError("route_changed")
    except (ValueError,OSError):
        job.state,job.error_code = "blocked","media_recheck_failed"
        job.save(update_fields=["state","error_code","updated_at"])
        return
    video.title = current[video.pk]["title"]
    video.thumbnail_url = current[video.pk].get("thumbnail_url", "")
    video.available = True
    video.source_checked_at = now
    video.save(update_fields=["title","thumbnail_url","available","source_checked_at"])
    if job.kind == "photo" and not valid_thumbnail_url(video.thumbnail_url):
        job.error_code = "thumbnail_unavailable"
        job.save(update_fields=["error_code","updated_at"])
        return
    changed = PublishJob.objects.filter(pk=job.pk,state="pending",remote_id="").update(state="sending")
    if not changed:
        return
    try:
        description = f"{video.title}\n{video.youtube_url}"
        if job.kind == "video":
            remote_id = fb.publish_video(video.original.path,video.title,description)
        elif job.kind == "photo":
            remote_id = fb.publish_photo(landscape_message(video.title),video.thumbnail_url)
        else:
            remote_id = fb.publish_link(video.title,video.youtube_url)
        if not remote_id or not all(c in "0123456789_" for c in remote_id):
            raise ValueError("invalid_remote_id")
    except Exception:
        PublishJob.objects.filter(pk=job.pk).update(state="needs_review",error_code="post_outcome_unknown")
        return
    # If this database write fails, persistent 'sending' is recovered to needs_review.
    PublishJob.objects.filter(pk=job.pk).update(
        remote_id=remote_id,state="verifying",error_code="",retry_at=now,
    )
```

**Boundary:** adapter exceptions during POST—including HTTP 5xx/429 returned after submit—are deliberately treated as unknown outcomes, not safe retries. A more clever retry policy is out of scope until provider idempotency is proven for the endpoint.

- [ ] เพิ่ม tests: source unavailable/private → 0 POST; source GET exception → pending; file removed/วิดีโอ job เปลี่ยนเป็นแนวนอน → blocked,0 POST; photo job ที่ยืนยันแนวนอนต้องไม่เรียก video uploader; auto_publish false →0 POST; disabled source →0 POST; succeeded/verifying/remote_id present →0 POST; same job stale object twice → second conditional update prevents POST
- [ ] Run same command → PASS; commit `feat: stop ambiguous publishes instead of duplicating posts`.

### Task 10 — Readback-only retry with bounded backoff

Files: เพิ่ม `social/services.py`, append `tests/test_jobs.py`.

- [ ] RED:

```python
from datetime import timedelta
from social.services import verify_job

def test_pending_processing_retries_get_only(bundle):
    now = timezone.now()
    job = PublishJob.objects.create(video=bundle.video,page=bundle.page,kind="video",
        state="verifying",remote_id="456")
    api = SimpleNamespace(verify=lambda *a: None)
    verify_job(job,api,now)
    job.refresh_from_db()
    assert job.state == "verifying"
    assert job.retry_at == now + timedelta(seconds=60)
    api.verify = lambda *a: "https://www.facebook.com/watch/?v=456"
    verify_job(job,api,job.retry_at)
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert job.remote_id == "456"
```

Run `uv run pytest tests/test_jobs.py -q` → RED

- [ ] GREEN เพิ่ม `social/services.py`:

```python
VERIFY_DELAYS = (60,300,900,3600,21600)

def verify_job(job,fb,now):
    if job.state != "verifying" or not job.remote_id or (job.retry_at and job.retry_at > now):
        return
    try:
        url = fb.verify(job.remote_id,job.kind)
    except Exception:
        url = None
    if url:
        job.state,job.remote_url,job.error_code = "succeeded",url,""
        job.retry_at = None
    elif job.verify_attempts >= len(VERIFY_DELAYS):
        job.state,job.error_code = "needs_review","verification_exhausted"
        job.retry_at = None
    else:
        job.retry_at = now + timedelta(seconds=VERIFY_DELAYS[job.verify_attempts])
        job.verify_attempts += 1
        job.error_code = "verification_pending"
    job.save(update_fields=["state","remote_url","error_code","retry_at","verify_attempts","updated_at"])
```

- [ ] เพิ่ม tests: before retry_at → GET 0 ครั้ง; missing ID → ไม่ทำงาน; exhausted → needs_review; ID/owner mismatch → ไม่ succeed; verify error → ไม่เรียก publish method
- [ ] Run same command → PASS; commit `feat: verify published objects without repeating writes`.

### Task 11 — Interprocess lock without SQLite row-lock assumptions

Files: `social/locking.py`, `tests/test_commands.py`.

- [ ] RED:

```python
import pytest
from filelock import Timeout
from social.locking import worker_lock

def test_second_worker_cannot_enter(settings,tmp_path):
    settings.BASE_DIR = tmp_path
    with worker_lock():
        with pytest.raises(Timeout):
            with worker_lock():
                pass
```

Run `uv run pytest tests/test_commands.py -q` → RED

- [ ] GREEN `social/locking.py`:

```python
from django.conf import settings
from filelock import FileLock

def worker_lock():
    directory = settings.BASE_DIR / ".runtime"
    directory.mkdir(parents=True,exist_ok=True)
    return FileLock(str(directory / "social.lock"),timeout=0)
```

- [ ] Test creates **two FileLock instances** as above (same-instance recursive behavior would not prove contention); Run same command → PASS; commit `feat: serialize local integration workers`.

### Task 12 — Daily scan management command

Files: `social/management/__init__.py`, `social/management/commands/__init__.py`, `social/management/commands/scan_channels.py`, append `tests/test_commands.py`.

- [ ] RED:

```python
from io import StringIO
from django.core.management import call_command

def test_daily_scan_can_skip_already_scanned_channel(bundle,monkeypatch,tmp_path,settings):
    from django.utils import timezone
    settings.BASE_DIR = tmp_path
    bundle.channel.last_scan_at = timezone.now()
    bundle.channel.save()
    monkeypatch.setenv("YOUTUBE_API_KEY","fixture")
    monkeypatch.setattr("social.youtube.YouTube.snapshot",lambda *a:
        pytest.fail("must skip same-day scan"))
    out = StringIO()
    call_command("scan_channels",stdout=out)
    assert "scan_complete" in out.getvalue()
```

Run `uv run pytest tests/test_commands.py -q` → RED

- [ ] GREEN command file:

```python
import os
from filelock import Timeout
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone
from social.locking import worker_lock
from social.models import Channel
from social.services import scan_channel
from social.youtube import YouTube

class Command(BaseCommand):
    def add_arguments(self,parser):
        parser.add_argument("--force",action="store_true")

    def handle(self,*args,**options):
        failures = 0
        try:
            with worker_lock():
                api = YouTube(os.getenv("YOUTUBE_API_KEY",""))
                now = timezone.now()
                for channel in Channel.objects.filter(enabled=True,ownership_confirmed=True):
                    if not options["force"] and channel.last_scan_at and (
                        timezone.localdate(channel.last_scan_at) == timezone.localdate(now)
                    ):
                        continue
                    try:
                        scan_channel(channel,api,now)
                    except Exception:
                        failures += 1
                        self.stderr.write(f"scan_failed channel={channel.pk}")
        except Timeout:
            self.stdout.write("worker_busy")
            return
        except ValueError as exc:
            raise CommandError("youtube_configuration") from exc
        if failures:
            raise CommandError(f"scan_failed_count={failures}")
        self.stdout.write("scan_complete")
```

- [ ] เพิ่ม tests: force bypass daily skip; failure channel แรกไม่ขวางช่องถัดไป แต่ exit nonzero; `worker_busy` ไม่เรียก API; incomplete baseline ไม่ stamp วัน
- [ ] Run same command → PASS; commit `feat: schedule complete daily channel snapshots`.

### Task 13 — Preview-first worker command and crash recovery

Files: `social/management/commands/process_jobs.py`, append `tests/test_commands.py`.

- [ ] RED preview test:

```python
def test_preview_does_not_change_database_or_post(bundle,monkeypatch,tmp_path,settings):
    from social.models import PublishJob,Video
    settings.BASE_DIR = tmp_path
    before = list(Video.objects.values())
    out = StringIO()
    call_command("process_jobs",stdout=out)
    assert "preview" in out.getvalue()
    assert list(Video.objects.values()) == before
    assert PublishJob.objects.count() == 0
```

Run `uv run pytest tests/test_commands.py -q` → RED

- [ ] GREEN command:

```python
import os
from filelock import Timeout
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone
from django.db.models import F
from social.facebook import Facebook
from social.locking import worker_lock
from social.models import Video,PublishJob
from social.services import prepare_video,dispatch_job,verify_job
from social.youtube import YouTube

class Command(BaseCommand):
    def add_arguments(self,parser):
        parser.add_argument("--publish",action="store_true")
        parser.add_argument("--limit",type=int,default=10)

    def handle(self,*args,**options):
        if not options["publish"]:
            self.stdout.write(f"preview videos={Video.objects.filter(baseline=False).count()} jobs={PublishJob.objects.count()}")
            return
        if os.getenv("LIVE_PUBLISH","0") != "1":
            raise CommandError("live_publish_disabled")
        if not 1 <= options["limit"] <= 100:
            raise CommandError("limit_must_be_1_to_100")
        try:
            with worker_lock():
                now = timezone.now()
                PublishJob.objects.filter(state="sending",remote_id="").update(
                    state="needs_review",error_code="worker_interrupted_during_post")
                PublishJob.objects.filter(state="sending").exclude(remote_id="").update(
                    state="verifying",retry_at=now)
                yt = YouTube(os.getenv("YOUTUBE_API_KEY",""))
                videos = Video.objects.filter(baseline=False,available=True,
                    channel__enabled=True,channel__ownership_confirmed=True).select_related(
                    "channel__page").order_by(F("prepared_at").asc(nulls_first=True),"first_seen_at")
                for video in videos[:100]:
                    prepare_video(video)
                jobs = PublishJob.objects.filter(state__in=["pending","verifying"]).select_related(
                    "page","video__channel__page").order_by(
                    F("attempted_at").asc(nulls_first=True),"created_at")
                processed = 0
                for job in jobs:
                    if job.state == "pending" and not job.page.auto_publish:
                        continue
                    if job.state == "verifying" and job.retry_at and job.retry_at > now:
                        continue
                    token = os.getenv(job.page.token_env,"")
                    if not token:
                        job.error_code = "page_token_missing"
                        job.save(update_fields=["error_code","updated_at"])
                        continue
                    fb = Facebook(job.page.page_id,token,os.getenv("FB_GRAPH_VERSION","v26.0"))
                    PublishJob.objects.filter(pk=job.pk).update(attempted_at=now)
                    if job.state == "verifying":
                        verify_job(job,fb,now)
                    else:
                        dispatch_job(job,yt,fb,now)
                    processed += 1
                    if processed >= options["limit"]:
                        break
                self.stdout.write(f"processed={processed}")
        except Timeout:
            self.stdout.write("worker_busy")
```

- [ ] เพิ่ม RED fairness regression ก่อนเพิ่ม ordering ของ code ข้างบน: job pending source private ที่เก่าที่สุดและ `--limit=1` ต้องไม่บัง valid job ตลอดไป ใช้ `attempted_at` ที่สร้างไว้ตั้งแต่ Task03 ให้ worker ครั้งที่สองเลือก job ที่ยังไม่เคยลองก่อน ทดสอบ 2 รอบแล้ว valid job ต้องถูก dispatch
- [ ] เพิ่ม RED crash recovery regression ก่อนเพิ่ม recovery queries ข้างบน: `sending` ที่มี remote_id → `verifying`; ที่ไม่มี remote_id → `needs_review`; ทั้งคู่ห้าม POST ซ้ำ
- [ ] เพิ่ม RED preparation bounds regression ก่อนเพิ่ม bounded queryset ข้างบน: สร้าง101 video; worker รอบแรก prepare100รายการ รอบถัดไปต้องมีรายการที่101; `prepared_at` ทำให้หมุนเวียนทั่วคลัง ส่วน `checked_name` กัน ffprobe ซ้ำเมื่อไฟล์ไม่เปลี่ยน ready video ยังถูกทบทวน flags เพื่อสร้าง missing link/video job ได้
- [ ] Tests: `LIVE_PUBLISH=0` + --publish → CommandError ก่อน DB mutation; default preview → ไม่เปลี่ยน state/ไม่สร้าง directory lock/ไม่ network; missing token → ไม่ POST; `limit=0` → fail; lock busy →0 POST; interrupted state → no duplicate
- [ ] Run `uv run pytest tests/test_commands.py tests/test_jobs.py -q` → PASS; commit `feat: run gated publishing queue with safe recovery`.

### Task 14 — Staff-only Admin with immutable delivery records

Files: `social/admin.py`, `tests/test_admin.py`.

- [ ] RED:

```python
import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_admin_requires_login(client):
    response = client.get(reverse("admin:social_video_changelist"))
    assert response.status_code == 302
    assert "/admin/login/" in response.url

def test_media_is_not_publicly_served(client):
    assert client.get("/private-media/originals/anything.mp4").status_code == 404
```

Run `uv run pytest tests/test_admin.py -q` → video admin route missing RED

- [ ] GREEN `social/admin.py`:

```python
from django import forms
from django.contrib import admin
from .models import Page,Channel,Video,PublishJob
from .media import MAX_BYTES

class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = "__all__"
    def clean_original(self):
        original = self.cleaned_data.get("original")
        if original and (original.size > MAX_BYTES or not original.name.lower().endswith(".mp4")):
            raise forms.ValidationError("Use an MP4 file within the configured size limit")
        return original
    def clean(self):
        data = super().clean()
        changed = {"original","landscape_confirmed"} & set(self.changed_data)
        if self.instance.pk and changed and self.instance.publishjob_set.exclude(
            state__in=["pending","blocked"]).exists():
            raise forms.ValidationError("Delivery already started; resolve its existing job before editing media")
        return data

@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("name","page_id","auto_publish","post_video","post_photo","post_link","token_env")
    def get_readonly_fields(self,request,obj=None):
        return ("page_id",) if obj else ()

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("channel_id","page","enabled","ownership_confirmed","baseline_at","last_scan_at")
    readonly_fields = ("baseline_at","last_scan_at")
    def get_readonly_fields(self,request,obj=None):
        return self.readonly_fields + (("channel_id","page") if obj and obj.baseline_at else ())

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    form = VideoForm
    list_display = ("video_id","title","channel","state","available","first_seen_at")
    list_filter = ("state","available","baseline","channel")
    search_fields = ("video_id","title")
    readonly_fields = ("video_id","channel","title","first_seen_at","source_checked_at", "available",
        "baseline","state","checked_name","prepared_at","media_error","delivery_kind","thumbnail_url","youtube_url")
    def has_add_permission(self,request):
        return False
    def has_delete_permission(self,request,obj=None):
        return False

@admin.register(PublishJob)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id","video","page","kind","state","remote_id","error_code","updated_at")
    list_filter = ("state","kind","page")
    search_fields = ("video__video_id","remote_id")
    readonly_fields = tuple(f.name for f in PublishJob._meta.fields)
    def has_add_permission(self,request):
        return False
    def has_delete_permission(self,request,obj=None):
        return False
```

- [ ] Add RED token/path leak test: admin video change HTML ต้องไม่มี signed remote source URL/token และไม่มี clickable direct download URL ไป `/private-media/`; minimal GREEN: custom `ClearableFileInput` ใน VideoForm ใช้ template `social/templates/social/private_file_widget.html`:

```html
{% if widget.value %}<p>Private original attached. Upload a replacement only before delivery starts.</p>{% endif %}
<input type="file" name="{{ widget.name }}"{% include "django/forms/widgets/attrs.html" %}>
```

เพิ่ม `class PrivateFileInput(forms.ClearableFileInput): template_name = "social/private_file_widget.html"` และ `Meta.widgets = {"original": PrivateFileInput()}`; ปิด clear checkbox เพื่อไม่ลบไฟล์ระหว่าง job; ไม่ expose `original.path` ใน UI

- [ ] Add tests: nonstaff denied; oversized uploaded form rejected; filename suffix invalid rejected; readonly job no POST action; channel source identity immutable หลัง baseline; editing original หลัง job started fail แต่ยกเลิก rights/file-match confirmation ได้เสมอและ pending dispatch ต้องหยุด; upload ไม่ POST ไป Facebook; CSRF middleware อยู่ใน settings
- [ ] `uv run pytest tests/test_admin.py -q` → PASS; commit `feat: manage private originals through authenticated Django Admin`.

### Task 15 — Reconcile ambiguous writes by remote ID, never resend

Files: `social/management/commands/reconcile_job.py`, append `tests/test_commands.py`.

- [ ] RED:

```python
def test_reconcile_never_publishes_again(bundle,monkeypatch,tmp_path,settings):
    from social.models import PublishJob
    settings.BASE_DIR = tmp_path
    job = PublishJob.objects.create(video=bundle.video,page=bundle.page,kind="video",state="needs_review")
    monkeypatch.setenv(bundle.page.token_env,"fixture")
    monkeypatch.setattr("social.facebook.Facebook.verify",lambda *a: "https://www.facebook.com/watch/?v=456")
    monkeypatch.setattr("social.facebook.Facebook.publish_video",lambda *a: pytest.fail("must not POST"))
    call_command("reconcile_job",str(job.pk),"--remote-id","456")
    job.refresh_from_db()
    assert job.remote_id == "456" and job.state == "succeeded"
```

Run `uv run pytest tests/test_commands.py -q` → RED

- [ ] GREEN command:

```python
import os
from django.core.management.base import BaseCommand,CommandError
from social.facebook import Facebook
from social.locking import worker_lock
from social.models import PublishJob

class Command(BaseCommand):
    def add_arguments(self,parser):
        parser.add_argument("job_id",type=int)
        parser.add_argument("--remote-id",required=True)
    def handle(self,*args,**options):
        with worker_lock():
            job = PublishJob.objects.select_related("page").get(pk=options["job_id"])
            if job.state not in {"needs_review","verifying"}:
                raise CommandError("job_not_reconcilable")
            remote_id = options["remote_id"]
            if job.remote_id and job.remote_id != remote_id:
                raise CommandError("remote_id_is_immutable")
            api = Facebook(job.page.page_id,os.getenv(job.page.token_env,""),os.getenv("FB_GRAPH_VERSION","v26.0"))
            url = api.verify(remote_id,job.kind)
            if not url:
                raise CommandError("remote_not_ready")
            job.remote_id,job.remote_url,job.state = remote_id,url,"succeeded"
            job.error_code,job.retry_at = "",None
            job.save(update_fields=["remote_id","remote_url","state","error_code","retry_at","updated_at"])
        self.stdout.write("reconciled_without_publish")
```

Reconciliation ตรวจ owner/ID ผ่าน adapter แต่ไม่อาจพิสูจน์ว่าเลือกคลิปถูกอันจาก ID อย่างเดียว RUNBOOK ต้องให้คนดูเนื้อหาก่อนระบุ remote ID: video/link ตรวจ YouTube URL ใน caption; photo ตรวจรูปปก ชื่อคลิป และบรรทัดแท็กตรงตัวอย่าง โดยไม่บังคับเติม YouTube URL ลงโพสต์รูป ห้ามเขียนว่าโปรแกรมตรวจ content equality ได้

- [ ] เพิ่ม tests wrong page/readback failure → ไม่แก้ job; remote id เดิมมีแล้วเปลี่ยนไม่ได้; blocked/succeeded ไม่ reconcile
- [ ] Run same command → PASS; commit `feat: reconcile uncertain deliveries without resending`.

### Task 16 — Read-only integration preflight

Files: `social/management/commands/check_integrations.py`, append `tests/test_commands.py`.

- [ ] RED test mock HTTP adapter ยืนยัน command ใช้ GET เท่านั้นและไม่เผย token:

```python
def test_preflight_never_publishes(bundle,monkeypatch):
    import requests
    monkeypatch.setenv("YOUTUBE_API_KEY","fixture")
    monkeypatch.setenv(bundle.page.token_env,"fixture-token")
    seen = []
    def get(self,url,**kwargs):
        seen.append(url)
        class Response:
            status_code = 200
            def json(self):
                return {"items":[{"id":bundle.channel.channel_id}]} if "googleapis" in url else {"id":"123"}
        return Response()
    monkeypatch.setattr(requests.Session,"get",get)
    out = StringIO()
    call_command("check_integrations",stdout=out)
    assert "preflight_ok" in out.getvalue()
    assert "fixture-token" not in out.getvalue()
    assert len(seen) == 2
```

- [ ] GREEN command: ไม่โหลด video file, ไม่สร้างงาน, GET YouTube `channels?part=id&id=<channel-id>` และ GET Facebook `/<page-id>?fields=id,name`; assert exact requested IDs และ status200; ไม่มี auto token refresh และไม่มี POST:

```python
import os
from django.core.management.base import BaseCommand,CommandError
from social.facebook import Facebook
from social.models import Channel,Page
from social.youtube import YouTube
from social.validators import channel_id_validator

class Command(BaseCommand):
    def handle(self,*args,**options):
        try:
            yt = YouTube(os.getenv("YOUTUBE_API_KEY",""))
            for channel in Channel.objects.filter(enabled=True,ownership_confirmed=True):
                channel_id_validator(channel.channel_id)
                data = yt._get("channels",part="id",id=channel.channel_id)
                if [x["id"] for x in data.get("items",[])] != [channel.channel_id]:
                    raise ValueError("source_mismatch")
            for page in Page.objects.all():
                fb = Facebook(page.page_id,os.getenv(page.token_env,""),os.getenv("FB_GRAPH_VERSION","v26.0"))
                data = fb._json(fb.session.get(
                    f"https://graph.facebook.com/{fb.version}/{page.page_id}",
                    params={"fields":"id,name"},timeout=(10,60)))
                if str(data.get("id")) != page.page_id:
                    raise ValueError("page_mismatch")
        except Exception as exc:
            raise CommandError("preflight_failed_check_credentials_and_permissions") from None
        self.stdout.write("preflight_ok")
```

- [ ] เพิ่ม tests malformed configured ID → fail ก่อน HTTP, missing token/API key → sanitized error, 403 → no publish/no DB mutation
- [ ] Run `uv run pytest tests/test_commands.py -q` → PASS; commit `feat: check integration identity without external writes`.

### Task 17 — Consistent SQLite + private file backup

Files: `social/management/commands/backup_state.py`, `tests/test_backup.py`.

- [ ] RED `tests/test_backup.py` ใช้ SQLite file จริงใน temporary test directory ไม่ใช่ in-memory DB:

```python
import sqlite3
import pytest
from social.management.commands.backup_state import backup_database

def test_sqlite_backup_contains_rows_and_does_not_overwrite(tmp_path):
    source,destination = tmp_path/"source.sqlite3",tmp_path/"backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample (value) VALUES (?)",("kept",))
    backup_database(source,destination)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == [("kept",)]
    with pytest.raises(ValueError):
        backup_database(source,destination)
```

Run `uv run pytest tests/test_backup.py -q` → missing command/helper RED
- [ ] GREEN helper และ command ในไฟล์เดียว:

```python
import shutil
import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from social.locking import worker_lock

def backup_database(source: Path,destination: Path):
    if destination.exists() or not source.is_file():
        raise ValueError("invalid_backup_path")
    with sqlite3.connect(source.as_uri()+"?mode=ro",uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)

class Command(BaseCommand):
    def add_arguments(self,parser):
        parser.add_argument("--output",required=True)
    def handle(self,*args,**options):
        destination = Path(options["output"]).resolve()
        root = settings.BASE_DIR.resolve()
        media = settings.MEDIA_ROOT.resolve()
        if destination == root or destination == media or media in destination.parents or destination in root.parents:
            raise CommandError("invalid_backup_directory")
        with worker_lock():
            destination.mkdir(parents=True,exist_ok=False)
            backup_database(Path(settings.DATABASES["default"]["NAME"]).resolve(),destination/"db.sqlite3")
            if media.exists():
                shutil.copytree(media,destination/"media")
        self.stdout.write("backup_complete")
```

ก่อน command นี้ ต้องหยุด web process และ scheduled tasks ให้หมด: lock ครอบ worker แต่ไม่ได้ครอบ Admin upload ไม่อ้างว่าเป็น consistent DB+media snapshot ถ้า web ยังเขียนอยู่ `sqlite3.backup()` ใช้เพื่อ consistency ของฐานข้อมูล ไม่ใช้การ copy `.sqlite3` ที่กำลังเขียน

- [ ] `uv run pytest tests/test_backup.py -q` → PASS; commit `feat: back up SQLite and originals during maintenance`.

### Task 18 — Windows scheduling and local serving

Files: `scripts/scan.cmd`, `scripts/process.cmd`, `README.md`, `RUNBOOK.md`, append `tests/test_commands.py`.

- [ ] RED append `tests/test_commands.py`:

```python
from pathlib import Path

@pytest.mark.parametrize("name",["scan","process"])
def test_windows_wrappers_use_project_python(name):
    text = (Path(__file__).resolve().parents[1]/"scripts"/f"{name}.cmd").read_text()
    assert 'cd /d "%~dp0.."' in text
    assert r".venv\Scripts\python.exe" in text
    assert "exit /b %errorlevel%" in text
```

Run `uv run pytest tests/test_commands.py -k windows_wrappers -q` → FileNotFoundError RED
- [ ] GREEN `scripts/scan.cmd`:

```bat
@echo off
cd /d "%~dp0.."
if not exist .runtime mkdir .runtime
.venv\Scripts\python.exe manage.py scan_channels >> .runtime\scan.log 2>&1
exit /b %errorlevel%
```

` scripts/process.cmd` (ชื่อไฟล์จริงไม่มี space นำหน้า):

```bat
@echo off
cd /d "%~dp0.."
if not exist .runtime mkdir .runtime
.venv\Scripts\python.exe manage.py process_jobs --publish --limit 10 >> .runtime\process.log 2>&1
exit /b %errorlevel%
```

- [ ] README ต้องมี commands ที่ copy ได้จาก Git Bash:

```bash
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 127.0.0.1:8000
```

Local persistent server:

```bash
uv run waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

ใช้ `runserver` เพื่อ dev เท่านั้น ไม่เปิดรับ network ภายนอก; ถ้าจะ deploy ให้เพิ่ม HTTPS reverse proxy, secure cookies, CSRF trusted origins และ `check --deploy` เป็นแผน deployment แยก อย่าให้ implementer เดาระบบ hosting

- [ ] README ระบุ FFmpeg/ffprobe prerequisite ให้ติดตั้งจากแหล่งที่ผู้ใช้เชื่อถือเอง ตั้ง `FFPROBE_BIN` ถ้าไม่อยู่ใน PATH ห้าม command ดาวน์โหลด executable จาก URL ที่ไม่ตรวจสอบ
- [ ] Task Scheduler GUI instructions ที่ต้องเขียนใน RUNBOOK:
  - Task `Katy404 Scan`: daily 09:00 ตาม Windows timezone Asia/Bangkok/SE Asia Standard Time; program `C:\Windows\System32\cmd.exe`; argument `/c "C:\Users\win01\Desktop\Projects\katy404_notify_social\scripts\scan.cmd"`; Start in project path
  - Task `Katy404 Process`: every 5 minutes, indefinite; program เดิม; argument เปลี่ยนเป็น `process.cmd`
  - ทั้งคู่เลือก “Do not start a new instance”, “Run task as soon as possible after a scheduled start is missed”; ไม่ hard-kill worker ระหว่าง upload; shared file lock จัดการเวลาที่สอง task ชนกัน
  - ยังไม่สร้าง/enable scheduled tasks จนผ่าน Task 20 และผู้ใช้อนุญาต external publishing ชัดเจน
  - `worker_busy` เป็นการ skip อย่างปลอดภัย; ตรวจ log ถ้า busy ติดกันหลายรอบ
- [ ] Run `uv run pytest tests/test_commands.py -q` → PASS; commit `docs: describe local operation and safe Windows scheduling`.

### Task 19 — End-to-end offline acceptance and security regression tests

Files: เพิ่ม `tests/test_discovery.py`, `tests/test_jobs.py`, `tests/test_admin.py`, `RUNBOOK.md`.

- [ ] RED end-to-end test mock YouTube snapshot และ Facebook adapter:
  1. snapshot A → baseline,0 jobs
  2. snapshot A+B → B waiting_file,0 POST
  3. แนบ original B และยืนยันสิทธิ์ → one video job
  4. source check B public + dispatch → remote_id,verifying
  5. readback owner/id/source ผ่าน → succeeded
  6. scan/worker ซ้ำอีก 2 รอบ → POST count ยังเท่ากับ1
- [ ] RED second case: landscape B → ready_photo,photo job1รายการ,video upload0ครั้ง; square181sec → rejected; vertical600sec → video; square180sec → video; ยังไม่รู้แนวคลิป →รอ ไม่เดาจาก thumbnail
- [ ] RED third case: POST timeout → needs_review → restart → POST countยัง1; ถ้า remote ID บันทึกแล้วแต่ readback timeout ให้ GET retryเท่านั้น
- [ ] RED privacy case: public ตอนสแกนแต่ private ก่อน dispatch →0 POST; deleted → purge cached title; changed title → updated existing Video แต่ไม่สร้าง new job
- [ ] RED retention case: source_checked_at เกิน30วันและ scan ล้มเหลวต่อเนื่อง → clear source title ก่อนมีการแสดง/ใช้งาน โดยเพิ่ม helper `purge_stale_source_metadata(now)` ใน `social/services.py`:

```python
def purge_stale_source_metadata(now):
    Video.objects.filter(source_checked_at__lt=now-timedelta(days=30)).update(
        title="",thumbnail_url="",available=False)
```

เรียก helper ใน `scan_channels` ภายใน lock ก่อน network scan และใน live `process_jobs` ก่อน preparation; preview ห้ามเรียก helper เพราะต้องไม่มี DB writes Source metadata ที่หาไม่พบถูกล้างทันทีตั้งแต่ Task06; video ID/job identity เป็น tombstone สำหรับ dedupe ไม่เก็บ description/thumb ที่ไม่ได้ใช้ การรับรอง policy compliance ครบทุกข้อยังต้องทบทวน privacy notice/ข้อมูลที่เก็บจริงก่อนเปิดสาธารณะ.[2]

- [ ] GREEN ทำเฉพาะ code ที่ทำให้ acceptance tests ผ่าน ไม่เพิ่ม feature ใหม่
- [ ] รัน:

```bash
uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py process_jobs
 git diff --check
 git status --short
```

Expected: pytest ทั้งหมด PASS ภายใต้ `--disable-socket`; check ไม่มี issue; migration check `No changes detected`; process_jobs แสดง `preview ...`; diff check ไม่มี output; git status มีเฉพาะไฟล์งานที่คาดหวัง ไม่มี `.env`, `db.sqlite3`, `media/` หรือ log

- [ ] Commit `test: verify complete offline publishing lifecycle`.

### Task 20 — Explicitly approved live smoke gate (not part of offline tests)

Files: บันทึกผลที่ตัดข้อมูลลับใน `RUNBOOK.md`; ห้ามเพิ่ม token หรือ raw API responses

ขั้นนี้มี external side effect ต้องให้ผู้ใช้อนุญาตเผยแพร่คลิปทดสอบจริงหนึ่งคลิปบน Page ที่ระบุก่อนเสมอ ไม่รวม permission request/app registration/token generation ในคำสั่งอัตโนมัติของผู้ลงมือทำ

- [ ] ผู้ใช้เตรียม Google project เปิด YouTube Data API และ restricted API key สำหรับ read-only public metadata; ยืนยัน Channel ID ที่ดูแล
- [ ] ผู้ใช้เตรียม Meta app/Page access token ตาม permissions ของ endpoint และสิทธิ์ Page จริง เก็บใน `.env` ไม่ส่ง token ผ่าน chat; App Review/Business Verification อาจเป็น prerequisite ตาม app/access level ต้องรายงาน blocker ไม่บอกว่าเสร็จโดยยังไม่มีสิทธิ์.[8][9]
- [ ] `uv run python manage.py check_integrations` → `preflight_ok`; ขั้นนี้พิสูจน์ตัวตน read access เท่านั้น ไม่พิสูจน์ publish permission
- [ ] สร้าง Channel ใน Admin: ownership_confirmed=True,enabled=True; Page auto_publish=False; `uv run python manage.py scan_channels --force` → `scan_complete`; ต้องมี baseline และ0 delivery jobs
- [ ] ผู้ใช้อัปโหลดคลิปทดสอบสาธารณะใหม่ที่ตนมีสิทธิ์ข้ามแพลตฟอร์ม; scan --force อีกครั้ง → waiting_file; แนบ original ที่ตรงกัน, rights_confirmed=True,file_matches_video=True
- [ ] ตรวจ `ffprobe -version` → exit0; preview `uv run python manage.py process_jobs` → ไม่มี POST/DB mutation
- [ ] หลังอนุมัติหนึ่งคลิปจริง: ตั้ง `LIVE_PUBLISH=1`, เปิด Page auto_publish=True, ให้มีเพียงคลิปทดสอบที่พร้อมหนึ่งรายการ แล้วรัน:

```bash
uv run python manage.py process_jobs --publish --limit 1
uv run python manage.py process_jobs --publish --limit 1
```

Expected: รอบแรก job pending→verifying พร้อม remote_id; รอบที่สอง readback→succeeded หรือยัง verifying ถ้า Facebook ยัง processing; ห้ามรายงาน succeed จาก HTTP POST เพียงอย่างเดียว

- [ ] เปิด exact remote URL ใน Facebook โดยผู้ใช้ ตรวจ Page owner, วิดีโอ, caption, เสียง และการมองเห็นจากมุมมองสาธารณะ บันทึก remote_id + URL + วันที่ตรวจ + ผลตรวจ visibility โดยไม่เก็บ signed source URL
- [ ] รัน worker รอบที่สาม → ไม่มีโพสต์เพิ่ม เปิด Page ตรวจว่ามีวิดีโอทดสอบเพียงหนึ่งชิ้น
- [ ] ทดสอบแนวนอนเพิ่มอีกหนึ่งคลิปเมื่อได้รับอนุมัติ: landscape_confirmed=True,rights_confirmed=True โดยไม่แนบ original → photo post1รายการ,video upload0ครั้ง; exact caption/title/tags ตรงตัวอย่างและมีรูปปกจริง ตรวจ post_id + readback + visibility แล้วรันซ้ำต้องไม่โพสต์เพิ่ม
- [ ] หากต้องการ link post สำหรับแนวตั้งให้ทดสอบแยก โดยเปิด post_link อย่างชัดเจนและรับทราบว่าจะมีสองโพสต์ต่อคลิป ไม่เปิดโดยปริยาย; แนวนอนห้ามสร้าง link post เพิ่ม
- [ ] ตั้ง LIVE_PUBLISH=0 และ auto_publish=False หลัง smoke จนผู้ใช้ยืนยันเปิดงานประจำวัน; เมื่ออนุมัติจึงเปิด scheduler ตาม Task18
- [ ] Commit `docs: record redacted live verification outcome` เฉพาะเมื่อมีผลจริง หากติด permission/API processing ให้บันทึก blocker ไม่เติมผลตัวอย่าง

## Additional validation details implementer must not skip

### FFprobe real-file integration (read-only on an operator-provided original)

คำสั่งต้องใช้ไฟล์จริงที่ผู้ใช้อนุญาต ไม่สร้างตัวเลขอ้างว่า inspect แล้ว:

```bash
uv run python -c 'from pathlib import Path; from social.media import probe,eligible; p=Path(input("Original MP4 path: ")); geometry=probe(p); print(geometry, eligible(*geometry))'
```

Expected: ขนาด display หลัง rotation ตรงกับเครื่องเล่นจริงและ eligibility ตาม rule; ถ้าไม่มี ffprobe ให้รายงาน prerequisite ห้าม fake tuple เป็นผลจริง

### Database/media operational behavior

- SQLite unique constraint กัน job ซ้ำแม้ caller เรียก prepare ซ้ำ; file lock กัน commands พร้อมกัน; conditional state update กัน stale job object ภายในรอบ
- หลีกเลี่ยง long transaction; network/ffprobe นอก transaction; อย่าแก้ปัญหา locked DB ด้วยการเพิ่ม worker หรือใช้ `select_for_update()` บน SQLite
- ลบ original MP4 หลัง Facebook exact-object readback ยืนยัน `succeeded` สำหรับ video job และทุก configured delivery job ของ `(video_id,page_id)` สำเร็จแล้วเท่านั้น; HTTP POST/unknown outcome ไม่ลบ; photo-only ไม่ลบไฟล์; link job ที่ยัง pending ป้องกัน deletion; หาก cleanup ล้มเหลวเก็บ DB reference และ retry รอบ worker ถัดไป
- การลบหลัง verified เป็น irreversible; ผู้ใช้สำรองต้นฉบับก่อนเผยแพร่หากต้องเก็บ archive; อย่าลบไฟล์ของ pending/blocked/needs_review job
- Django เก็บไฟล์ใหม่แล้วเปลี่ยน original ไม่ได้ลบไฟล์เก่าเอง README ต้องบอกว่าอาจมี orphan files; ไม่เติม delete signal ที่ทำให้ irreversible deletion ใน transaction
- ไม่แก้ content Facebook เมื่อแก้ title ใน YouTube หลังเผยแพร่ ไม่ลบโพสต์เดิมอัตโนมัติเมื่อคลิปถูกตั้ง private; ถ้าต้องการ synchronization แบบนั้นต้องออกแบบ consent และ delete behavior แยก
- หากมี dispatch worker run นานจนพลาด scan เวลา09:00 ให้ rerun scan ด้วย `--force` หรือเปิด Task Scheduler missed-run behavior; มี daily full rescan จึงไม่ตัด catch-up ด้วยหน้าต่าง yesterday-only

### Backup/restore acceptance

หยุด web server และ scheduled tasks ก่อน จากนั้นใน Git Bash:

```bash
uv run python manage.py backup_state --output 'C:/Users/win01/Desktop/Projects/katy404_notify_social/backups/acceptance-snapshot'
```

Expected: `backup_complete` และ directory ใหม่ที่มี db.sqlite3 + media; ถ้ามี directory เดิม command ต้องปฏิเสธ ไม่ overwrite

ทดสอบ restore บน workspace สำเนาแยกที่ตั้ง `LIVE_PUBLISH=0` และไม่มี scheduled task ก่อนคัดลอก backup; `uv run python manage.py check` และ Admin ต้องแสดง source/job IDs เดิมกับไฟล์แนบที่เปิดตรวจได้ ห้ามทดลอง restore ทับ active DB ของผู้ใช้

## Review focus / acceptance checklist

- [ ] เปลี่ยน title หรือรัน scheduler ซ้ำ ไม่ทำให้เกิด POST ใหม่
- [ ] คลิป private/unlisted/live/upcoming/replay ไม่ถูกเผยแพร่ แม้เคย public ตอนสแกน
- [ ] ถ้ายังไม่มี original และยังไม่ยืนยันแนวนอน ให้รออย่างตรงไปตรงมา; ถ้ายืนยันแนวนอนแล้วสามารถ photo post จาก metadata ได้ ไม่ต้องแนบไฟล์วิดีโอ
- [ ] แนวนอนใช้ captionชื่อคลิป + บรรทัดแท็กตรงตัวอักษร มีรูปปกจริง ไม่เพิ่ม URL ไม่อัปโหลดวิดีโอ ไม่สร้างโพสต์ซ้ำ
- [ ] rotation/SAR/NaN/file-too-large/file-removed ไม่ทำให้คลิปผิดประเภทหลุดไปเผยแพร่
- [ ] POST timeout หรือ crash ตรง remote/local boundary ไม่ทำให้ upload ซ้ำ; คน reconcile โดย exact ID
- [ ] GET success อย่างเดียวไม่ถูกสรุปว่าคนทั่วไปดูได้; ต้องมี manual visibility evidence ของ live smoke
- [ ] preview ไม่เปลี่ยน DB, ไม่ acquire/create lock file, ไม่ส่ง HTTP write; offline tests ไม่ออก network
- [ ] baseline snapshot ต้อง complete ก่อน mark initialized และก่อนนำ source ไปใช้
- [ ] user consent คือ channel ownership + rights/file match + Page auto_publish + global publish gate ไม่ใช่ checkbox ที่ default เปิดเอง
- [ ] ผู้ใช้ได้รับ README/RUNBOOK ที่ทำซ้ำได้ และไม่มี secret/file binary อยู่ใน Git

## Risks, tradeoffs, and open questions

1. **ยังมี manual file handoff/confirmation:** แนวตั้งใช้ original ตามที่เลือก; แนวนอนใช้ original เพื่อวัดสัดส่วนหรือผู้ดูแลยืนยันแนวนอนโดยไม่ส่งไฟล์วิดีโอ ระบบจึงยังไม่ครบอัตโนมัติตั้งแต่ YouTube จน Facebook หากต้องการ hands-free ภายหลัง ให้เก็บ originals ในโฟลเดอร์/inbox พร้อม video-ID mapping ตั้งแต่ pipeline อัปโหลดต้นทาง ไม่เปลี่ยนกลับไปทำ downloader เงียบ ๆ
2. **Shorts vs vertical:** app rule ตั้งใจคัดแนวตั้งทุกความยาวภายใน app limit และ square≤180sec ไม่อ้างรู้ YouTube classification; ถ้าต้องการเฉพาะ Shorts อย่างเป็นทางการ ให้กำหนด owner metadata/explicit flag และข้อยกเว้นช่องเพิ่มเติม
3. **Facebook Reels:** v1 ใช้ Page `/videos` ตามขอบเขตสมมติ หากผู้ใช้ต้องการ `/video_reels` โดยเฉพาะ ต้องตรวจ Reels publishing requirements และเปลี่ยน adapter/tests ก่อนลงมือ ไม่ถือว่า Page video = Reels เสมอ
4. **API approval:** token อ่าน Page ได้ไม่ได้แปลว่าโพสต์ได้; documentation permissions ที่พบต่างกันบางหน้า ต้องมี preflight + approved live smoke กับ app จริง
5. **Video readback limitations:** reference video page ที่เข้าถึงมีหมายเหตุ legacy และ field coverage ไม่ครบ อย่าเดา status fields เพิ่ม; หาก v26 app จริงไม่อนุญาต `source/from` ให้หยุดที่ verifying/needs_review และเก็บผล schema แบบ redacted ก่อนปรับ contract ไม่ mark succeeded จาก ID อย่างเดียว
6. **Duplicate avoidance vs unattended retry:** ยอมให้คนตรวจ unknown POST outcome แทน auto resend เพื่อไม่ทำให้ Page มีคลิปซ้ำ ไม่อ้าง distributed exactly-once
7. **Scale ceiling:** full snapshot สูงสุด100หน้า/ช่องต่อรอบ; ถ้าเกินให้ fail ชัดเจนไม่มี partial baseline ต้องขยาย pagination/checkpoint พร้อมทดสอบก่อนเปิดช่องนั้น v1 ไม่ถูกออกแบบสำหรับคลังขนาดใหญ่หลายร้อยช่อง
8. **Polling latency:** ตรวจวันละครั้งไม่ใช่ทันทีหลัง upload; หลังแนบไฟล์ใช้ worker 5นาที ถ้าต้องการ near real-time ค่อยเพิ่ม polling/WebSub แยก
9. **Music/content rights:** เพลงที่อนุญาตบน YouTube อาจไม่อนุญาตบน Facebook; ต้องให้คนยืนยันสิทธิ์และตรวจเสียงหลังโพสต์ ไม่ strip watermark/เพลงหรือหลบ Content ID
10. **Security/deployment:** v1 ใช้ในเครื่อง staff คนเดียว ไม่เปิด media endpoint และไม่รับ URL ดาวน์โหลดจากภายนอก หากเปิดรับอินเทอร์เน็ตต้องมี deployment/security plan ใหม่
11. **Nonblocking decisions ที่ควรให้ผู้ใช้ยืนยันตอน review:** เวลาสแกน09:00, ต้องการ native Page video ไม่ใช่ dedicated Reels, ต้องการ link post เพิ่มหรือไม่, จำนวนช่องและ Page จริง, ตำแหน่งเก็บ originals และ disk capacity

## Plan-only verification record

- Revision ตามคำขอล่าสุด: แนวนอนเป็น photo notification พร้อมชื่อคลิปและ `tag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย`; ไม่อัปโหลดวิดีโอ ไม่เติมลิงก์ และคงแท็กตามผู้ใช้แม้เป็นแนวนอน เพิ่ม route, metadata, adapter และ offline/live acceptance ในแผนแล้ว

- ตรวจ repo และเครื่องมือด้วย read-only commands แล้ว; repo ไม่มีโค้ด/commit เดิม
- อ่าน official YouTube/Meta/Django docs และแยกข้อจำกัด/ข้อสมมติไว้แล้ว
- Clarifications ของผู้ใช้ถูกนำมาแทนคำขอเริ่มต้น: ไม่ทำ YouTube Posts และไม่ทำ automatic video downloader
- รอบนี้อนุญาตให้เขียนเพียงไฟล์แผนนี้ จึงเก็บ citation mapping ในหน่วยความจำแล้วฝัง Sources ในแผน ไม่สร้าง ledger, spec, code, config, skill หรือเอกสารอื่น
- Acceptance outputs ใน tasks ทั้งหมดเป็น expected outputs สำหรับ implementer ยังไม่ได้รัน test และยังไม่มี Facebook post จริง

## Sources

[1] YouTube Data API reference: https://developers.google.com/youtube/v3/docs
[2] YouTube Developer Policies: https://developers.google.com/youtube/terms/developer-policies
[3] Download your own uploads: https://support.google.com/youtube/answer/56100?hl=en
[4] Shorts eligibility: https://support.google.com/youtube/answer/15424877?hl=en
[5] Channels list: https://developers.google.com/youtube/v3/docs/channels/list
[6] PlaylistItems list: https://developers.google.com/youtube/v3/docs/playlistItems/list
[7] Videos list: https://developers.google.com/youtube/v3/docs/videos/list
[8] Facebook Video publishing: https://developers.facebook.com/docs/video-api/guides/publishing/
[9] Facebook Page videos: https://developers.facebook.com/docs/graph-api/reference/page/videos/
[10] Facebook Page posts: https://developers.facebook.com/docs/pages-api/posts
[11] Facebook Video readback: https://developers.facebook.com/docs/graph-api/reference/video/
[12] Django SQLite notes: https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes
[13] Facebook Page post readback: https://developers.facebook.com/docs/graph-api/reference/page-post/
[14] Facebook Page photos: https://developers.facebook.com/docs/graph-api/reference/page/photos/
[15] YouTube video thumbnails metadata: https://developers.google.com/youtube/v3/docs/videos
