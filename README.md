# Katy404 Notify Social

Django Admin + SQLite สำหรับตรวจคลิปสาธารณะใหม่ของช่อง YouTube ที่คุณดูแล แล้วเตรียมส่งไปยัง Facebook **Page** โดยใช้ไฟล์ต้นฉบับ/ไฟล์ที่คุณดาวน์โหลดผ่าน YouTube Studio เอง ไม่มี downloader, browser cookies หรือ Community Posts

**ดาวน์โหลด MP4 อัตโนมัติ (ปิดเป็นค่าเริ่มต้น):** ตั้ง `YT_DOWNLOAD=1` ใน `.env` เพื่อให้ worker ใช้ yt-dlp (ไม่ใช้ cookies, ไม่ใช้ `YOUTUBE_API_KEY`) โหลดคลิป**แนวตั้ง**ใหม่ของช่องที่ `enabled` + `ownership_confirmed` และ Page เปิด `auto_publish` เท่านั้น คลิปแนวนอนไม่โหลด (อ่านขนาดจากเมตาดาตา แล้วส่งเป็น photo post) คลิป baseline ไม่ถูกโหลด ล้มเหลวจะลองใหม่ได้ทุก 1 ชั่วโมง หลังโพสต์ผ่านการอ่านกลับจาก Facebook ระบบลบ MP4 เอง ความเสี่ยง: นโยบาย YouTube API ห้ามดาวน์โหลด/เก็บสำเนา audiovisual content โดยไม่มีหนังสืออนุมัติ[1] และ ToS ของ YouTube อาจจำกัดการดาวน์โหลดนอกเหนือ Studio[2] ใช้กับช่องของคุณเองและยอมรับความเสี่ยงเอง ทางปลอดภัยกว่าคือดาวน์โหลดผ่าน YouTube Studio แล้วแนบใน Admin

**ค่าเริ่มต้นปิดการเผยแพร่จริง** (`LIVE_PUBLISH=0`, Page `auto_publish=False`) และ `process_jobs` เป็น preview เท่านั้น ทดสอบจริงแล้วสำหรับคลิปแนวนอนหนึ่งคลิป: Facebook Page ได้รับ photo post หนึ่งรายการ และตรวจยืนยัน owner, caption และไฟล์แนบผ่าน readback; ยังไม่ได้ทดสอบอัปโหลดวิดีโอแนวตั้งเพราะยังไม่มีไฟล์ต้นฉบับ

## เริ่มใช้ในเครื่อง (Windows + Git Bash)

ต้องมี `uv` และ Python 3.13 (จัดการผ่าน uv ได้) พร้อม **ffprobe จาก FFmpeg** ที่ติดตั้งจากแหล่งที่คุณเชื่อถือเอง ทดสอบ `ffprobe -version`; ถ้าไม่อยู่ใน PATH ให้กำหนด `FFPROBE_BIN` เป็น path ของ executable ในเครื่อง ไม่ได้แถม ffprobe มากับแอป

```bash
uv sync --frozen
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver 127.0.0.1:8000
```

เปิด <http://127.0.0.1:8000/admin/> ใช้บัญชี staff/superuser; `runserver` ใช้พัฒนาในเครื่องเท่านั้น อย่า bind `0.0.0.0` หรือเปิดพอร์ตสู่ภายนอก

ตัว scheduler ทำงานเป็น Django management command แยกจากเว็บเซิร์ฟเวอร์: รัน `uv run python manage.py run_scheduler` ใน terminal อีกหน้าต่างเพื่อ preview หรือเติม `--publish` เมื่ออนุมัติ live publishing แล้ว คำสั่งจะ scan ทันที จากนั้น scan ทุกชั่วโมงและ process คิวทุก 60 วินาที วิดีโอที่อยู่ในช่วงเวลาที่ Meta รับได้จะอัปโหลดเป็นโพสต์กำหนดเวลาใน Facebook; รายการที่ไกลกว่านั้นจะรอใน backend แล้วเลื่อนเข้า Facebook เมื่อถึงช่วงที่รองรับ ดูวิธีเปิดใช้งานและหยุดใน [RUNBOOK.md](RUNBOOK.md)

