# RUNBOOK — การปฏิบัติงานในเครื่อง

## สถานะและขอบเขต

- ค่าเริ่มต้น `LIVE_PUBLISH=0`, Page `auto_publish=False`; smoke test จริงผ่านแล้วหนึ่งครั้งสำหรับ photo post แนวนอนเท่านั้น ยังไม่มีการเปิดใช้งานต่อเนื่องหรือลงทะเบียน Windows scheduled tasks
- Facebook post ของคลิป `9KETfCikPB4` ผ่าน GET readback ตรวจ exact object ID/owner, caption ตรง format และมี photo attachment หนึ่งไฟล์; remote ID `1367371476460961_122094772071519387`
- คลิปแนวตั้ง `3OGs8nDiXrk` ยังไม่ได้ทดสอบอัปโหลดเพราะไม่มีไฟล์ต้นฉบับ; Page auto publish ถูกปิดกลับหลัง smoke test
- Offline tests ใช้ข้อมูลจำลองและปิด sockets ไม่ใช่หลักฐานว่า token/API/permissions จริงใช้ได้ ต้องให้ผู้ใช้เตรียม credentials ใน `.env`/environment เอง ห้ามส่งค่าลับผ่านแชตหรือบันทึก raw API response
- SQLite และ `media/` อยู่ local disk ไม่ใช้ network share ใช้ worker เพียงหนึ่งตัว; scan/process/reconcile/Admin write ใช้ file lock เดียวกัน ไม่ใช้ SQLite `select_for_update()` แทน interprocess lock

## เปิดใช้งานโดยไม่ส่งจริง

รันจาก project root ใน Git Bash หลังทำ setup ใน README:

```bash
uv run python manage.py check
ffprobe -version
uv run python manage.py check_integrations
uv run python manage.py scan_channels --force
uv run python manage.py process_jobs
```

`check_integrations` เป็น read-only GET: ตรวจ channel/page identity และ read access เท่านั้น **ไม่ยืนยัน publish permission** Graph version ตรึง `v26.0` ผู้ใช้ต้องตรวจ Meta app access level, Page task `CREATE_CONTENT`, permissions ที่ endpoint/version จริงต้องใช้ (เช่น `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`) และ App Review/Business Verification ที่เกี่ยวข้องก่อนเปิดเผยแพร่ ห้ามแก้ version/เพิ่มสิทธิ์เองโดยเดา

สแกนเต็มคลังครั้งแรกเป็น baseline และต้องไม่มี jobs; ครั้งถัดไปคลิปที่เพิ่งพบ public รอ original/ยืนยันแนวนอน ไม่ replay baseline ไม่ใช้ yesterday-only window ต้นทาง private/unlisted/deleted/live/upcoming/replay ไม่ถูกส่ง

`process_jobs` ไม่มี `--publish` เป็น preview ไม่สร้าง job/เปลี่ยน DB/ส่ง HTTP write/สร้าง worker lock การแนบ original ใน Admin เป็นแค่การบันทึกไฟล์ ไม่สั่งโพสต์ ตรวจไฟล์จริงด้วย ffprobe ใน worker ไม่เรียก HTTP หรือ probe ของไฟล์จำลองตอน validate form

## ตรวจสถานะและแก้ไฟล์

| สถานะ | การปฏิบัติ |
|---|---|
| `baseline` | รายการเก่าไว้กันซ้ำ ไม่เข้าคิวอัตโนมัติ |
| `waiting_file` | แนบ original ที่ตรงคลิป หรือยืนยันแนวนอนจากคลิปจริง/Studio ห้ามอ้าง thumbnail |
| `waiting_rights` | ตรวจสิทธิ์ภาพ/เพลงข้ามแพลตฟอร์ม; original ต้องมี rights + file match |
| `waiting_thumbnail` | รอ metadata รูปปกที่ API คืนจริง ไม่สร้าง maxres URL เอง ไม่โพสต์ข้อความล้วน |
| `rejected` / `blocked` | ตรวจรหัสสาเหตุ/format/ไฟล์หาย/route เปลี่ยน ไม่แปลงไฟล์อัตโนมัติ |
| `pending` | ยังไม่ POST; ตรวจ consent, Page flags, public status, file/route ใหม่ก่อนส่ง |
| `sending` | POST อาจกำลังทำงาน ห้ามเปิด worker อีกตัว/kill ระหว่าง upload |
| `verifying` | มี remote ID แล้ว อ่าน GET exact object ซ้ำตาม backoff เท่านั้น ไม่ POST อีก |
| `succeeded` | exact remote object ผ่าน readback **ไม่ใช่**หลักฐานว่าคนทั่วไปมองเห็น ต้องตรวจด้วยคน |
| `needs_review` | ผลส่งกำกวมหรือ route เปลี่ยน หยุดตรวจด้วยคน ห้าม reset คิว/ส่งซ้ำ |

