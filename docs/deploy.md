# نشر الرفيق المسند على الإنترنت - دليل التشغيل

> **تنبيه ترخيص:** نصوص المصادر (OpenITI) مرخصّة CC BY-NC-SA 4.0 -
> **غير تجاري**. لا إعلانات ولا اشتراكات مدفوعة على النشر الحالي. النسبة
> والمشاركة بالمثل مطلوبتان. أي استخدام تجاري يحتاج طبعات/تراخيص أخرى
> (قرار المالك).

## 1) تجهيز الخادم

```bash
# خادم صغير يكفي للبداية (2GB RAM)
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo adduser rafiq && sudo usermod -aG docker rafiq
su - rafiq && git clone <repo-url> rafiq-os && cd rafiq-os/rafiq-os
```

## 2) الإعدادات (ملف .env بجوار docker-compose.yml)

```bash
cat > .env <<'EOF'
RAFIQ_ENV=prod
RAFIQ_AMIN_SECRET=<قيمة عشوائية 48+ حرفاً: openssl rand -hex 32>
RAFIQ_TRUSTED_HOSTS=rafiq.example.com
RAFIQ_PUBLIC_URL=https://rafiq.example.com
RAFIQ_API_PORT=8000
EOF
chmod 600 .env
```

- `RAFIQ_ENV=prod` يفرض فحص الإقلاع الآمن (سر قوي، مضيفون موثوقون، كوكيز آمنة، HSTS).
- `RAFIQ_PUBLIC_URL` يُستخدم في sitemap.xml و robots.txt خلف وكيل TLS.

## 3) الإقلاع

```bash
docker compose up -d --build
docker compose ps          # كل الخدمات healthy
curl -s localhost:8000/health
```

## 4) TLS و DNS مع Caddy (الأبسط)

DNS: سجل A للدومين → عنوان الخادم.

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile <<'EOF'
rafiq.example.com {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

Caddy يصدّر شهادات Let's Encrypt تلقائياً. جرّب بعد الدقائق الأولى:

```bash
curl -sI https://rafiq.example.com | head -5
curl -s https://rafiq.example.com/sitemap.xml
curl -s https://rafiq.example.com/robots.txt
```

**بلا دومين بعد؟** استخدم `nip.io` فوراً: لو عنوان خادمك `203.0.113.10` فاجعل
Caddyfile:

```
rafiq.203.0.113.10.nip.io {
    reverse_proxy 127.0.0.1:8000
}
```

و`RAFIQ_PUBLIC_URL=https://rafiq.203.0.113.10.nip.io` و`RAFIQ_TRUSTED_HOSTS=`
بنفس القيمة - تحصل على TLS حقيقي بلا شراء دومين، ثم انتقل لدومينك لاحقاً
(أعد فقط Caddyfile والمتغيرات).

## 5) الفهرسة والمشاركة

- أضف الموقع في Google Search Console (تحقق DNS) وأرسل `sitemap.xml`.
- شارك الرابط في قنوات القبائل العلمية: مجموعات المساجد (واتساب/تليجرام)،
  مجتمعات الفقه على فيسبوك/إكس، مع مقطع قصير يشرح «سؤال → جواب بنقول من
  الكتب + رابط الملف المرقمن».
- أزرار المشاركة على كل جواب تنسخ النص + الرابط (واتساب/تليجرام/إكس).
- الموقع PWA (manifest + أيقونة): «إضافة إلى الشاشة الرئيسية» تعمل من متصفح
  الجوال؛ لا يوجد service worker بعد فلا عمل دون اتصال.

## 6) النسخ الاحتياطي (مهم - كل التواريخ هنا)

```bash
# نسخة أسبوعية على Cron
docker run --rm -v rafiq-os_data_volume:/data -v /home/rafiq/backups:/b alpine \
  tar czf /b/rafiq-data-$(date +%F).tgz /data
```

يشمل الحجم: `data/verifications.jsonl` (سجل التوقيعات إن وُجد)، الدورسيهات،
سجل التدقيق، وقواعد SQLite. الاحتفاظ: 8 نسخ أسبوعية على الأقل.

## 7) التحديث والصيانة

```bash
cd rafiq-os/rafiq-os && git pull
docker compose build && docker compose up -d
docker compose logs -f api | tail -50
```

- المراقبة الدنيا: `curl /health` من مراقب خارجي (UptimeRobot مثلاً) + تنبيه.
- حدود المعدل in-memory: عامل واحد فقط (`uvicorn` افتراضي). لا ترفع العمال
  قبل نقل الحدود إلى مخزن مشترك.
- التوسع لاحقاً: CDN للـ static، قاعدة مشتركة (Postgres) عند تعدد العمال.

## 8) بديل مجاني بالكامل ($0): Hugging Face Spaces + PWA

بلا دومين وبلا خادم وبلا بطاقة. الصورة نفسها تعمل: Dockerfile يستمع على
`$PORT` أو 7860.

**أ) تجربة فورية على جوالك (رابط مؤقت، دقائق):**