ตั้งค่าลับใน `.env`/environment เท่านั้น: `DJANGO_SECRET_KEY`, `YOUTUBE_API_KEY`, และ Page token ตามชื่อ `token_env` เช่น `FB_PAGE_TOKEN_MAIN` อย่าใส่ token จริงใน Admin, SQLite, log, Git หรือ screenshot และอย่าใช้ shell command ที่พิมพ์ค่าลับออกมา คง `FB_GRAPH_VERSION=v26.0` และ `LIVE_PUBLISH=0` ระหว่างติดตั้ง

1. เพิ่ม Page: ระบุ numeric Page ID และ **ชื่อ environment variable** ใน `token_env` ไม่ใช่ token จริง คง `auto_publish=False`, `post_link=False`
2. เพิ่ม Channel: ใช้ Channel ID รูปแบบ `UC…` ตรงตัว ไม่ใส่ handle/URL/ช่องว่าง เลือก Page และยืนยันว่าเป็นเจ้าของ/ดูแลช่องก่อนเปิด `ownership_confirmed` และ `enabled`
3. สแกนครั้งแรกเป็น baseline ทั้งคลัง: ไม่มีงานโพสต์คลิปย้อนหลัง หลัง baseline ห้ามเปลี่ยน Channel ID หรือ Page mapping; Page ID แก้ไม่ได้หลังสร้าง
4. คลิปสาธารณะใหม่จะรอ original หรือการยืนยันแนวนอน การแนบไฟล์ใน Admin **บันทึกอย่างเดียว ไม่ส่ง Facebook และไม่สร้างงานด้วยตัวมันเอง**

## รูปแบบการส่ง

- แนวตั้ง หรือสี่เหลี่ยมที่ยาวไม่เกิน 180 วินาที: native **Page video ปกติ ไม่ใช่ dedicated Reels endpoint** ต้องมี original MP4/H.264, audio AAC หรือไม่มี audio, ระยะเวลา >0 ถึง 1800 วินาที, ขนาดไม่เกิน 250 MiB พร้อม `rights_confirmed` และ `file_matches_video` ทั้งคู่ ไม่แปลงไฟล์/ตัดคลิปอัตโนมัติ
- แนวนอน: **photo post เท่านั้น** มีรูปปกจริงจาก metadata และ caption ตามด้านล่าง ไม่มี URL ไม่มี video upload และไม่มี link post เพิ่ม แม้ Page เปิด `post_link`
- ถ้าไม่มี original สำหรับแนวนอน ให้ตรวจคลิปจริงหรือข้อมูลใน Studio แล้วเปิด `landscape_confirmed` และ `rights_confirmed` (รวมสิทธิ์ใช้รูปปก) ได้ ไม่ต้องแนบวิดีโอหรือเปิด `file_matches_video` **ห้ามเดาสัดส่วนคลิปจาก thumbnail**
- ถ้าไม่รู้แนวคลิปให้รอ; ไม่มีรูปปกที่ใช้ได้ให้รอ `waiting_thumbnail` ไม่ fallback เป็นข้อความล้วน การจัดประเภทนี้เป็นกติกาของแอป ไม่ใช่การรับรอง Shorts ของ YouTube

Caption photo ตรงตัว โดยแทนบรรทัดแรกด้วยชื่อคลิปจริง:

```text
ชื่อคลิป
tag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย
```

การเป็นเจ้าของช่องไม่ได้ยืนยันสิทธิ์นำเพลง/ภาพไป Facebook อัตโนมัติ ตรวจสิทธิ์ข้ามแพลตฟอร์มก่อนยืนยัน

## คำสั่งหลัก

```bash
uv run python manage.py check
uv run python manage.py check_integrations
uv run python manage.py scan_channels
uv run python manage.py scan_channels --force
uv run python manage.py process_jobs
uv run pytest -q
```

`check_integrations` ใช้ GET ตรวจ identity/read access ไม่พิสูจน์ publish permission; `scan_channels` อ่าน metadata และแก้สถานะในเครื่อง ไม่โพสต์ Facebook; preview ไม่แก้ DB/ไม่ส่งจริง Tests ปิด sockets โดยค่าเริ่มต้น

**อย่ารัน `process_jobs --publish` จนผู้ใช้อนุญาตและผ่าน gate ใน [RUNBOOK.md](RUNBOOK.md)** ต้องมี `--publish`, `LIVE_PUBLISH=1`, Page `auto_publish=True` และ consent/ข้อมูลที่ตรวจผ่านครบพร้อมกัน ถ้า POST ไม่ทราบผล ระบบหยุด `needs_review` ไม่ auto resend

