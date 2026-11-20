# score-lab

مساحة صغيرة للتعلّم والفضول حول **السكور**: كيف يُكتب، كيف يُقرأ، وكيف ينتقل من
نص ABC إلى ورقة مطبوعة في MuseScore.

*Score notation sandbox — ABC → MusicXML → MuseScore, plus a primer on reading a
score. Unrelated to any production project; this is for learning.*

![score-lab demo](examples/demo.png)

> المشروع الأم: [akbargherbal/arabmaqamrock](https://github.com/akbargherbal/arabmaqamrock).
> هذا المستودع **منفصل تمامًا** ولا يشارك أي كود أو بيانات معه؛ أُخذ منه فقط
> ملف `abc_tools.py` المنسوخ (MIT) ليفهم لهجة ABC المستخدمة هناك.

---

## شنو موجود هنا

| المسار | شنو |
|---|---|
| `docs/abc-primer-ar.md` | **ابدأ من هنا**: شنو السكور، شنو ABC، جدول الرموز والمدد، وكيف تقرأ ملفًا سطرًا بسطر |
| `docs/musescore-on-wsl.md` | تثبيت MuseScore على WSL بلا أي بناء، التشغيل الرسومي والـheadless، وربط MCP |
| `docs/synchronized-viewer.md` | العارض المتزامن: التسجيل الأصلي + البارات والكوردات والأقسام والنوتات وصفحة السكور في وقت واحد |
| `tools/abc_to_musicxml.py` | تحويل سكور ABC (لهجة arabmaqamrock) إلى MusicXML 4.0 الذي يفتحه MuseScore |
| `tools/musescore` | مُشغّل الواجهة الرسومية (WSLg) |
| `tools/mscore-cli` | تحويل/تصدير بلا نافذة: pdf, png, mp3, flac, mid, mscz |
| `tools/take_shot.sh` | تصوير نافذة WSLg (MuseScore) من جهة ويندوز — `--list`, `--wait`, `--client`، للتحقق البصري |
| `tools/score_viewer.py` | عارض متزامن: التسجيل الأصلي + الموجة + البارات + الكوردات + الأقسام + النوتات على خط زمني واحد (صفحة السكور اختيارية بـ`--pages`، وبلاها لا يحتاج MuseScore) |
| `tools/view_run.py` | يبني العارض لكل تراكات تشغيلية + فهرس `index.html`، مع جلب الصوت من `gs://`، ويقبل التراكات مفكوكة أو كأرشيفات `.tar.gz` / `.zip` |
| `tools/vendor/` | نسخة مثبّتة من parser `abc_tools.py` (MIT) ليكون المستودع مكتفيًا بذاته |
| `examples/demo.abc` | ٤ بارات: كوردات + لحن + ربط (tie) عبر خط البار |
| `tests/` | ١٦ اختبارًا على المحوّل واكتشاف تراكات التشغيل (بدون شبكة، بدون MuseScore) |

## البدء السريع

```bash
# 1) MuseScore (AppImage، بلا بناء — التفاصيل في docs/musescore-on-wsl.md)
mkdir -p ~/Applications
curl -fL -o ~/Applications/MuseScore-Studio-4.7.7.AppImage \
  https://github.com/musescore/MuseScore/releases/download/v4.7.7/MuseScore-Studio-4.7.7.261109195-x86_64.AppImage
chmod +x ~/Applications/MuseScore-Studio-4.7.7.AppImage

# 2) ABC -> MusicXML، ثم ورقة PDF
python3 tools/abc_to_musicxml.py examples/demo.abc \
    --out /tmp/demo.musicxml --render pdf
```

بعدها `/tmp/demo.pdf` جاهز، أو افتح الموسيقى تفاعليًا:

```bash
tools/musescore /tmp/demo.musicxml
```

## المحوّل `abc_to_musicxml.py`

- جزء MusicXML واحد لكل صوت ABC (`Vocal`, `Ins`)
- الكوردات في سطور مزدوجة تصير `<harmony>` على ستاف Vocal
- إعادة بناء دقيقة: تقسيم النوتات على خطوط البارات مع `tie`، ملء الفراغات
  سكتات، بارات فاضية سكتة كاملة، تغييرات المقام والوزن، والسرعة
- `divisions=8` لأن لهجة ABC كلها مضاعفات `1/32` — بلا أي تقريب
- `verify()` يقرأ المخرَج مرة ثانية ويقارن مجموع المدد مع المصدر، ويرفض أي فقد
  صامت

```bash
python3 tools/abc_to_musicxml.py score.abc --out score.musicxml \
    --title "اسم القطعة" --render pdf --render png --render mid
```

`MUSESCORE` متغيّر بيئة يحدد الملف التنفيذي، وافتراضيًا يستخدم `mscore-cli`
أو `musescore` من الـ`PATH`.

## العارض المتزامن لتشغيل كامل

`tools/view_run.py` يبني صفحة لكل take + فهرسًا واحدًا. الأمر الأساسي (بلا
MuseScore ولا MusicXML):

```bash
python3 tools/view_run.py --run <run-dir> \
    --transcripts transcripts \
    --audio-dir gs://<bucket>/.../<run> \
    --out <run-dir>/score --no-pages
```

### شكل مجلد التشغيل

لازم يطابق هذا الشكل (الأسماء أمثلة؛ المهم البنية وأسماء الملفات):

```text
<run-dir>/
├── transcripts/                    # --transcripts transcripts
│   ├── p01_hijaz_…/                # مجلد لكل take
│   │   ├── score.abc               # إلزامي: المقام/الميزان/السرعة/عدد البارات
│   │   ├── downbeat.lab            # إلزامي: لحظة بداية كل بار
│   │   ├── beat.lab                # إلزامي: لحظة كل نبضة
│   │   ├── chord.lab               # إلزامي: start end chord
│   │   ├── structure.lab           # إلزامي: start end section
│   │   ├── melody_vocal.lab        # إلزامي: start end midi_pitch
│   │   ├── melody_instrumental.lab # إلزامي: start end midi_pitch
│   │   └── meta.json               # إلزامي: منه تُقرأ مدّة الموديل للفهرس
│   ├── p02_nahawand_…/
│   └── (أي ملفات أخرى مثل events.json تُتجاهل)
├── p01_hijaz_….mp3                 # في --audio-dir (هنا أو gs://…/<run>/)
├── p02_nahawand_….mp3
├── p01_hijaz_….musicxml            # اختياري: فقط لصفحات السكور (بلا --no-pages)
└── score/                          # --out (يُنشأ تلقائيًا)
    ├── index.html
    └── p01_hijaz_…/
        ├── viewer.html
        └── audio.mp3
```

بدل المجلدات المفكوكة، يكفي أرشيف لكل تراك — نفس المحتوى بداخله:

```text
<run-dir>/transcripts/
├── p01_hijaz_….tar.gz     # بداخله p01_hijaz_…/score.abc + بقية الملفات
└── p02_nahawand_….tar.gz
```

أو أرشيف `.zip` واحد للشجرة كاملة، في `abc_transcript/` أو جذر التشغيل:

```text
<run-dir>/
├── abc_transcript/
│   └── <run>_abc_transcript.zip
│       └── transcripts/           # الغلاف هذا طبيعي
│           ├── p01_hijaz_…/{score.abc, *.lab, meta.json}
│           └── p02_nahawand_…/
└── p01_hijaz_….mp3
```

الأرشيفات تُفكّ تلقائيًا في `<out>/.transcripts/`، فلا حاجة لفكّها يدويًا
ولا يُكتب شيء داخل `<run-dir>`. و`<run>/<take>.mp3` غير مطلوب إذا كان
`--audio-dir` يشير إلى `gs://` أو إلى مجلد آخر.

- `--transcripts` يقبل أي شكل من الأشكال الثلاثة أعلاه؛ وإن لم يوجد مجلد
  `transcripts/` أصلًا يبحث في `<run>/abc_transcript/` ثم جذر التشغيل.
- `--audio-dir` يقبل `gs://…` أو مجلدًا محليًا فيه `<take>.mp3`، والصوت
  الموجود لا يُجلب مرة ثانية. `--force` يعيد البناء و`--limit N` للتجربة.
- الناتج: `<out>/<take>/viewer.html` + `<out>/index.html` (مدد، مقام، ميزان،
  بارات، كوردات). افتح `index.html` مباشرة من `file://`.
- لصفحات السكور: احذف `--no-pages`، وجهّز `<run>/<take>.musicxml`
  (`abc_to_musicxml.py`) مع MuseScore.

وتراك واحد فقط:

```bash
python3 tools/score_viewer.py --abc <take-dir> --audio <take>.mp3 \
    --out viewer.html --title "<take>"
```

## الاختبارات

```bash
python3 -m pytest tests -q      # أو: python3 -m unittest discover tests
```

## حدود

- هذا المستودع **ليس** جزءًا من أي pipeline إنتاجي، ولا يُستورد من المشروع الأم.
- اللهجة المدعومة هي لهجة `arabmaqamrock` الصارمة: صوتان، `L:1/32`، بلا أقواس
  نوتات، بلا بارات تكرار.
- MuseScore لا يفتح ABC أبدًا — لذلك وُجد هذا المحوّل.

## الترخيص

MIT — انظر `LICENSE`. أما `tools/vendor/abc_tools.py` فمن YuE2 (MIT،
انظر `tools/vendor/LICENSE`).
