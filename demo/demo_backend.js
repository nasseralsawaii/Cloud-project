/* طبقة تحاكي الخادم داخل المتصفح، للنسخة التجريبية فقط.

   الغرض: تشغيل واجهة البرنامج الحقيقية (web/app.js) كما هي، بلا أي تعديل،
   مع استبدال الخادم بذاكرة داخل الصفحة. أي اختلاف في السلوك بين هذه الطبقة
   والخادم الحقيقي هو خطأ في هذا الملف، لا في البرنامج.

   البيانات هنا في ذاكرة المتصفح فقط: تختفي عند إعادة تحميل الصفحة، ولا
   تُرسل إلى أي مكان. */

(function () {
  'use strict';

  // ------------------------------------------------------- حساب المبالغ

  const BAISA = 1000;
  const RATES = { standard: 500, zero: 0, exempt: 0 };
  const ARABIC_DIGITS = { '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9' };

  function toNumberText(value) {
    return String(value == null ? '' : value)
      .trim()
      .replace(/[،,٬]/g, '')
      .replace(/٫/g, '.')
      .replace(/[٠-٩]/g, (d) => ARABIC_DIGITS[d]);
  }

  /** يحوّل مبلغًا بالريال إلى بيسة (عدد صحيح). */
  function parseAmount(value) {
    const text = toNumberText(value);
    if (text === '') return 0;
    const number = Number(text);
    if (!isFinite(number)) throw new DemoError('قيمة المبلغ غير صالحة');
    return Math.round(number * BAISA);
  }

  /** يحوّل كمية إلى أجزاء الألف. */
  function parseQuantity(value) {
    const text = toNumberText(value);
    if (text === '') return 0;
    const number = Number(text);
    if (!isFinite(number)) throw new DemoError('قيمة الكمية غير صالحة');
    return Math.round(number * BAISA);
  }

  /** نفس ترتيب الخادم: الخصم أولًا، ثم الضريبة على الصافي بعد الخصم. */
  function lineTotals(unitPrice, quantity, rateBp, discountBaisa) {
    const gross = Math.round((unitPrice * quantity) / BAISA);
    const discount = Math.min(discountBaisa || 0, gross);
    const taxable = gross - discount;
    const vat = Math.round((taxable * rateBp) / 10000);
    return { gross, discount, taxable, vat, total: taxable + vat };
  }

  function formatMoney(baisa) {
    const value = Math.abs(Math.round(baisa || 0));
    return (baisa < 0 ? '-' : '') +
      Math.floor(value / BAISA).toLocaleString('en-US') + '.' +
      String(value % BAISA).padStart(3, '0');
  }

  function todayText() {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }

  function DemoError(message) { this.message = message; }
  DemoError.prototype = Object.create(Error.prototype);

  // ------------------------------------------------------- حالة النسخة التجريبية

  const store = {
    loggedIn: true,   // النسخة التجريبية تبدأ من داخل البرنامج مباشرة
    org: {
      id: 1,
      name: 'مؤسسة النور للتجارة',
      vat_number: 'OM1100234567',
      cr_number: '1234567',
      address: 'روي، مسقط، سلطنة عُمان',
      phone: '92345678',
      email: 'info@alnoor.om',
      invoice_prefix: 'NOOR',
      next_invoice_no: 1,
      plan: 'pro',
    },
    user: { id: 1, org_id: 1, email: 'demo@omanbill.om', name: 'ناصر' },
    customers: [],
    items: [],
    invoices: [],
    nextIds: { customer: 1, item: 1, invoice: 1, payment: 1 },
  };

  const PLAN_LIMITS = {
    free: { invoices_per_month: 10, customers: 25, label: 'المجانية' },
    pro: { invoices_per_month: null, customers: null, label: 'الاحترافية' },
  };

  function orgPayload() {
    return Object.assign({}, store.org, { plan_limits: PLAN_LIMITS[store.org.plan] });
  }

  function nextInvoiceNumber() {
    const sequence = store.org.next_invoice_no++;
    return store.org.invoice_prefix + '-' + String(sequence).padStart(5, '0');
  }

  // ------------------------------------------------------- بناء الفاتورة

  function prepareLines(rawLines) {
    if (!Array.isArray(rawLines) || !rawLines.length) {
      throw new DemoError('الفاتورة يجب أن تحتوي على بند واحد على الأقل');
    }
    return rawLines.map((raw, position) => {
      const description = String(raw.description || '').trim();
      if (!description) throw new DemoError('وصف البند رقم ' + (position + 1) + ' مطلوب');

      const category = String(raw.vat_category || 'standard');
      if (!(category in RATES)) throw new DemoError('الفئة الضريبية غير معروفة');

      const quantity = parseQuantity(raw.quantity);
      if (quantity <= 0) {
        throw new DemoError('كمية البند رقم ' + (position + 1) + ' يجب أن تكون أكبر من صفر');
      }

      const unitPrice = parseAmount(raw.unit_price);
      const rateBp = RATES[category];
      const computed = lineTotals(unitPrice, quantity, rateBp, parseAmount(raw.discount));

      return {
        id: position + 1,
        position: position,
        description: description,
        unit: String(raw.unit || 'قطعة').trim() || 'قطعة',
        quantity: quantity,
        unit_price: unitPrice,
        discount: computed.discount,
        vat_category: category,
        vat_rate_bp: rateBp,
        taxable: computed.taxable,
        vat_amount: computed.vat,
        line_total: computed.total,
      };
    });
  }

  function checkMonthlyLimit(issueDate) {
    const limit = PLAN_LIMITS[store.org.plan].invoices_per_month;
    if (limit === null) return;
    const month = issueDate.slice(0, 7);
    const used = store.invoices.filter(
      (inv) => inv.issue_date.slice(0, 7) === month && inv.status !== 'cancelled').length;
    if (used >= limit) {
      throw new DemoError('الباقة المجانية تسمح بـ ' + limit +
        ' فواتير شهريًا. رقّ إلى الباقة الاحترافية لإصدار فواتير بلا حد.');
    }
  }

  function buildInvoice(data, existing) {
    const issueDate = data.issue_date || todayText();
    const dueDate = data.due_date || '';
    if (dueDate && dueDate < issueDate) {
      throw new DemoError('تاريخ الاستحقاق لا يمكن أن يسبق تاريخ الإصدار');
    }

    const lines = prepareLines(data.lines);
    const totals = lines.reduce((sum, line) => ({
      gross: sum.gross + line.taxable + line.discount,
      discount: sum.discount + line.discount,
      taxable: sum.taxable + line.taxable,
      vat: sum.vat + line.vat_amount,
      total: sum.total + line.line_total,
    }), { gross: 0, discount: 0, taxable: 0, vat: 0, total: 0 });

    const invoice = existing || {
      id: store.nextIds.invoice++,
      number: null,
      payments: [],
    };
    if (!invoice.number) {
      checkMonthlyLimit(issueDate);
      invoice.number = nextInvoiceNumber();
    }

    invoice.customer_id = data.customer_id ? Number(data.customer_id) : null;
    invoice.issue_date = issueDate;
    invoice.due_date = dueDate;
    invoice.status = data.status || 'draft';
    invoice.notes = String(data.notes || '');
    invoice.lines = lines;
    invoice.gross_total = totals.gross;
    invoice.discount_total = totals.discount;
    invoice.taxable_total = totals.taxable;
    invoice.vat_total = totals.vat;
    invoice.grand_total = totals.total;
    return invoice;
  }

  function isOverdue(invoice, balance) {
    return invoice.status === 'sent' && !!invoice.due_date &&
           balance > 0 && invoice.due_date < todayText();
  }

  /** يبني نفس الشكل الذي يُرجعه الخادم لفاتورة واحدة. */
  function invoicePayload(invoice) {
    const paid = invoice.payments.reduce((sum, p) => sum + p.amount, 0);
    const balance = invoice.grand_total - paid;
    const customer = store.customers.find((c) => c.id === invoice.customer_id) || null;

    const buckets = {};
    invoice.lines.forEach((line) => {
      const bucket = buckets[line.vat_rate_bp] || (buckets[line.vat_rate_bp] = { taxable: 0, vat: 0 });
      bucket.taxable += line.taxable;
      bucket.vat += line.vat_amount;
    });

    return Object.assign({}, invoice, {
      customer: customer,
      customer_name: customer ? customer.name : '',
      paid_total: paid,
      balance: balance,
      is_overdue: isOverdue(invoice, balance),
      vat_breakdown: Object.keys(buckets)
        .map(Number).sort((a, b) => b - a)
        .map((rate) => ({ rate_bp: rate, taxable: buckets[rate].taxable, vat: buckets[rate].vat })),
    });
  }

  function findInvoice(id) {
    const invoice = store.invoices.find((candidate) => candidate.id === Number(id));
    if (!invoice) throw new DemoError('الفاتورة غير موجودة');
    return invoice;
  }

  // ------------------------------------------------------- البيانات التجريبية

  /** مولّد أرقام شبه عشوائي بنواة ثابتة، حتى تتكرر نفس البيانات كل مرة. */
  function makeRandom(seed) {
    let value = seed;
    return function () {
      value = (value * 1103515245 + 12345) & 0x7fffffff;
      return value / 0x7fffffff;
    };
  }

  function seedDemoData() {
    const random = makeRandom(20260810);
    const pick = (list) => list[Math.floor(random() * list.length)];

    [
      { name: 'شركة الخليج للمقاولات', vat_number: 'OM1100998877', phone: '99887766', address: 'الخوير، مسقط' },
      { name: 'مؤسسة البحر الأزرق', vat_number: 'OM1100445566', phone: '95441122', address: 'صحار' },
      { name: 'مكتب الرؤية للاستشارات', vat_number: 'OM1100223344', phone: '91223344', address: 'روي، مسقط' },
      { name: 'بقالة الوادي', vat_number: '', phone: '92556677', address: 'نزوى' },
    ].forEach((data) => {
      store.customers.push(Object.assign(
        { id: store.nextIds.customer++, email: '', notes: '', archived: 0 }, data));
    });

    [
      { name: 'استشارة هندسية', unit: 'ساعة', unit_price: 12750, vat_category: 'standard' },
      { name: 'تصميم هوية بصرية', unit: 'مشروع', unit_price: 250000, vat_category: 'standard' },
      { name: 'صيانة دورية', unit: 'زيارة', unit_price: 35500, vat_category: 'standard' },
      { name: 'توريد أثاث مكتبي', unit: 'قطعة', unit_price: 45500, vat_category: 'standard' },
      { name: 'خدمة تصدير', unit: 'شحنة', unit_price: 500000, vat_category: 'zero' },
    ].forEach((data) => {
      store.items.push(Object.assign({ id: store.nextIds.item++, archived: 0 }, data));
    });

    const now = new Date();
    for (let monthsAgo = 5; monthsAgo >= 0; monthsAgo--) {
      const count = 3 + Math.floor(random() * 4);
      for (let n = 0; n < count; n++) {
        const issue = new Date(now.getFullYear(), now.getMonth() - monthsAgo,
                               1 + Math.floor(random() * 25));
        if (issue > now) continue;
        const issueText = new Date(issue.getTime() - issue.getTimezoneOffset() * 60000)
          .toISOString().slice(0, 10);
        const due = new Date(issue.getTime() + 30 * 86400000);
        const dueText = new Date(due.getTime() - due.getTimezoneOffset() * 60000)
          .toISOString().slice(0, 10);

        const lines = [];
        const lineCount = 1 + Math.floor(random() * 3);
        for (let l = 0; l < lineCount; l++) {
          const item = pick(store.items);
          lines.push({
            description: item.name,
            unit: item.unit,
            quantity: String(pick([1, 1, 2, 3, '2.5'])),
            unit_price: formatMoney(item.unit_price),
            vat_category: item.vat_category,
          });
        }

        const invoice = buildInvoice({
          customer_id: pick(store.customers).id,
          issue_date: issueText,
          due_date: dueText,
          status: 'sent',
          notes: 'الدفع خلال 30 يومًا من تاريخ الفاتورة.',
          lines: lines,
        }, null);
        store.invoices.push(invoice);

        const roll = random();
        if (monthsAgo > 0 && roll < 0.8) {
          invoice.payments.push({
            id: store.nextIds.payment++, invoice_id: invoice.id,
            amount: invoice.grand_total, paid_on: issueText,
            method: pick(['cash', 'bank', 'cheque']), note: '',
          });
          invoice.status = 'paid';
        } else if (roll < 0.9) {
          invoice.payments.push({
            id: store.nextIds.payment++, invoice_id: invoice.id,
            amount: Math.round(invoice.grand_total / 2), paid_on: issueText,
            method: 'bank', note: 'دفعة أولى',
          });
        }
      }
    }
    store.invoices.sort((a, b) => (a.issue_date < b.issue_date ? -1 : 1));
  }

  // ------------------------------------------------------- التقارير

  const COUNTED = ['sent', 'paid'];

  function dashboardPayload() {
    const month = todayText().slice(0, 7);
    const counted = store.invoices.filter((inv) => COUNTED.indexOf(inv.status) >= 0);

    const monthly = {};
    counted.forEach((inv) => {
      const key = inv.issue_date.slice(0, 7);
      const bucket = monthly[key] || (monthly[key] = { month: key, taxable: 0, vat: 0, total: 0, count: 0 });
      bucket.taxable += inv.taxable_total;
      bucket.vat += inv.vat_total;
      bucket.total += inv.grand_total;
      bucket.count += 1;
    });

    const thisMonth = monthly[month] || { taxable: 0, vat: 0, total: 0, count: 0 };
    const sent = store.invoices.filter((inv) => inv.status === 'sent').map(invoicePayload);
    const overdue = sent.filter((inv) => inv.is_overdue);

    const byCustomer = {};
    counted.forEach((inv) => {
      if (!inv.customer_id) return;
      const bucket = byCustomer[inv.customer_id] ||
        (byCustomer[inv.customer_id] = { id: inv.customer_id, name: '', invoice_count: 0, total: 0 });
      const customer = store.customers.find((c) => c.id === inv.customer_id);
      bucket.name = customer ? customer.name : '—';
      bucket.invoice_count += 1;
      bucket.total += inv.grand_total;
    });

    return {
      summary: {
        month: month,
        month_sales_taxable: thisMonth.taxable,
        month_sales_vat: thisMonth.vat,
        month_sales_total: thisMonth.total,
        month_invoice_count: thisMonth.count,
        outstanding_balance: sent.reduce((sum, inv) => sum + inv.balance, 0),
        outstanding_count: sent.length,
        overdue_count: overdue.length,
        overdue_balance: overdue.reduce((sum, inv) => sum + inv.balance, 0),
        draft_count: store.invoices.filter((inv) => inv.status === 'draft').length,
      },
      monthly: Object.keys(monthly).sort().slice(-12).map((key) => monthly[key]),
      top_customers: Object.keys(byCustomer)
        .map((key) => byCustomer[key]).sort((a, b) => b.total - a.total).slice(0, 5),
      recent: listInvoices({}).slice(0, 8),
    };
  }

  function vatReturnPayload(from, to) {
    const buckets = {};
    let invoiceCount = 0;
    store.invoices.forEach((inv) => {
      if (COUNTED.indexOf(inv.status) < 0) return;
      if (inv.issue_date < from || inv.issue_date > to) return;
      invoiceCount += 1;
      inv.lines.forEach((line) => {
        const key = line.vat_category + '|' + line.vat_rate_bp;
        const bucket = buckets[key] ||
          (buckets[key] = { category: line.vat_category, rate_bp: line.vat_rate_bp, taxable: 0, vat: 0 });
        bucket.taxable += line.taxable;
        bucket.vat += line.vat_amount;
      });
    });
    const breakdown = Object.keys(buckets).map((key) => buckets[key])
      .sort((a, b) => b.rate_bp - a.rate_bp);
    return {
      date_from: from, date_to: to, invoice_count: invoiceCount, breakdown: breakdown,
      total_taxable: breakdown.reduce((sum, b) => sum + b.taxable, 0),
      total_vat: breakdown.reduce((sum, b) => sum + b.vat, 0),
    };
  }

  function listInvoices(filters) {
    const statusFilter = filters.status;
    const search = (filters.q || '').trim();
    return store.invoices
      .map(invoicePayload)
      .filter((inv) => !statusFilter || inv.status === statusFilter)
      .filter((inv) => !search ||
        inv.number.indexOf(search) >= 0 || (inv.customer_name || '').indexOf(search) >= 0)
      .sort((a, b) => (a.issue_date === b.issue_date
        ? b.id - a.id : (a.issue_date < b.issue_date ? 1 : -1)));
  }

  function csvExport(from, to) {
    const labels = { draft: 'مسودة', sent: 'صادرة', paid: 'مدفوعة', cancelled: 'ملغاة' };
    const rows = [[
      'رقم الفاتورة', 'تاريخ الإصدار', 'تاريخ الاستحقاق', 'الحالة', 'العميل',
      'الرقم الضريبي للعميل', 'المبلغ قبل الضريبة', 'ضريبة القيمة المضافة',
      'الإجمالي', 'المسدّد', 'المتبقي',
    ]];
    store.invoices
      .filter((inv) => inv.issue_date >= from && inv.issue_date <= to)
      .forEach((inv) => {
        const payload = invoicePayload(inv);
        rows.push([
          payload.number, payload.issue_date, payload.due_date,
          labels[payload.status] || payload.status,
          payload.customer ? payload.customer.name : '',
          payload.customer ? payload.customer.vat_number : '',
          formatMoney(payload.taxable_total), formatMoney(payload.vat_total),
          formatMoney(payload.grand_total), formatMoney(payload.paid_total),
          formatMoney(payload.balance),
        ]);
      });
    return '﻿' + rows
      .map((row) => row.map((cell) => '"' + String(cell).replace(/"/g, '""') + '"').join(','))
      .join('\r\n');
  }

  // ------------------------------------------------------- توجيه الطلبات

  function route(method, path, query, body) {
    // --- المصادقة
    if (path === '/api/me') {
      if (!store.loggedIn) return [401, { error: 'يجب تسجيل الدخول' }];
      return [200, { user: store.user, org: orgPayload() }];
    }
    if (path === '/api/login' && method === 'POST') {
      store.loggedIn = true;
      return [200, { user: store.user, org: orgPayload() }];
    }
    if (path === '/api/register' && method === 'POST') {
      store.loggedIn = true;
      if (body.org_name) store.org.name = String(body.org_name);
      return [200, { user: store.user, org: orgPayload() }];
    }
    if (path === '/api/logout' && method === 'POST') {
      store.loggedIn = false;
      return [200, { ok: true }];
    }
    if (!store.loggedIn) return [401, { error: 'يجب تسجيل الدخول' }];

    // --- المنشأة
    if (path === '/api/org' && method === 'PUT') {
      ['name', 'vat_number', 'cr_number', 'address', 'phone', 'email', 'invoice_prefix']
        .forEach((field) => {
          if (body[field] !== undefined) store.org[field] = String(body[field]).trim();
        });
      if (!store.org.name) throw new DemoError('اسم المنشأة مطلوب');
      if (!store.org.invoice_prefix) store.org.invoice_prefix = 'INV';
      return [200, { org: orgPayload() }];
    }
    if (path === '/api/org/plan' && method === 'POST') {
      if (!(body.plan in PLAN_LIMITS)) throw new DemoError('باقة غير معروفة');
      store.org.plan = body.plan;
      return [200, { org: orgPayload() }];
    }

    // --- العملاء
    if (path === '/api/customers' && method === 'GET') {
      return [200, { customers: store.customers.filter((c) => !c.archived) }];
    }
    if (path === '/api/customers' && method === 'POST') {
      const name = String(body.name || '').trim();
      if (!name) throw new DemoError('اسم العميل مطلوب');
      const limit = PLAN_LIMITS[store.org.plan].customers;
      if (limit !== null && store.customers.filter((c) => !c.archived).length >= limit) {
        throw new DemoError('الباقة المجانية تسمح بـ ' + limit +
          ' عميلًا. رقّ إلى الباقة الاحترافية للمزيد.');
      }
      const customer = {
        id: store.nextIds.customer++, name: name, archived: 0,
        vat_number: String(body.vat_number || ''), phone: String(body.phone || ''),
        email: String(body.email || ''), address: String(body.address || ''),
        notes: String(body.notes || ''),
      };
      store.customers.push(customer);
      return [200, { customer: customer }];
    }

    let match = path.match(/^\/api\/customers\/(\d+)$/);
    if (match) {
      const customer = store.customers.find((c) => c.id === Number(match[1]));
      if (!customer) throw new DemoError('العميل غير موجود');
      if (method === 'PUT') {
        const name = String(body.name || '').trim();
        if (!name) throw new DemoError('اسم العميل مطلوب');
        Object.assign(customer, {
          name: name, vat_number: String(body.vat_number || ''),
          phone: String(body.phone || ''), email: String(body.email || ''),
          address: String(body.address || ''), notes: String(body.notes || ''),
        });
        return [200, { customer: customer }];
      }
      if (method === 'DELETE') { customer.archived = 1; return [200, { ok: true }]; }
    }

    // --- الأصناف
    if (path === '/api/items' && method === 'GET') {
      return [200, { items: store.items.filter((item) => !item.archived) }];
    }
    if (path === '/api/items' && method === 'POST') {
      const name = String(body.name || '').trim();
      if (!name) throw new DemoError('اسم الصنف مطلوب');
      const item = {
        id: store.nextIds.item++, name: name, archived: 0,
        unit: String(body.unit || 'قطعة').trim() || 'قطعة',
        unit_price: parseAmount(body.unit_price),
        vat_category: (body.vat_category in RATES) ? body.vat_category : 'standard',
      };
      store.items.push(item);
      return [200, { item: item }];
    }

    match = path.match(/^\/api\/items\/(\d+)$/);
    if (match) {
      const item = store.items.find((candidate) => candidate.id === Number(match[1]));
      if (!item) throw new DemoError('الصنف غير موجود');
      if (method === 'PUT') {
        const name = String(body.name || '').trim();
        if (!name) throw new DemoError('اسم الصنف مطلوب');
        Object.assign(item, {
          name: name, unit: String(body.unit || 'قطعة').trim() || 'قطعة',
          unit_price: parseAmount(body.unit_price),
          vat_category: (body.vat_category in RATES) ? body.vat_category : 'standard',
        });
        return [200, { item: item }];
      }
      if (method === 'DELETE') { item.archived = 1; return [200, { ok: true }]; }
    }

    // --- الفواتير
    if (path === '/api/invoices' && method === 'GET') {
      return [200, { invoices: listInvoices(query) }];
    }
    if (path === '/api/invoices' && method === 'POST') {
      const invoice = buildInvoice(body, null);
      store.invoices.push(invoice);
      return [200, { invoice: invoicePayload(invoice) }];
    }

    match = path.match(/^\/api\/invoices\/(\d+)$/);
    if (match) {
      const invoice = findInvoice(match[1]);
      if (method === 'GET') return [200, { invoice: invoicePayload(invoice) }];
      if (method === 'PUT') {
        if (invoice.status === 'paid' || invoice.status === 'cancelled') {
          throw new DemoError('لا يمكن تعديل فاتورة مدفوعة أو ملغاة');
        }
        buildInvoice(body, invoice);
        return [200, { invoice: invoicePayload(invoice) }];
      }
      if (method === 'DELETE') {
        if (invoice.status !== 'draft') {
          throw new DemoError('لا يمكن حذف فاتورة صادرة — استخدم الإلغاء بدلًا من ذلك');
        }
        store.invoices.splice(store.invoices.indexOf(invoice), 1);
        return [200, { ok: true }];
      }
    }

    match = path.match(/^\/api\/invoices\/(\d+)\/status$/);
    if (match && method === 'POST') {
      const invoice = findInvoice(match[1]);
      invoice.status = body.status;
      return [200, { invoice: invoicePayload(invoice) }];
    }

    match = path.match(/^\/api\/invoices\/(\d+)\/payments$/);
    if (match && method === 'POST') {
      const invoice = findInvoice(match[1]);
      if (invoice.status === 'cancelled') {
        throw new DemoError('لا يمكن تسجيل دفعة على فاتورة ملغاة');
      }
      const payload = invoicePayload(invoice);
      const amount = parseAmount(body.amount);
      if (amount <= 0) throw new DemoError('مبلغ الدفعة يجب أن يكون أكبر من صفر');
      if (amount > payload.balance) {
        throw new DemoError('مبلغ الدفعة أكبر من المتبقي على الفاتورة');
      }
      invoice.payments.push({
        id: store.nextIds.payment++, invoice_id: invoice.id, amount: amount,
        paid_on: body.paid_on || todayText(), method: body.method || 'cash',
        note: String(body.note || ''),
      });
      if (payload.balance - amount <= 0) invoice.status = 'paid';
      return [200, { invoice: invoicePayload(invoice) }];
    }

    match = path.match(/^\/api\/invoices\/(\d+)\/payments\/(\d+)$/);
    if (match && method === 'DELETE') {
      const invoice = findInvoice(match[1]);
      const index = invoice.payments.findIndex((p) => p.id === Number(match[2]));
      if (index < 0) throw new DemoError('الدفعة غير موجودة');
      invoice.payments.splice(index, 1);
      if (invoice.status === 'paid' &&
          invoice.payments.reduce((sum, p) => sum + p.amount, 0) < invoice.grand_total) {
        invoice.status = 'sent';
      }
      return [200, { invoice: invoicePayload(invoice) }];
    }

    // --- التقارير
    if (path === '/api/reports/dashboard') return [200, dashboardPayload()];
    if (path === '/api/reports/vat') {
      return [200, { vat_return: vatReturnPayload(query.from, query.to) }];
    }

    return [404, { error: 'المسار غير موجود' }];
  }

  // ------------------------------------------------------- اعتراض الطلبات

  const realFetch = window.fetch.bind(window);

  window.fetch = function (input, options) {
    const url = typeof input === 'string' ? input : input.url;
    if (url.indexOf('/api/') !== 0) return realFetch(input, options);

    const config = options || {};
    const parsed = new URL(url, window.location.origin);
    const query = {};
    parsed.searchParams.forEach((value, key) => { query[key] = value; });

    let body = {};
    if (config.body) {
      try { body = JSON.parse(config.body); } catch (error) { body = {}; }
    }

    let status = 200;
    let payload;
    try {
      const result = route(config.method || 'GET', parsed.pathname, query, body);
      status = result[0];
      payload = result[1];
    } catch (error) {
      status = 400;
      payload = { error: error.message || 'حدث خطأ غير متوقع' };
    }

    return Promise.resolve(new Response(JSON.stringify(payload), {
      status: status,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    }));
  };

  // تصدير Excel في الخادم الحقيقي تنزيل من رابط. هنا نولّد الملف في المتصفح،
  // فنعترض الضغطة قبل أن يصل إليها معالج الواجهة.
  document.addEventListener('click', function (event) {
    const button = event.target.closest && event.target.closest('#r-export');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const from = document.getElementById('r-from').value;
    const to = document.getElementById('r-to').value;
    const blob = new Blob([csvExport(from, to)], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'invoices-' + from + '-to-' + to + '.csv';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
  }, true);

  seedDemoData();
})();