Admin เป็น staff-only + CSRF; Page ID immutable หลังสร้าง, source ID/Page mapping immutable หลัง baseline; Video/PublishJob ไม่มี add/delete/bulk-delete และ job แก้ state/remote ID ไม่ได้ อย่าใช้ SQL เพื่อข้าม guard

ไฟล์ private ไม่ได้เสิร์ฟผ่าน URL Widget ไม่แสดง path/ชื่อ storage/ลิงก์ download; `checked_name`, raw thumbnail URL และ raw remote URL ไม่ถูกแสดงเพื่อกัน path/query-token leak ให้ค้น Facebook ด้วย remote ID ใน job แทน

เปลี่ยน original หรือ `landscape_confirmed` ไม่ได้หลังมีงาน sending/verifying/succeeded/needs_review แต่ถอน `rights_confirmed`/`file_matches_video` ได้หลัง worker คืน lock; `worker_busy` หมายถึงยังไม่บันทึก ให้รอและลองใหม่ การถอนสิทธิ์หยุดส่งครั้งถัดไป ไม่ยกเลิก POST ที่เริ่มไปแล้วและไม่ลบ remote object

## Photo กับ video

- แนวนอน: หนึ่ง **Page photo post** มีรูปปกจริงและข้อความ `ชื่อคลิป` ตามด้วย newline และ `tag: #katy404 #vtuberth #short #วีทูปเบอร์ไทย` ตรงตัว ห้าม URL/ข้อความเกริ่น/แท็กเพิ่ม ห้ามแก้ `#short` เป็น `#shorts` ไม่อัปโหลดวิดีโอและไม่สร้าง link post เพิ่ม
- ไม่จำเป็นต้องมี original ถ้าผู้ดูแลตรวจคลิปจริง/Studio แล้วเปิด `landscape_confirmed` + `rights_confirmed` การยืนยันแนวคลิปไม่ได้พิสูจน์สิทธิ์รูปปกโดยตัวมันเอง
- แนวตั้ง หรือ square≤180 วินาที ใช้ original MP4/H.264 + AAC/ไม่มีเสียง ≤250 MiB และ >0 ถึง1800วินาที พร้อม rights/file match ใช้ native **Page video ไม่ใช่ dedicated Reels** Square>180 ไม่เข้ากติกาส่งของแอป
- `post_link` ปิดโดยปริยาย; เปิดเฉพาะต้องการ link post เพิ่มสำหรับแนวตั้ง ซึ่งทำให้มีสองโพสต์ ไม่ใช้กับแนวนอน
- เปลี่ยน route หลังมีงานต้องตรวจ `needs_review` ไม่สร้างอีกชนิดเพื่อหลบ dedupe

## Unknown POST: ห้าม auto resend

Timeout, 429/5xx หลังเริ่ม POST หรือ worker crash ไม่พิสูจน์ว่าฝั่ง Facebook ไม่รับข้อมูล ระบบจึงหยุด `needs_review` การเริ่ม worker ใหม่ไม่อนุญาต POST ซ้ำ ไม่มี distributed exactly-once guarantee

1. คง `LIVE_PUBLISH=0`/ปิด Page auto publish และหยุด scheduled tasks; รอ worker ที่ทำงานอยู่จบก่อน ห้าม hard-kill ระหว่าง upload
2. จด job ID, video ID, Page และเวลาที่ส่งจาก Admin โดยไม่คัดลอก credentials
3. เปิด Page จริง ตรวจว่ามี remote object อยู่หรือไม่ และดู **เนื้อหาจริง** ไม่ใช่แค่ ID/owner: video/link ต้องตรงคลิปและ YouTube URL ใน caption; photo ต้องตรงรูปปก ชื่อ และแท็กหนึ่งบรรทัดข้างต้น **ไม่บังคับเติม URL ลง photo**
4. ถ้าพบแน่นอน ให้ระบุ remote ID ของ object นั้น (photo ใช้ **Page post `post_id` ไม่ใช่ photo object `id`**) แทน placeholders ด้านล่าง:

```bash
uv run python manage.py reconcile_job JOB_ID --remote-id REMOTE_ID
```

5. Command ใช้ GET อ่าน exact ID ตรวจ owner/ชนิดตาม adapter ไม่ POST และไม่พิสูจน์ content equality แทนคน ถ้าอ่านไม่ได้/owner ไม่ตรง/ยัง processing ให้หยุดแก้สิทธิ์หรือรอตรวจซ้ำ ไม่เปลี่ยน ID ที่บันทึกแล้ว
6. ถ้ายังไม่พบผลส่งที่แน่นอน ให้คง `needs_review` และตรวจผ่าน Page/API โดยผู้ดูแลต่อ **ห้าม reset pending, ลบ job, สร้าง job ใหม่ หรืออัปโหลดซ้ำเพียงเพราะค้นไม่เจอ**
7. เปิด exact object ตรวจ visibility จากมุมมองสาธารณะ เสียง/caption/รูป แล้วบันทึกเฉพาะ remote ID, URL ปกติที่ไม่มี signed query/token, วันเวลาและผลตรวจจริง

`verifying` ที่มี ID แล้ว retry GET ตาม backoff; เมื่อ exhausted ต้องตรวจด้วยคนเช่นกัน ถ้าหลัง crash พบ `sending` โดยไม่มี ID จะเป็น `needs_review`; ถ้ามี ID จะไป readback ไม่ส่งใหม่

## Live smoke gate — ทำได้เมื่อผู้ใช้อนุญาตเท่านั้น

ผลทดสอบจริงหนึ่งรายการ: คลิปแนวนอน `9KETfCikPB4` สร้าง Facebook Page photo post และตรวจ readback ว่า exact ID/owner ตรง, caption ตรง format, มี photo attachment หนึ่งไฟล์; ยังไม่ได้ตรวจ public visibility ด้วยคน คลิปแนวตั้ง `3OGs8nDiXrk` ยังไม่ได้อัปโหลดเพราะไม่มี original MP4 หลัง smoke ตั้ง Page `auto_publish=False` กลับแล้ว ไม่มีการตั้ง Scheduler

1. ผู้ใช้ยืนยัน Page/Channel/สิทธิ์เพลงและภาพ; เตรียม restricted YouTube API key และ Page access token ในเครื่อง ไม่ส่งเข้าห้องสนทนา ผ่าน `check_integrations` และตรวจสิทธิ์เผยแพร่จริงก่อน
2. ทำ baseline โดย Page `auto_publish=False`; อัปโหลดคลิปทดสอบ public ใหม่ที่ได้รับอนุญาต สแกนอีกครั้ง แนบ original+rights+match (หรือ photo: landscape+rights โดยไม่มี original) ให้มีเพียงหนึ่งคลิปพร้อม
3. Preview ตรวจคิว; หลังได้รับอนุมัติให้ตั้ง `LIVE_PUBLISH=1` ในเครื่องและเปิด Page `auto_publish=True` ชั่วคราว รัน:

```bash
uv run python manage.py process_jobs --publish --limit 1
uv run python manage.py process_jobs --publish --limit 1
```

4. ต้องมี remote ID แล้วผ่าน GET readback ก่อนเป็น `succeeded`; ถ้ายัง processing ให้รอ GET retry ห้ามสรุปสำเร็จจาก HTTP POST หรือ ID อย่างเดียว
5. คนเปิด exact object ตรวจ owner/content/caption/เสียงและ public visibility; รัน worker อีกครั้งและตรวจว่าไม่เกิดโพสต์ซ้ำ สำหรับ photo ต้องแยกอนุมัติ smoke เพิ่มและตรวจมีรูปจริงหนึ่งโพสต์ ไม่มี video upload/URL
6. บันทึกผลจริงที่ตัดข้อมูลลับ: remote ID + permalink ปกติ + เวลาตรวจ + visibility ไม่เก็บ signed source URL/raw response ตั้ง `LIVE_PUBLISH=0` และ Page `auto_publish=False` กลับหลังทดสอบ จนผู้ใช้อนุญาตงานประจำวัน

