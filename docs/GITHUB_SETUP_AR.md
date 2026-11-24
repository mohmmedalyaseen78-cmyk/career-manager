# بناء نسخة Windows عبر GitHub (بدون تثبيت أدوات على جهازك)

## 1) حساب GitHub
1. افتح https://github.com/signup من المتصفح، وأدخل بريدك وكلمة مرور واسم مستخدم، وأكمل التحقق.
2. أكّد بريدك من الرسالة التي تصلك.

## 2) مستودع خاص
1. اضغط «+» أعلى الصفحة ← New repository.
2. الاسم: grafeco. اختر **Private**. اضغط Create repository.

## 3) رفع الملفات
1. فكّ ضغط grafeco_project.zip على جهازك.
2. في صفحة المستودع اضغط «uploading an existing file».
3. اسحب **محتويات** المجلد (engine, tests, docs, tools, mockups، وملفي bench.py وما معه) إلى الصفحة، ثم اضغط Commit changes.
4. المجلد المخفي `.github`: إن لم يُرفع بالسحب، اضغط Add file ← Create new file، اكتب في الاسم
   `.github/workflows/build.yml` والصق محتوى الملف الموجود في المشروع ثم Commit.

## 4) تشغيل البناء
1. تبويب **Actions** ← إن ظهر زر تفعيل اضغطه.
2. اختر «Build and test» ← Run workflow ← Run workflow.
3. انتظر ~3-5 دقائق حتى يظهر ✓ أخضر.
4. افتح التشغيلة ← أسفل الصفحة **Artifacts** ← grafeco-bench-windows ← يتنزل ملف zip.

## 5) تشغيل القياس على جهازك
1. فكّ الـ zip وشغّل grafeco-bench.exe (قد تظهر تحذيرات SmartScreen لأن الملف غير موقّع: More info ← Run anyway).
2. ينتهي في دقيقة تقريباً ويكتب bench_report.txt بجانبه. أرسله لي.
3. البرنامج يعمل داخل مجلده فقط، ولا يثبّت شيئاً ولا يتصل بالإنترنت.