## การเก็บข้อมูลและดูแลระบบ

- Original อยู่ใน private `media/` ไม่ใช่ public download; Admin ไม่แสดง path/ลิงก์ไฟล์ ไม่ map `/private-media/` ให้เว็บเซิร์ฟเวอร์
- เมื่อ native video post ทุกแบบของคลิปนั้นบน Page ผ่าน Facebook exact-object GET readback แล้ว ระบบลบ MP4 ต้นฉบับจาก private storage และล้างช่องไฟล์ใน DB; ไม่ลบหลัง HTTP POST เพียงอย่างเดียว และไม่ลบเมื่องาน pending/failed/needs_review หรือมี link delivery อื่นยังไม่ยืนยัน
- การลบเป็น irreversible: หากต้องเก็บ archival original ให้สำรองแยกก่อนเผยแพร่; horizontal photo notification ไม่อัปโหลด MP4 จึงไม่ลบ original ด้วย flow นี้
- Video/job ห้ามสร้างหรือลบเองจาก Admin; job เป็น view-only ปิด bulk delete สำหรับ operational records เปลี่ยน original/การยืนยันแนวนอนไม่ได้เมื่อส่งเริ่มแล้ว แต่ยังถอน rights/file-match ได้ (ไม่ย้อนลบ remote post)
- Admin writes ใช้ lock เดียวกับ worker; ถ้าขึ้น `worker_busy` จะไม่มีการบันทึก ให้รอ worker จบแล้วลองใหม่ อย่า kill ระหว่าง upload
- Metadata ที่ไม่ public ล้างทันทีเมื่อสแกน/ตรวจต้นทาง; metadata เก่าที่ตรวจไม่ได้เกิน 30 วัน purge พร้อมล้างชื่อคลิปที่ค้างใน Django Admin audit history โดย scan/live worker เก็บ ID เป็น tombstone กันซ้ำ อย่าปล่อย worker หยุดนานแล้วถือว่าข้อมูลยังสด
- การอัปโหลดไฟล์แทนที่ก่อนโพสต์สำเร็จอาจทิ้ง **orphan files** เพราะ Django ไม่ลบไฟล์เก่าให้ ต้องสำรองก่อนตรวจและทำความสะอาดเองหลังตรวจ references; หลัง Facebook video job และ delivery jobs ทั้งหมดผ่าน readback สำเร็จ ระบบจะลบ MP4 ต้นฉบับตามคำขอ
- การแก้ชื่อหรือเปลี่ยนคลิปเป็น private ภายหลังไม่แก้/ลบโพสต์ Facebook ที่เผยแพร่แล้วอัตโนมัติ

## Verification completed in the development workspace

Offline validation on the current workspace completed: `347 passed`; the end-to-end test uses a real generated portrait MP4 and local `ffprobe`, while YouTube/Facebook API responses are mocked and network sockets are blocked for the suite. `uv run ruff check .`, `uv run ruff format --check .`, Django system check, migration drift check, Admin HTTP/CSRF/static/private-media checks, and Windows wrapper fixture tests pass. This does not verify credentials, Meta app approval, Page permissions, Facebook processing, or public visibility.

## Local persistent serving

```bash
uv run python manage.py collectstatic --noinput
uv run waitress-serve --listen=127.0.0.1:8000 config.wsgi:application
```

**Waitress ไม่เสิร์ฟ static files เอง**: คำสั่งนี้เปิด WSGI เท่านั้น ต้องจัด local static server/reverse proxy ให้ `/static/` ชี้ `.runtime/static/` จึงใช้ Admin CSS/JS ได้ครบ ห้ามชี้ไป `media/` ไม่อ้างว่าแค่นี้พร้อม production สำหรับ deployment ต้องกำหนด `DJANGO_DEBUG=0`, secret ที่แข็งแรง, HTTPS proxy, secure cookies/CSRF trusted origins และตรวจ `uv run python manage.py check --deploy` แยกก่อนเปิดรับภายนอก

Backup/restore, unknown POST reconciliation, live gate และ backend scheduler อยู่ใน [RUNBOOK.md](RUNBOOK.md)

## Sources

[1] YouTube API Services Developer Policies: https://developers.google.com/youtube/terms/developer-policies
[2] Download videos you've uploaded through YouTube Studio: https://support.google.com/youtube/answer/56100?hl=en