## Windows wrappers และ Task Scheduler (คำแนะนำเท่านั้น)

ยังไม่สร้าง/ลงทะเบียน/enable/launch tasks ให้ Wrappers ใช้ `.venv\Scripts\python.exe`, เปลี่ยน cwd เป็น project root, ต่อ log ใน `.runtime\scan.log`/`process.log` และคืน exit code ของ command ไม่ฝังค่า secret

**`scripts\process.cmd` เป็น preview โดยค่าเริ่มต้น**; หลังผ่าน live gate และได้รับอนุมัติต้องส่ง `--publish` ชัดเจน Wrapper รองรับ `%*`; scan ส่ง `--force` ได้เมื่อจำเป็น

Task Scheduler GUI:

- `Katy404 Scan`: Daily 09:00 ตรวจ Windows timezone เป็น **SE Asia Standard Time (Asia/Bangkok, UTC+07:00)**
- `Katy404 Process`: Repeat every 5 minutes, indefinite. เริ่มจาก preview เท่านั้น
- Program ทั้งคู่: `C:\Windows\System32\cmd.exe`
- Start in ทั้งคู่: `C:\Users\win01\Desktop\Projects\katy404_notify_social`
- Arguments scan:

```text
/d /c ""C:\Users\win01\Desktop\Projects\katy404_notify_social\scripts\scan.cmd""
```

- Arguments process สำหรับ preview:

```text
/d /c ""C:\Users\win01\Desktop\Projects\katy404_notify_social\scripts\process.cmd""
```

- หลังผู้ใช้อนุมัติ live ต่อเนื่องเท่านั้น เปลี่ยน arguments process เป็น:

```text
/d /c ""C:\Users\win01\Desktop\Projects\katy404_notify_social\scripts\process.cmd" --publish"
```

ทั้งคู่เลือก **Do not start a new instance** และ **Run task as soon as possible after a scheduled start is missed** ใช้บัญชีเครื่องที่เข้าถึงโครงการ/env/private files ได้ ห้ามตั้ง hard-kill worker ระหว่าง upload; shared lock กัน scan/process ชนกัน `worker_busy` เป็น safe skip ถ้าเกิดติดกันหลายรอบให้ตรวจ log/worker ไม่ลบ lock ขณะใช้งานหรือเพิ่ม worker ชดเชย ถ้า scan พลาดเวลาให้รัน `scan_channels --force` หลัง lock ว่าง ไม่ได้สแกนแค่คลิปเมื่อวาน

## Retention และ maintenance

สแกนล้าง title/thumbnail ของรายการที่ไม่ public ทันทีเมื่อพบ Source metadata ที่เก่าหรือไม่ยืนยันต่อเนื่อง **เกิน 30 วัน (retention threshold ≥30 days)** ถูก purge เป็น title/thumbnail ว่างและ unavailable ระหว่าง scan/live processing พร้อมแทน Admin audit `object_repr` ของคลิปเหล่านั้นเป็น `Expired video metadata` เพื่อไม่เก็บชื่อคลิปซ้ำใน history แม้ API ล้มเหลว Preview ไม่ทำ purge เพราะห้าม DB writes ให้รัน scan สม่ำเสมอและตรวจ failure ไม่ปล่อย snapshot เก่าค้างโดยคิดว่าเป็นข้อมูลสด Video/job IDs คงอยู่เพื่อกันซ้ำ ไม่เก็บ description/thumb binary ที่ไม่ใช้

ถ้าต้องหยุดทั้งระบบเกิน 30 วัน ให้จัด maintenance ล้าง metadata เก่าก่อนกลับมาแสดง/ใช้งาน ไม่ใช้ข้อมูลเก่าทดแทน source check ไม่แก้/ลบ remote Facebook post ตามการเปลี่ยน title/privacy ต้นทางอัตโนมัติ

