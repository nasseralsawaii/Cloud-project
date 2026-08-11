# رحلة الواحة | Oasis Journey

**لعبة منصات عربية مفتوحة المصدر من ست مراحل، مستوحاة من البيئات العُمانية وتعمل مباشرة في المتصفح.**

[🎮 العب النسخة الرئيسية](https://saeed-oasis-game.nasseralsawaii.chatgpt.site) · [نسخة GitHub Pages](https://nasseralsawaii.github.io/saeed-oasis-game/)

An open-source, Arabic-first six-stage browser platformer inspired by Omani landscapes, designed for mobile and desktop play.

![Mobile gameplay preview](docs/gameplay-mobile.jpeg)

## الإصدار 2.0 | Version 2.0

تتدرج الرحلة عبر ست بيئات:

1. الكثبان الأولى
2. سوق الفوانيس
3. ليل النجوم
4. وادي الصخور
5. قلعة الرمال
6. واحة الفجر

يحفظ الإصدار الجديد التقدم بين المراحل ويتيح متابعة الرحلة لاحقًا، مع انتقال النقاط والسلاح والذخيرة والقوة بين المراحل.

## المزايا | Features

- ست مراحل طويلة ومتدرجة مع أهداف وميداليات.
- 12 نوعًا من الوحوش، منها العقرب والأفعى والخفاش وحارس الصخور والمومياء والعنقاء.
- ثلاثة أسلحة متدرجة: مقلاع البذور، عصا البرق، ومدفع الواحة.
- السيارة وبساط الريح والبوابات السرية ونقاط الحفظ.
- 30 طلقة عند الحصول على السلاح، وتتضاعف الذخيرة عند العثور على صندوق مماثل.
- حفظ أفضل نتيجة وتقدم الحملة محليًا في المتصفح.
- تحكم بلوحة المفاتيح وأزرار لمس دلالية ومتجاوبة.
- فحوص آلية لبنية المراحل وسلامة JavaScript.
- Static, framework-free game runtime with no backend required.

## التحكم | Controls

| الإجراء | لوحة المفاتيح |
| --- | --- |
| الحركة | الأسهم أو A / D |
| القفز | Space |
| استخدام السلاح | F |
| الاندفاع | Shift |
| مغادرة السيارة | E |
| الإيقاف المؤقت | Escape |

تظهر أزرار اللمس تلقائيًا على الهاتف والجهاز اللوحي.

## التشغيل محليًا | Run locally

```bash
python3 -m http.server 8000
```

ثم افتح `http://localhost:8000`. لا توجد خطوة بناء مطلوبة.

## المشروع المفتوح | Open source

- [خريطة التطوير](ROADMAP.md)
- [دليل المساهمة](CONTRIBUTING.md)
- [سجل التغييرات](CHANGELOG.md)
- [سياسة الأمان](SECURITY.md)
- [ملاحظات إصدار 2.0](RELEASE_NOTES_2.0.md)

نرحب بالمساهمات في الوصول، والأداء، ودعم العربية، وتصميم المراحل والقيمة التعليمية.

## المؤلف والمشرف الرئيسي | Maintainer

ناصر الصواعي — [@nasseralsawaii](https://github.com/nasseralsawaii)

## الرخصة | License

مرخّص بموجب [MIT License](LICENSE).
