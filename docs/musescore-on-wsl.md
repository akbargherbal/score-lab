# MuseScore على WSL: بلا بناء

الهدف: MuseScore يشتغل على WSL في دقائق، بلا تجميع من المصدر، وبأقل عدد من
الخطوات اليدوية. كل ما هنا مُختبَر على Ubuntu 22.04 + WSL2 + WSLg.

---

## ١) لماذا AppImage؟

| الطريقة | الحكم | السبب |
|---|---|---|
| **AppImage من GitHub** | ✅ الأسرع | ملف واحد جاهز، بلا `sudo`، بلا بناء، ترقية/تراجع بنسخ ملف |
| `apt install musescore3` | ❌ | Ubuntu يعطي 3.2.3، والإصدار 4 هو المطلوب (وإضافة الـMCP تطلب 4.7+) |
| `snap install musescore` | ⚠️ | يعمل مع systemd، لكن صندوقي: مسار الإضافات يتغيّر، وأثقل في الإدارة |
| Flatpak | ⚠️ | نفس مشكلة المسارات + يحتاج Flathub |
| بناء من المصدر | ❌ | ساعات، ومكتبات Qt كاملة، وما يعطي شيء إضافي |

> على WSLg لا تحتاج تثبيت `libxcb-*` يدويًا: AppImage الخاص بـMuseScore 4
> يحمل مكتبات Qt/xcb معه. على توزيعات سطح مكتب ناقصة قد تحتاج
> `libfuse2` (على 24.04+: `libfuse2t64`) فقط لتشغيل ملف AppImage.

---

## ٢) التثبيت

```bash
mkdir -p ~/Applications
curl -fL -o ~/Applications/MuseScore-Studio-4.7.7.AppImage \
  https://github.com/musescore/MuseScore/releases/download/v4.7.7/MuseScore-Studio-4.7.7.261109195-x86_64.AppImage
chmod +x ~/Applications/MuseScore-Studio-4.7.7.AppImage
```

للتحقق (بلا نافذة):

```bash
QT_QPA_PLATFORM=offscreen ~/Applications/MuseScore-Studio-4.7.7.AppImage --version
# MuseScore4 4.7.7
```

### المُشغّلان

`tools/musescore` و`tools/mscore-cli` يغلّفان الأمرين:

```bash
tools/musescore score.musicxml        # واجهة رسومية عبر WSLg
tools/mscore-cli -o out.pdf score.musicxml   # headless
```

كلاهما يقرأ `MUSESCORE_APPIMAGE` لو غيّرت الإصدار أو المسار.

---

## ٣) الـheadless (الاستخدام الأهم برمجيًا)

بلا نافذة وبلا X — مناسب للسكربتات والتحقق الرسومي:

```bash
tools/mscore-cli -o out.pdf   in.musicxml
tools/mscore-cli -o out.png   in.musicxml   # يكتب out-1.png, out-2.png, ...
tools/mscore-cli -o out.mp3   in.musicxml   # رندر صوتي
tools/mscore-cli -o out.flac  in.musicxml
tools/mscore-cli -o out.mid   in.musicxml
tools/mscore-cli -o out.mscz  in.musicxml   # ملف MuseScore الأصلي
```

قياس فعلي: سكور ٢١١ بار → PDF في **~0.9 ثانية**، PNG لخمس صفحات، MP3 وFLAC
بلا أي واجهة.

ملاحظات:

- تحويل PNG ينتج صفحات بأبعاد كبيرة جدًا (A4 بدقة عالية ~9924×14028). للأرشفة
  استخدم PDF، وللصور صغّرها (مثلًا بـPIL/`pdftoppm`).
- التصدير يعمل مع `QT_QPA_PLATFORM=offscreen` فقط؛ لا تضع `xcb` في السكربتات.

---

## ٤) الواجهة على WSLg

- WSLg يوفّر X server وPulseAudio، فالنافذة والصوت يعملان مباشرة.
- `tools/musescore` يضبط `QT_QPA_PLATFORM=xcb` تلقائيًا.
- رسائل `ALSA lib seq_hw.c ... /dev/snd/seq` عند البدء **غير ضارة**: لا يوجد
  ALSA داخل WSL، والصوت يمرّ عبر PulseAudio.

---

## ٥) ربط MCP (اختياري)

مشروع [ghchen99/mcp-musescore](https://github.com/ghchen99/mcp-musescore) يفتح
سكور مفتوح في MuseScore عبر WebSocket (بورت 8765) ويسمح للوكيل يقرأ ويعدّل
ويعلّق على النوتات.

المتطلبات: MuseScore **4.7+**، و`uv`، وعميل MCP (Claude Desktop أو opencode).

```bash
git clone https://github.com/ghchen99/mcp-musescore.git ~/opt/mcp-musescore
cd ~/opt/mcp-musescore && uv sync

mkdir -p ~/Documents/MuseScore4/Plugins
ln -sfn "$PWD/musescore-mcp-websocket.qml" \
  ~/Documents/MuseScore4/Plugins/musescore-mcp-websocket.qml
```

ثم داخل MuseScore:

1. `Plugins → Plugin Manager` → فعّل **MuseScore API Server**
2. `Plugins → MuseScore API Server` (اتركه يعمل ما دام السكور مفتوحًا)

وتسجيل السيرفر في opencode (سطر واحد):

```bash
opencode mcp add musescore --global -- \
  /home/$USER/opt/mcp-musescore/.venv/bin/python \
  /home/$USER/opt/mcp-musescore/server.py
opencode mcp list      # يجب أن يظهر: musescore
```

إن ظهر `success: false` عند الاتصال فالسبب عادةً أن الإضافة لم تُشغَّل من قائمة
Plugins، أو أن MuseScore ليس مفتوحًا على سكور.

---

## ٦) مشاكل شائعة

| العرض | السبب / الحل |
|---|---|
| `AppImage: Permission denied` | `chmod +x` على الملف |
| `fuse: failed to exec fusermount` | ثبّت `libfuse2` (22.04) أو `libfuse2t64` (24.04+) |
| `could not load the Qt platform plugin "xcb"` | لا يوجد X: استخدم WSLg، أو `QT_QPA_PLATFORM=offscreen` |
| لا صوت | الصوت يمرّ عبر PulseAudio في WSLg؛ رسائل ALSA غير ضارة |
| تحويل PNG عملاق | استخدم PDF، أو صغّر الصور بعد التصدير |
| الـMCP لا يتصل | الإضافة غير مفعّلة/غير مشغّلة، أو بورت 8765 مستخدم |