Original ของ native video จะถูกลบจาก private storage **หลัง video job และทุก delivery job ที่ตั้งค่าไว้บน Page ของคลิปเดียวกันผ่าน exact-object readback เป็น `succeeded` แล้วเท่านั้น**; HTTP POST/ID ที่ยัง verifying/needs_review ไม่ทำให้ลบ หากไฟล์ลบติด lock/permission ระบบคง DB reference ไว้และลอง cleanup ใน worker รอบถัดไปโดยไม่ POST ซ้ำ Link job ที่ยัง pending ต้องสำเร็จก่อนจึงลบได้ Horizontal photo post ไม่ลบ video original ที่แนบไว้เพราะไม่ได้อัปโหลดไฟล์นั้นเอง การแทนที่ original ก่อนสำเร็จอาจทิ้ง orphan file; สำรองแยกก่อนเผยแพร่ถ้าต้องเก็บต้นฉบับ เพราะ cleanup หลัง verified เป็น irreversible

## Backup และ restore

**หยุด web server และ scheduled tasks ทั้งหมด รอ worker จบก่อน** lock ป้องกันงาน worker ได้ แต่ต้องหยุด web เพื่อให้ DB+media เป็น snapshot เดียว ไม่ copy ไฟล์ SQLite ที่กำลังเขียนด้วย filesystem copy แทน backup API

```bash
uv run python manage.py backup_state --output 'C:/Users/win01/Desktop/Projects/katy404_notify_social/backups/manual-snapshot-001'
```

เลือก directory ใหม่ทุกครั้ง Command ปฏิเสธ path ที่มีอยู่แล้ว ไม่ overwrite ภายในต้องมี `db.sqlite3` และ `media/` ถ้ามี originals อย่าใส่ secret ลง backup note; `.env` ไม่ใช่ส่วนของ backup command เก็บ credentials แยกในที่ปลอดภัย จำกัด ACL/เข้ารหัสและไม่ commit DB/media/backups/logs

Restore rehearsal: ใช้ **สำเนา workspace แยกที่ไม่ active** ไม่มี tasks และตั้ง `LIVE_PUBLISH=0`, Page auto publish ปิด คัดลอก `db.sqlite3` + `media/` จาก snapshot ขณะ web/worker หยุด ติดตั้ง dependency ด้วย `uv sync --frozen` แล้วรัน `uv run python manage.py check` และ preview ตรวจ Admin ว่ามี source/job/remote IDs เดิม ตรวจไฟล์ private บนเครื่องโดยผู้ดูแล (ไม่เปิด URL สาธารณะ) และไม่มีคิวส่งซ้ำ ห้ามทดลอง restore ทับ DB ผู้ใช้ที่ยัง active

## สถานะ verification ของ development workspace

ตรวจแล้ว: `uv run pytest -q` → 324 passed; มี offline end-to-end ทดสอบไฟล์ portrait MP4 ที่สร้างในเครื่องผ่าน ffprobe จริง แต่ YouTube/Facebook HTTP ถูก mock และ pytest ปิด sockets; `uv run ruff check .` และ `uv run ruff format --check .` ผ่าน; Django check ไม่มี issue; migration check `No changes detected`; Admin ได้ login HTML/CSRF และ static CSS ตอบ 200 ขณะที่ `/private-media/...` ตอบ 404; wrapper tests รันกับ Windows `cmd.exe` fixture; backup command สร้าง SQLite snapshot จริงและ `PRAGMA integrity_check` ตอบ `ok`.

นี่เป็นผลทดสอบในเครื่อง ไม่ได้ทดสอบ credentials/API/Meta review/visibility ภายนอก ไม่มีโพสต์จริงและไม่มี scheduled tasks ที่เปิดใช้งาน

## Local serving และตรวจหลังอัปเดต

ใช้ runserver เฉพาะ dev แบบ loopback; persistent WSGI ใช้ Waitress ตาม README แต่ต้องจัด static serving แยก (`collectstatic` ไป `.runtime/static/`) ห้ามเสิร์ฟ `media/` ผ่าน proxy/Waitress สำหรับภายนอกต้องมีแผน HTTPS/secure cookies/CSRF และ deployment checks ก่อน ไม่ได้ตั้ง production server ในงานนี้

```bash
uv run pytest -q
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py process_jobs
git diff --check
```

คำสั่งเหล่านี้ไม่ใช่ live smoke; ถ้าติด ffprobe/credentials/permissions ให้รายงาน blocker ไม่แต่งผลสำเร็จและไม่เปิด publish เพื่อทดแทนการตรวจ
