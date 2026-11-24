# دليل GitHub الكامل (من الصفر إلى تشغيل سير العمل)

## 1) إنشاء الحساب
1. افتح github.com ← Sign up ← بريدك وكلمة سر واسم مستخدم ← فعّل البريد من الرسالة.
2. فعّل المصادقة الثنائية: Settings ← Password and authentication.

## 2) تثبيت Git على ويندوز
حمّل Git من git-scm.com واتركه بالإعدادات الافتراضية. ثم في PowerShell:
```
git config --global user.name "اسمك"
git config --global user.email "بريدك-المسجّل-في-GitHub"
```

## 3) إنشاء المستودع الخاص
github.com ← زر + ← New repository ← الاسم `career-manager` ← **Private** ← **لا تضف** README ولا .gitignore ← Create repository.

## 4) فك ضغط المشروع ورفعه
فُك الـ ZIP إلى `C:\career-manager` ثم:
```
cd C:\career-manager
git init -b main
git add .
git commit -m "Initial import"
git remote add origin https://github.com/اسمك/career-manager.git
git push -u origin main
```
عند طلب كلمة السر: **ليست كلمة سر الحساب** بل Personal Access Token: GitHub ← Settings ← Developer settings ← Personal access tokens ← Tokens (classic) ← Generate ← صلاحية `repo` و`workflow` ← انسخه والصقه. (بديل أسهل: برنامج GitHub Desktop: File ← Add local repository ← Publish repository مع تأشير Keep this code private.)
تأكد أن المجلد `.github/workflows` ظهر في المستودع على الموقع.

## 5) تفعيل Actions
تبويب **Actions** ← إن ظهر زر «I understand my workflows, enable them» اضغطه.

## 6) تشغيل سير العمل (بهذا الترتيب)
1. **Build and test**: Actions ← Build and test ← Run workflow ← Run. ينتظر ~10 دقائق. ينجح = الاختبارات تعمل على ويندوز ولينكس، وينتج `grafeco-bench-windows` (برنامج قياس).
2. **Build Career Manager 2026-27 squads and OVR**: Run workflow. خانة `use_ea` اتركها `false` أولاً ثم جرّب `true` في تشغيل ثانٍ. ينتج Artifact باسم `career-manager-2026-27-rosters-and-ovr` فيه CSV الأندية واللاعبين وتقرير التغطية والمصادر.
3. في صفحة التشغيل أسفلاً ← Artifacts ← حمّل الملفات (ZIP) وأرسلها لي لأبني `world.db` الحقيقي وأفحص التغطية.

## 7) قياس جهازك
من Artifact `grafeco-bench-windows` شغّل `grafeco-bench.exe` على لابتوبك وأرسل الناتج. (هذا يقيس المحرك فقط؛ قياس الواجهة يأتي مع أول نسخة غلاف.)

## 8) إصدار ويندوز (لاحقاً)
سير عمل بناء المثبّت **غير موجود بعد** لأن غلاف ويندوز لم يُكتب. عند اكتماله أضيفه لنفس المستودع، وتشغّله بنفس طريقة الخطوة 6، فتحمّل `Career-Manager-Setup.exe` من Artifacts.

## ملاحظات
- المستودع Private: لا يراه أحد غيرك. لا ترفع صوراً شخصية ولا مفاتيح.
- حدود Actions المجانية للمستودعات الخاصة 2000 دقيقة شهرياً، وهي كافية.