```bash
export RAFIQ_AMIN_SECRET=$(openssl rand -hex 32)
docker compose up -d --build     # الرابط المحلي: http://localhost:8000
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
cloudflared tunnel --url http://localhost:8000   # انسخ رابط https://*.trycloudflare.com
```

افتح الرابط على الجوال ← سفاري: مشاركة ← «إضافة إلى الشاشة الرئيسية»؛ كروم:
⋮ ← «تثبيت التطبيق». الرابط يتغير عند كل تشغيل - للتجربة اليوم فقط.

**ب) موقع دائم مجاني (HTTPS ثابت):**

1. `huggingface.co/new-space` ← الاسم `rafiq-os`، License: `cc-by-nc-sa-4.0`،
   SDK: **Docker** ← **Blank**، Public. (تأكد أن README.md يبدأ بترويسة
   `sdk: docker` و`app_port: 7860` - موجودة في المستودع.)
2. ادفع الكود (نفس مستودع git، بفرعين بعيدين):
   ```bash
   git remote add origin https://github.com/<user>/rafiq-os.git   # إن لم يكن
   git remote add hf https://huggingface.co/spaces/<user>/rafiq-os
   git push origin main && git push hf main
   ```
3. Space ← Settings ← Variables and Secrets:
   ```
   RAFIQ_ENV=prod
   RAFIQ_AMIN_SECRET=<openssl rand -hex 32>
   RAFIQ_TRUSTED_HOSTS=*.hf.space
   RAFIQ_PUBLIC_URL=https://<user>-rafiq-os.hf.space
   ```
4. الرابط الدائم: `https://<user>-rafiq-os.hf.space` - أضفه إلى Google Search
   Console وأرسل `sitemap.xml`، ثم ثبّته PWA على جوالك.

**بديل احتياطي:** Render.com ← Web Service ← اربط مستودع GitHub ← Docker ←
الخطة المجانية (ينام بعد 15 دقيقة خمول؛ جيد كاحتياط فقط).

**المتاجر لاحقاً:** PWA الآن ($0) ← Microsoft Store ($0 عبر pwabuilder.com)
← Google Play ($25 مرة واحدة) ← App Store (يحتاج Mac + $99/سنة - أجّله).
`CORS` غير مطلوب: كل الصفحات والطلبات من نفس النطاق.

## 9) ما لا تفعله

- لا تفعّل `RAFIQ_DEV_AUTH` في prod (مرفوض تلقائياً).
- لا تشارك `.env` أو `data/verifications.jsonl` علناً (سجل تدقيق).
- لا تَعِد المستخدمين بفتوى: الواجهة تقول صراحة «منقول من الكتب - بلا توقيع
  مفتٍ» و«ليست فتوى مفتٍ» - حافظ على هذه الصياغة في كل وصف للموقع.
