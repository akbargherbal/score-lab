# العارض المتزامن: الصوت والرموز في وقت واحد

MuseScore لا يضع ملف صوتي داخل السكور على خط الزمن (طلب الميزة ما زال مفتوحًا)،
لكن ترانسكربت SheetSage2 يعطينا شيئًا أفضل: **أزمنة حقيقية** للتسجيل —

| ملف | محتواه |
|---|---|
| `downbeat.lab` | لحظة كل بداية بار |
| `beat.lab` | لحظة كل نبضة + رقمها |
| `chord.lab` | `start end chord` لكل كورد |
| `structure.lab` | `start end section` للأقسام |
| `melody_vocal.lab` / `melody_instrumental.lab` | `start end midi_pitch` لكل نوتة |

`tools/score_viewer.py` يحوّل هذه الملفات + التسجيل الأصلي + صفحات السكور إلى
صفحة واحدة تعمل من `file://` بلا خادم وبلا مكتبات خارجية.

## نسختان: مع السكور أو بدونه

العارض لا يحتاج MuseScore إطلاقًا: الموجة والبارات والكوردات والأقسام
والبيانو-رول كلها من ملفات `.lab` + ملف الصوت، والبيانات مضمّنة في الـHTML.
صفحة السكور (الركن الأيسر) ميزة اختيارية تحتاج `mscore-cli` لتصدير الصور:

```bash
# بلا سكور (لا MuseScore، ولا MusicXML، ~10 ثوانٍ للتشغيل كله)
python3 tools/view_run.py --run <run> --transcripts transcripts \
    --audio-dir gs://…/<run> --out <out> --no-pages

# مع السكور (يحتاج <take>.musicxml مسبقًا + MuseScore)
python3 tools/view_run.py --run <run> --audio-dir gs://…/<run> --out <out>
```

ولتراك واحد: `score_viewer.py --abc … --audio … --out viewer.html` بدون
`--pages` = عارض بلا سكور، ومع `--pages <dir>` = يظهر ركن السكور.

## شنو يعرض

- **الموجة** مع خطوط البارات وأرقامها وقوس كل قسم.
- **شريط الكوردات** بأزمنة الموديل الحقيقية (البار الحالي مضاء).
- **شريط الأقسام** (intro / verse / chorus / interlude / outro…).
- **بيانو-رول** لنوتات الصوت (Vocal) والآلة (Ins) — أعلى = طبقة أعلى.
- **صفحة السكور** الخاصة بالبار الحالي، مع رقم البار/النبضة/الكورد/القسم.
- تشغيل/إيقاف، قفز بالنقر، تكبير ٨ بارات أو العرض الكامل، `viewer.html#t=75`
  يفتح على ١:١٥، <kbd>Space</kbd> و<kbd>←</kbd>/<kbd>→</kbd>.

مزامنة صفحة السكور **تقديرية** (تقسيم خطي للبارات على الصفحات) لأن MuseScore
لا يصدّر إحداثيات البارات؛ الكوردات والبارات والأقسام والنوتات كلها **دقيقة**
لأنها من أزمنة الموديل.

## بناء عارض لتراك

```bash
TRACK=out/<run>/transcripts/<take>
OUT=~/score-view/<run>/<take>

mkdir -p "$OUT/pages"
# 1) صفحات السكور (PNG لكل صفحة) من الـMusicXML
mscore-cli -o "$OUT/pages/raw.png" "$OUT/$take.musicxml"

# 2) صغّر الصفحات (اختياري لكن يخفّف الملف)
python3 - <<'PY'
from PIL import Image; import glob, os
for f in sorted(glob.glob(os.environ["OUT"] + "/pages/raw-*.png")):
    n = f.rsplit("-", 1)[-1]
    im = Image.open(f).convert("RGB"); im.thumbnail((1000, 1414))
    im.save(f.rsplit("-", 1)[0] + f"-p-{n}", optimize=True); os.remove(f)
PY

# 3) التسجيل الأصلي
gcloud storage cp "gs://…/runs/<run>/<take>.mp3" "$OUT/audio.mp3"

# 4) العارض
python3 tools/score_viewer.py --abc "$TRACK" --audio "$OUT/audio.mp3" \
    --pages "$OUT/pages" --out "$OUT/viewer.html" --title "<take>"
```

ثم افتح `viewer.html` (من ويندوز: `explorer.exe "$(wslpath -w "$OUT")"`).

## كل التراكات مرة واحدة

```bash
python3 tools/view_run.py --run ~/score-view/<run> \
    --audio-dir gs://<bucket>/.../runs/<run> \
    --out ~/score-view/<run>
```

يقرأ `<run>/transcripts/<take>/*.lab` و`<run>/<take>.musicxml`، يجيب الصوت من
`gs://` (أو من مجلد محلي) مرة واحدة، يبني صفحات السكور، ويكتب
`<out>/<take>/viewer.html` + فهرس `<out>/index.html` فيه كل التراك مع الغلاف
والمقام والمدد والمجاميع. `--force` يعيد البناء، و`--limit N` للتجربة.

## بدائل MuseScore الرسمية (4.7)

| المسار | ماذا يعطي | ملاحظة |
|---|---|---|
| `Publish → Export → MP4` (أو `mscore-cli -o out.mp4 score.musicxml`) | فيديو بصفحات السكور ومؤشّر متحرّك + صوت MuseScore | تم اختباره: ٤:١٩ دقيقة → ٥٤ ثانية رندر، 1080p، AAC. الصوت هو عزف MuseScore لا التسجيل الأصلي |
| `File → Import audio to score` | يحوّل MP3 إلى سكور عبر خدمة musescore.com (بيتا) | يحتاج تسجيل دخول، والاتجاه معاكس: من صوت إلى سكور |
| سكربتات الطرف الثالث (`musescore-audio-sync`, إضافة VLC) | تشغيل ملف صوتي خارجي متزامن مع MuseScore | تحتاج تركيب إضافات/خادم محلي |

العارض هنا لا يحتاج أي منها: يعرض التسجيل الأصلي نفسه مع رموز الترانسكربت.
