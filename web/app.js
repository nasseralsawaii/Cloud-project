/* نظام الفوترة — منطق الواجهة.
   جافاسكربت خالص بلا أي مكتبة خارجية، حتى يعمل البرنامج بدون إنترنت. */

'use strict';

// ============================================================ الحالة

const state = {
  user: null,
  org: null,
  view: 'dashboard',
  customers: [],
  items: [],
  editor: null,   // الفاتورة قيد التحرير
  viewing: null,  // الفاتورة المعروضة
};

const BAISA = 1000;

const STATUS_LABELS = {
  draft: 'مسودة', sent: 'صادرة', paid: 'مدفوعة', cancelled: 'ملغاة',
};

const VAT_LABELS = {
  standard: 'أساسية 5%', zero: 'صفرية 0%', exempt: 'معفاة',
};

const PAYMENT_METHODS = {
  cash: 'نقدًا', bank: 'تحويل بنكي', card: 'بطاقة', cheque: 'شيك', other: 'أخرى',
};

const MONTH_NAMES = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
                     'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];

// ============================================================ أدوات

/** يهرّب النص قبل إدراجه في HTML. كل قيمة قادمة من المستخدم تمر من هنا. */
function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** يعرض مبلغًا بالبيسة على هيئة نص بثلاث خانات عشرية. */
function money(baisa) {
  const negative = baisa < 0;
  const value = Math.abs(Math.round(baisa || 0));
  const rials = Math.floor(value / BAISA);
  const fraction = String(value % BAISA).padStart(3, '0');
  return (negative ? '-' : '') + rials.toLocaleString('en-US') + '.' + fraction;
}

/** يعرض المبلغ مع رمز العملة داخل عنصر يحافظ على اتجاه الأرقام. */
function amountHtml(baisa) {
  return `<span class="num">${esc(money(baisa))}</span> ر.ع`;
}

function qty(milli) {
  const value = (milli || 0) / BAISA;
  return Number.isInteger(value) ? String(value) : String(parseFloat(value.toFixed(3)));
}

function today() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function addDays(dateText, days) {
  const date = new Date(dateText + 'T00:00:00');
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function monthLabel(yyyymm) {
  const [year, month] = yyyymm.split('-');
  return `${MONTH_NAMES[parseInt(month, 10) - 1]} ${year}`;
}

function statusBadge(invoice) {
  if (invoice.is_overdue) return '<span class="badge badge-overdue">متأخرة</span>';
  const status = invoice.status;
  return `<span class="badge badge-${esc(status)}">${esc(STATUS_LABELS[status] || status)}</span>`;
}

function toast(message, isError) {
  const element = document.getElementById('toast');
  element.textContent = message;
  element.className = 'toast' + (isError ? ' error' : '');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.add('hidden'), 3600);
}

// ============================================================ الاتصال بالخادم

async function api(path, options = {}) {
  const config = { method: options.method || 'GET', headers: {}, credentials: 'same-origin' };
  if (options.body !== undefined) {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(path, config);
  } catch (error) {
    throw new Error('تعذّر الاتصال بالخادم. تأكد أن البرنامج ما زال يعمل.');
  }

  if (response.status === 401 && state.user) {
    // انتهت الجلسة أثناء الاستخدام
    state.user = null;
    showAuth();
    throw new Error('انتهت الجلسة، سجّل الدخول من جديد');
  }

  const text = await response.text();
  let payload = {};
  if (text) {
    try { payload = JSON.parse(text); } catch (error) { payload = {}; }
  }

  if (!response.ok) throw new Error(payload.error || 'حدث خطأ غير متوقع');
  return payload;
}

// ============================================================ الدخول

function showAuth() {
  document.getElementById('app').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
}

function showApp() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('org-name').textContent = state.org.name;
  document.getElementById('user-email').textContent = state.user.email;

  const badge = document.getElementById('plan-badge');
  const limits = state.org.plan_limits;
  badge.textContent = 'الباقة ' + (limits ? limits.label : '');
}

function authError(message) {
  const box = document.getElementById('auth-error');
  if (!message) { box.classList.add('hidden'); return; }
  box.textContent = message;
  box.classList.remove('hidden');
}

function setupAuthScreen() {
  document.querySelectorAll('[data-auth-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.authTab;
      document.querySelectorAll('[data-auth-tab]').forEach((t) => t.classList.toggle('active', t === tab));
      document.getElementById('login-form').classList.toggle('hidden', target !== 'login');
      document.getElementById('register-form').classList.toggle('hidden', target !== 'register');
      authError('');
    });
  });

  document.getElementById('login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    authError('');
    const data = Object.fromEntries(new FormData(event.target));
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    try {
      const result = await api('/api/login', { method: 'POST', body: data });
      state.user = result.user;
      state.org = result.org;
      await afterLogin();
    } catch (error) {
      authError(error.message);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById('register-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    authError('');
    const data = Object.fromEntries(new FormData(event.target));
    const button = event.target.querySelector('button[type=submit]');
    button.disabled = true;
    try {
      const result = await api('/api/register', { method: 'POST', body: data });
      state.user = result.user;
      state.org = result.org;
      await afterLogin();
      toast('أهلًا بك! أكمل بيانات منشأتك من الإعدادات لتظهر على فواتيرك.');
    } catch (error) {
      authError(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

async function afterLogin() {
  await refreshLookups();
  showApp();
  navigate('dashboard');
}

async function refreshLookups() {
  const [customers, items] = await Promise.all([api('/api/customers'), api('/api/items')]);
  state.customers = customers.customers;
  state.items = items.items;
}

// ============================================================ التنقّل

function navigate(view) {
  state.view = view;
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.view === view);
  });
  window.scrollTo(0, 0);
  render();
}

const VIEWS = {
  dashboard: renderDashboard,
  invoices: renderInvoices,
  invoiceEditor: renderInvoiceEditor,
  invoiceView: renderInvoiceView,
  customers: renderCustomers,
  items: renderItems,
  reports: renderReports,
  settings: renderSettings,
};

function render() {
  const container = document.getElementById('view-container');
  container.innerHTML = '<div class="empty">جارٍ التحميل…</div>';
  const view = VIEWS[state.view];
  Promise.resolve(view(container)).catch((error) => {
    container.innerHTML = `<div class="error-box">${esc(error.message)}</div>`;
  });
}

// ============================================================ الرئيسية

async function renderDashboard(container) {
  const data = await api('/api/reports/dashboard');
  const summary = data.summary;

  const limits = state.org.plan_limits;
  let limitNotice = '';
  if (limits.invoices_per_month !== null) {
    const used = summary.month_invoice_count + summary.draft_count;
    const remaining = Math.max(0, limits.invoices_per_month - used);
    limitNotice = `<div class="notice">
      الباقة المجانية: بقي لك <strong>${remaining}</strong> من ${limits.invoices_per_month} فواتير هذا الشهر.
      <button class="btn btn-small btn-primary" onclick="upgradePlan()">الترقية للاحترافية</button>
    </div>`;
  }

  const maxTotal = Math.max(...data.monthly.map((m) => m.total), 1);
  const chart = data.monthly.length
    ? `<div class="chart">${data.monthly.map((month) => `
        <div class="chart-col" title="${esc(monthLabel(month.month))}: ${esc(money(month.total))} ر.ع">
          <div class="chart-bar" style="height:${Math.max(3, (month.total / maxTotal) * 130)}px"></div>
          <div class="chart-label">${esc(monthLabel(month.month).split(' ')[0])}</div>
        </div>`).join('')}</div>`
    : '<div class="empty">لا توجد مبيعات مسجّلة بعد.</div>';

  container.innerHTML = `
    <div class="page-head">
      <h2>الرئيسية</h2>
      <div class="page-actions">
        <button class="btn btn-primary" onclick="newInvoice()">+ فاتورة جديدة</button>
      </div>
    </div>

    ${limitNotice}

    <div class="stat-grid">
      <div class="stat">
        <div class="stat-label">مبيعات ${esc(monthLabel(summary.month))}</div>
        <div class="stat-value">${amountHtml(summary.month_sales_total)}</div>
        <div class="stat-note">${summary.month_invoice_count} فاتورة صادرة</div>
      </div>
      <div class="stat">
        <div class="stat-label">ضريبة محصّلة هذا الشهر</div>
        <div class="stat-value">${amountHtml(summary.month_sales_vat)}</div>
        <div class="stat-note">تُورَّد لجهاز الضرائب</div>
      </div>
      <div class="stat">
        <div class="stat-label">مستحق على العملاء</div>
        <div class="stat-value">${amountHtml(summary.outstanding_balance)}</div>
        <div class="stat-note">${summary.outstanding_count} فاتورة غير مسدّدة</div>
      </div>
      <div class="stat ${summary.overdue_count ? 'alert' : ''}">
        <div class="stat-label">متأخرة عن السداد</div>
        <div class="stat-value">${amountHtml(summary.overdue_balance)}</div>
        <div class="stat-note">${summary.overdue_count} فاتورة تجاوزت الاستحقاق</div>
      </div>
    </div>

    <div class="card">
      <h3>المبيعات الشهرية</h3>
      ${chart}
    </div>

    <div class="card">
      <h3>آخر الفواتير</h3>
      ${invoiceTable(data.recent)}
    </div>

    ${data.top_customers.length ? `<div class="card">
      <h3>أكثر العملاء شراءً</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>العميل</th><th>عدد الفواتير</th><th class="text-end">الإجمالي</th></tr></thead>
        <tbody>${data.top_customers.map((customer) => `<tr>
          <td>${esc(customer.name)}</td>
          <td>${customer.invoice_count}</td>
          <td class="text-end">${amountHtml(customer.total)}</td>
        </tr>`).join('')}</tbody>
      </table></div>
    </div>` : ''}
  `;
}

// ============================================================ الفواتير

function invoiceTable(list) {
  if (!list.length) {
    return '<div class="empty"><span class="empty-icon">🧾</span>لا توجد فواتير بعد.</div>';
  }
  return `<div class="table-wrap"><table>
    <thead><tr>
      <th>الرقم</th><th>العميل</th><th>التاريخ</th><th>الحالة</th>
      <th class="text-end">الإجمالي</th><th class="text-end">المتبقي</th>
    </tr></thead>
    <tbody>${list.map((invoice) => `
      <tr class="clickable" onclick="openInvoice(${invoice.id})">
        <td class="nowrap"><strong>${esc(invoice.number)}</strong></td>
        <td>${esc(invoice.customer_name || '—')}</td>
        <td class="nowrap"><span class="num">${esc(invoice.issue_date)}</span></td>
        <td>${statusBadge(invoice)}</td>
        <td class="text-end nowrap">${amountHtml(invoice.grand_total)}</td>
        <td class="text-end nowrap">${invoice.balance > 0 ? amountHtml(invoice.balance) : '—'}</td>
      </tr>`).join('')}</tbody>
  </table></div>`;
}

async function renderInvoices(container) {
  const filter = renderInvoices.filter || {};
  const params = new URLSearchParams();
  if (filter.status) params.set('status', filter.status);
  if (filter.q) params.set('q', filter.q);
  params.set('limit', '200');

  const data = await api('/api/invoices?' + params.toString());

  container.innerHTML = `
    <div class="page-head">
      <h2>الفواتير</h2>
      <div class="page-actions">
        <input type="search" id="invoice-search" placeholder="بحث برقم الفاتورة أو العميل"
               value="${esc(filter.q || '')}" style="width:230px">
        <select id="invoice-status" style="width:150px">
          <option value="">كل الحالات</option>
          ${Object.entries(STATUS_LABELS).map(([value, label]) =>
            `<option value="${value}" ${filter.status === value ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
        <button class="btn btn-primary" onclick="newInvoice()">+ فاتورة جديدة</button>
      </div>
    </div>
    <div class="card">${invoiceTable(data.invoices)}</div>
  `;

  const search = document.getElementById('invoice-search');
  let timer = null;
  search.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      renderInvoices.filter = { ...filter, q: search.value.trim() };
      render();
    }, 320);
  });

  document.getElementById('invoice-status').addEventListener('change', (event) => {
    renderInvoices.filter = { ...filter, status: event.target.value };
    render();
  });
}

// ---------------------------------------------------------- محرر الفاتورة

function blankLine() {
  return { description: '', unit: 'قطعة', quantity: '1', unit_price: '', discount: '', vat_category: 'standard' };
}

function newInvoice() {
  state.editor = {
    id: null,
    customer_id: '',
    issue_date: today(),
    due_date: addDays(today(), 30),
    status: 'sent',
    notes: '',
    lines: [blankLine()],
  };
  navigate('invoiceEditor');
}

async function editInvoice(id) {
  const data = await api('/api/invoices/' + id);
  const invoice = data.invoice;
  state.editor = {
    id: invoice.id,
    customer_id: invoice.customer_id || '',
    issue_date: invoice.issue_date,
    due_date: invoice.due_date,
    status: invoice.status,
    notes: invoice.notes,
    lines: invoice.lines.map((line) => ({
      description: line.description,
      unit: line.unit,
      quantity: qty(line.quantity),
      unit_price: money(line.unit_price),
      discount: line.discount ? money(line.discount) : '',
      vat_category: line.vat_category,
    })),
  };
  navigate('invoiceEditor');
}

/** يحسب مجاميع المعاينة في المتصفح. الخادم يعيد الحساب دائمًا عند الحفظ. */
function previewTotals(lines) {
  let taxable = 0;
  let vat = 0;
  lines.forEach((line) => {
    const quantity = Math.round((parseFloat(line.quantity) || 0) * BAISA);
    const price = Math.round((parseFloat(line.unit_price) || 0) * BAISA);
    const discount = Math.round((parseFloat(line.discount) || 0) * BAISA);
    const gross = Math.round((price * quantity) / BAISA);
    const net = Math.max(0, gross - Math.min(discount, gross));
    const rate = line.vat_category === 'standard' ? 500 : 0;
    taxable += net;
    vat += Math.round((net * rate) / 10000);
  });
  return { taxable, vat, total: taxable + vat };
}

function renderInvoiceEditor(container) {
  const editor = state.editor;
  const totals = previewTotals(editor.lines);

  container.innerHTML = `
    <div class="page-head">
      <h2>${editor.id ? 'تعديل فاتورة' : 'فاتورة جديدة'}</h2>
      <div class="page-actions">
        <button class="btn" onclick="navigate('invoices')">إلغاء</button>
        <button class="btn btn-primary" id="save-invoice">حفظ الفاتورة</button>
      </div>
    </div>

    <div class="card">
      <div class="form-row">
        <label>العميل
          <select id="f-customer">
            <option value="">— بدون عميل محدد —</option>
            ${state.customers.map((customer) => `<option value="${customer.id}"
              ${String(editor.customer_id) === String(customer.id) ? 'selected' : ''}>${esc(customer.name)}</option>`).join('')}
          </select>
        </label>
        <label>الحالة
          <select id="f-status">
            <option value="draft" ${editor.status === 'draft' ? 'selected' : ''}>مسودة</option>
            <option value="sent" ${editor.status === 'sent' ? 'selected' : ''}>صادرة</option>
          </select>
        </label>
      </div>
      <div class="form-row" style="margin-top:14px">
        <label>تاريخ الإصدار
          <input type="date" id="f-issue" value="${esc(editor.issue_date)}">
        </label>
        <label>تاريخ الاستحقاق
          <input type="date" id="f-due" value="${esc(editor.due_date)}">
        </label>
      </div>
    </div>

    <div class="card">
      <h3>البنود</h3>
      <div class="table-wrap">
        <table class="line-table">
          <thead><tr>
            <th style="min-width:190px">الوصف</th>
            <th style="width:90px">الكمية</th>
            <th style="width:80px">الوحدة</th>
            <th style="width:120px">سعر الوحدة</th>
            <th style="width:110px">الخصم</th>
            <th style="width:130px">الضريبة</th>
            <th style="width:120px" class="text-end">الإجمالي</th>
            <th style="width:40px"></th>
          </tr></thead>
          <tbody id="lines-body">${editor.lines.map(lineRow).join('')}</tbody>
        </table>
      </div>

      <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap">
        <button class="btn btn-small" onclick="addLine()">+ إضافة بند</button>
        ${state.items.length ? `<select id="item-picker" style="width:220px">
          <option value="">إضافة من الأصناف المحفوظة…</option>
          ${state.items.map((item) => `<option value="${item.id}">${esc(item.name)} — ${esc(money(item.unit_price))}</option>`).join('')}
        </select>` : ''}
      </div>

      <div class="totals-box">
        <div class="totals-row"><span>المجموع قبل الضريبة</span><span data-total="taxable">${amountHtml(totals.taxable)}</span></div>
        <div class="totals-row"><span>ضريبة القيمة المضافة</span><span data-total="vat">${amountHtml(totals.vat)}</span></div>
        <div class="totals-row grand"><span>الإجمالي</span><span data-total="total">${amountHtml(totals.total)}</span></div>
      </div>
    </div>

    <div class="card">
      <label>ملاحظات تظهر على الفاتورة
        <textarea id="f-notes" placeholder="شروط الدفع، رقم الحساب البنكي، شكر للعميل…">${esc(editor.notes)}</textarea>
      </label>
    </div>
  `;

  bindEditor();
}

function lineRow(line, index) {
  return `<tr data-index="${index}">
    <td><input type="text" data-field="description" value="${esc(line.description)}" placeholder="وصف السلعة أو الخدمة"></td>
    <td><input type="text" inputmode="decimal" class="amount" data-field="quantity" value="${esc(line.quantity)}"></td>
    <td><input type="text" data-field="unit" value="${esc(line.unit)}"></td>
    <td><input type="text" inputmode="decimal" class="amount" data-field="unit_price" value="${esc(line.unit_price)}" placeholder="0.000"></td>
    <td><input type="text" inputmode="decimal" class="amount" data-field="discount" value="${esc(line.discount)}" placeholder="0.000"></td>
    <td><select data-field="vat_category">
      ${Object.entries(VAT_LABELS).map(([value, label]) =>
        `<option value="${value}" ${line.vat_category === value ? 'selected' : ''}>${label}</option>`).join('')}
    </select></td>
    <td class="text-end nowrap">${amountHtml(previewTotals([line]).total)}</td>
    <td><button class="btn btn-ghost btn-small" onclick="removeLine(${index})" title="حذف البند">✕</button></td>
  </tr>`;
}

function bindEditor() {
  document.getElementById('lines-body').addEventListener('input', (event) => {
    const field = event.target.dataset.field;
    if (!field) return;
    const index = parseInt(event.target.closest('tr').dataset.index, 10);
    state.editor.lines[index][field] = event.target.value;
    updateEditorTotals(index);
  });

  document.getElementById('lines-body').addEventListener('change', (event) => {
    if (event.target.dataset.field === 'vat_category') {
      const index = parseInt(event.target.closest('tr').dataset.index, 10);
      state.editor.lines[index].vat_category = event.target.value;
      updateEditorTotals(index);
    }
  });

  const picker = document.getElementById('item-picker');
  if (picker) {
    picker.addEventListener('change', () => {
      const item = state.items.find((candidate) => String(candidate.id) === picker.value);
      picker.value = '';
      if (!item) return;
      // نستبدل البند الفارغ الأول بدل إضافة صف زائد
      const blank = state.editor.lines.findIndex((line) => !line.description && !line.unit_price);
      const line = {
        description: item.name, unit: item.unit, quantity: '1',
        unit_price: money(item.unit_price), discount: '', vat_category: item.vat_category,
      };
      if (blank >= 0) state.editor.lines[blank] = line;
      else state.editor.lines.push(line);
      render();
    });
  }

  ['customer', 'status', 'issue', 'due', 'notes'].forEach((name) => {
    const map = { customer: 'customer_id', status: 'status', issue: 'issue_date', due: 'due_date', notes: 'notes' };
    const element = document.getElementById('f-' + name);
    element.addEventListener('change', () => { state.editor[map[name]] = element.value; });
  });

  document.getElementById('save-invoice').addEventListener('click', saveInvoice);
}

/** يحدّث إجمالي الصف والمجاميع دون إعادة رسم الجدول، حتى لا يفقد الحقل التركيز. */
function updateEditorTotals(index) {
  const row = document.querySelector(`#lines-body tr[data-index="${index}"]`);
  if (row) {
    row.querySelector('td.text-end').innerHTML = amountHtml(previewTotals([state.editor.lines[index]]).total);
  }

  const totals = previewTotals(state.editor.lines);
  ['taxable', 'vat', 'total'].forEach((key) => {
    const cell = document.querySelector(`.totals-box [data-total="${key}"]`);
    if (cell) cell.innerHTML = amountHtml(totals[key]);
  });
}

function addLine() {
  state.editor.lines.push(blankLine());
  render();
}

function removeLine(index) {
  if (state.editor.lines.length === 1) {
    toast('الفاتورة تحتاج بندًا واحدًا على الأقل', true);
    return;
  }
  state.editor.lines.splice(index, 1);
  render();
}

async function saveInvoice() {
  const editor = state.editor;
  const button = document.getElementById('save-invoice');
  button.disabled = true;

  const payload = {
    customer_id: editor.customer_id || null,
    issue_date: editor.issue_date,
    due_date: editor.due_date,
    status: editor.status,
    notes: document.getElementById('f-notes').value,
    lines: editor.lines,
  };

  try {
    const result = editor.id
      ? await api('/api/invoices/' + editor.id, { method: 'PUT', body: payload })
      : await api('/api/invoices', { method: 'POST', body: payload });
    toast('تم حفظ الفاتورة ' + result.invoice.number);
    state.viewing = result.invoice;
    state.editor = null;
    navigate('invoiceView');
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

// ---------------------------------------------------------- عرض الفاتورة

async function openInvoice(id) {
  const data = await api('/api/invoices/' + id);
  state.viewing = data.invoice;
  navigate('invoiceView');
}

function renderInvoiceView(container) {
  const invoice = state.viewing;
  const org = state.org;
  const customer = invoice.customer;
  const canEdit = invoice.status === 'draft' || invoice.status === 'sent';

  const vatRows = invoice.vat_breakdown.map((bucket) => `
    <div class="totals-row">
      <span>ضريبة ${bucket.rate_bp / 100}%</span>
      <span>${amountHtml(bucket.vat)}</span>
    </div>`).join('');

  container.innerHTML = `
    <div class="page-head no-print">
      <h2>فاتورة ${esc(invoice.number)} ${statusBadge(invoice)}</h2>
      <div class="page-actions">
        <button class="btn" onclick="navigate('invoices')">رجوع</button>
        ${canEdit ? `<button class="btn" onclick="editInvoice(${invoice.id})">تعديل</button>` : ''}
        ${invoice.status !== 'cancelled' && invoice.balance > 0
          ? `<button class="btn" onclick="paymentModal(${invoice.id})">تسجيل دفعة</button>` : ''}
        ${invoice.status === 'draft'
          ? `<button class="btn" onclick="changeStatus(${invoice.id},'sent')">اعتماد وإصدار</button>` : ''}
        ${invoice.status !== 'cancelled'
          ? `<button class="btn btn-ghost" onclick="changeStatus(${invoice.id},'cancelled')">إلغاء الفاتورة</button>` : ''}
        <button class="btn btn-primary" onclick="window.print()">طباعة / PDF</button>
      </div>
    </div>

    ${invoice.balance > 0 && invoice.status !== 'cancelled' ? `<div class="notice no-print">
      المتبقي على هذه الفاتورة: <strong>${amountHtml(invoice.balance)}</strong>
    </div>` : ''}

    <div class="invoice-sheet">
      <div class="invoice-header">
        <div class="invoice-supplier">
          <p class="invoice-title">فاتورة ضريبية</p>
          <h4>${esc(org.name)}</h4>
          ${org.vat_number ? `<div>الرقم الضريبي: <span class="num">${esc(org.vat_number)}</span></div>` : ''}
          ${org.cr_number ? `<div>السجل التجاري: <span class="num">${esc(org.cr_number)}</span></div>` : ''}
          ${org.address ? `<div>${esc(org.address)}</div>` : ''}
          ${org.phone ? `<div>هاتف: <span class="num">${esc(org.phone)}</span></div>` : ''}
        </div>
        <div class="invoice-meta">
          <div><strong>رقم الفاتورة:</strong> <span class="num">${esc(invoice.number)}</span></div>
          <div><strong>تاريخ الإصدار:</strong> <span class="num">${esc(invoice.issue_date)}</span></div>
          ${invoice.due_date ? `<div><strong>تاريخ الاستحقاق:</strong> <span class="num">${esc(invoice.due_date)}</span></div>` : ''}
        </div>
      </div>

      <div class="invoice-parties">
        <div class="party-box">
          <h5>فاتورة إلى</h5>
          <strong>${esc(customer ? customer.name : 'عميل نقدي')}</strong>
          ${customer && customer.vat_number ? `<div>الرقم الضريبي: <span class="num">${esc(customer.vat_number)}</span></div>` : ''}
          ${customer && customer.address ? `<div>${esc(customer.address)}</div>` : ''}
          ${customer && customer.phone ? `<div>هاتف: <span class="num">${esc(customer.phone)}</span></div>` : ''}
        </div>
        <div class="party-box">
          <h5>ملخص</h5>
          <div>الإجمالي: <strong>${amountHtml(invoice.grand_total)}</strong></div>
          <div>المسدّد: ${amountHtml(invoice.paid_total)}</div>
          <div>المتبقي: <strong>${amountHtml(invoice.balance)}</strong></div>
        </div>
      </div>

      <table class="invoice-lines">
        <thead><tr>
          <th style="width:32px">#</th>
          <th>الوصف</th>
          <th style="width:70px">الكمية</th>
          <th style="width:70px">الوحدة</th>
          <th style="width:95px">السعر</th>
          <th style="width:85px">الخصم</th>
          <th style="width:70px">الضريبة</th>
          <th style="width:105px" class="text-end">الإجمالي</th>
        </tr></thead>
        <tbody>${invoice.lines.map((line, index) => `<tr>
          <td>${index + 1}</td>
          <td>${esc(line.description)}</td>
          <td><span class="num">${esc(qty(line.quantity))}</span></td>
          <td>${esc(line.unit)}</td>
          <td class="nowrap">${amountHtml(line.unit_price)}</td>
          <td class="nowrap">${line.discount ? amountHtml(line.discount) : '—'}</td>
          <td class="nowrap">${line.vat_rate_bp / 100}%</td>
          <td class="text-end nowrap">${amountHtml(line.line_total)}</td>
        </tr>`).join('')}</tbody>
      </table>

      <div class="invoice-footer">
        <div class="invoice-notes">
          ${invoice.notes ? esc(invoice.notes).replace(/\n/g, '<br>') : ''}
        </div>
        <div class="totals-box" style="margin:0; min-width:280px">
          <div class="totals-row"><span>المجموع قبل الضريبة</span><span>${amountHtml(invoice.taxable_total)}</span></div>
          ${invoice.discount_total ? `<div class="totals-row"><span>إجمالي الخصم</span><span>${amountHtml(invoice.discount_total)}</span></div>` : ''}
          ${vatRows}
          <div class="totals-row grand"><span>الإجمالي المستحق</span><span>${amountHtml(invoice.grand_total)}</span></div>
        </div>
      </div>
    </div>

    ${invoice.payments.length ? `<div class="card no-print">
      <h3>المدفوعات</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>التاريخ</th><th>الطريقة</th><th>ملاحظة</th><th class="text-end">المبلغ</th><th></th></tr></thead>
        <tbody>${invoice.payments.map((payment) => `<tr>
          <td class="nowrap"><span class="num">${esc(payment.paid_on)}</span></td>
          <td>${esc(PAYMENT_METHODS[payment.method] || payment.method)}</td>
          <td>${esc(payment.note || '—')}</td>
          <td class="text-end nowrap">${amountHtml(payment.amount)}</td>
          <td><button class="btn btn-ghost btn-small"
              onclick="deletePayment(${invoice.id},${payment.id})">حذف</button></td>
        </tr>`).join('')}</tbody>
      </table></div>
    </div>` : ''}
  `;
}

async function changeStatus(id, status) {
  const messages = {
    cancelled: 'إلغاء هذه الفاتورة؟ ستبقى محفوظة في السجل لكن لن تُحتسب في المبيعات ولا الإقرار الضريبي.',
    sent: 'اعتماد الفاتورة وإصدارها للعميل؟',
  };
  if (messages[status] && !confirm(messages[status])) return;

  try {
    const result = await api(`/api/invoices/${id}/status`, { method: 'POST', body: { status } });
    state.viewing = result.invoice;
    toast('تم تحديث حالة الفاتورة');
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

function paymentModal(invoiceId) {
  const invoice = state.viewing;
  openModal('تسجيل دفعة', `
    <form class="modal-form" id="payment-form">
      <label>المبلغ (ر.ع)
        <input type="text" inputmode="decimal" class="amount" name="amount"
               value="${esc(money(invoice.balance))}" required>
        <small class="muted">المتبقي على الفاتورة: ${esc(money(invoice.balance))} ر.ع</small>
      </label>
      <div class="form-row">
        <label>تاريخ الدفع
          <input type="date" name="paid_on" value="${esc(today())}" required>
        </label>
        <label>طريقة الدفع
          <select name="method">
            ${Object.entries(PAYMENT_METHODS).map(([value, label]) =>
              `<option value="${value}">${label}</option>`).join('')}
          </select>
        </label>
      </div>
      <label>ملاحظة
        <input type="text" name="note" placeholder="رقم السند أو المرجع">
      </label>
      <div class="modal-actions">
        <button type="submit" class="btn btn-primary">تسجيل الدفعة</button>
        <button type="button" class="btn" onclick="closeModal()">إلغاء</button>
      </div>
    </form>
  `);

  document.getElementById('payment-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      const result = await api(`/api/invoices/${invoiceId}/payments`, { method: 'POST', body: data });
      state.viewing = result.invoice;
      closeModal();
      toast('تم تسجيل الدفعة');
      render();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function deletePayment(invoiceId, paymentId) {
  if (!confirm('حذف هذه الدفعة؟')) return;
  try {
    const result = await api(`/api/invoices/${invoiceId}/payments/${paymentId}`, { method: 'DELETE' });
    state.viewing = result.invoice;
    toast('تم حذف الدفعة');
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

// ============================================================ العملاء

async function renderCustomers(container) {
  const data = await api('/api/customers');
  state.customers = data.customers;

  container.innerHTML = `
    <div class="page-head">
      <h2>العملاء</h2>
      <div class="page-actions">
        <button class="btn btn-primary" onclick="customerModal()">+ عميل جديد</button>
      </div>
    </div>
    <div class="card">
      ${state.customers.length ? `<div class="table-wrap"><table>
        <thead><tr><th>الاسم</th><th>الرقم الضريبي</th><th>الهاتف</th><th>البريد</th><th></th></tr></thead>
        <tbody>${state.customers.map((customer) => `<tr>
          <td><strong>${esc(customer.name)}</strong></td>
          <td><span class="num">${esc(customer.vat_number || '—')}</span></td>
          <td><span class="num">${esc(customer.phone || '—')}</span></td>
          <td>${esc(customer.email || '—')}</td>
          <td class="text-end nowrap">
            <button class="btn btn-ghost btn-small" onclick="customerModal(${customer.id})">تعديل</button>
            <button class="btn btn-ghost btn-small" onclick="archiveCustomer(${customer.id})">أرشفة</button>
          </td>
        </tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="empty"><span class="empty-icon">👥</span>لم تضف عملاء بعد.</div>'}
    </div>
  `;
}

function customerModal(id) {
  const customer = id ? state.customers.find((candidate) => candidate.id === id) : null;
  openModal(customer ? 'تعديل عميل' : 'عميل جديد', `
    <form class="modal-form" id="customer-form">
      <label>الاسم *
        <input type="text" name="name" required value="${esc(customer ? customer.name : '')}">
      </label>
      <div class="form-row">
        <label>الرقم الضريبي
          <input type="text" name="vat_number" value="${esc(customer ? customer.vat_number : '')}"
                 placeholder="OM1100000000">
        </label>
        <label>الهاتف
          <input type="text" name="phone" value="${esc(customer ? customer.phone : '')}">
        </label>
      </div>
      <label>البريد الإلكتروني
        <input type="email" name="email" value="${esc(customer ? customer.email : '')}">
      </label>
      <label>العنوان
        <input type="text" name="address" value="${esc(customer ? customer.address : '')}">
      </label>
      <label>ملاحظات
        <textarea name="notes">${esc(customer ? customer.notes : '')}</textarea>
      </label>
      <div class="modal-actions">
        <button type="submit" class="btn btn-primary">حفظ</button>
        <button type="button" class="btn" onclick="closeModal()">إلغاء</button>
      </div>
    </form>
  `);

  document.getElementById('customer-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      if (customer) await api('/api/customers/' + customer.id, { method: 'PUT', body: data });
      else await api('/api/customers', { method: 'POST', body: data });
      closeModal();
      toast('تم الحفظ');
      await refreshLookups();
      render();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function archiveCustomer(id) {
  if (!confirm('أرشفة هذا العميل؟ فواتيره السابقة تبقى كما هي.')) return;
  try {
    await api('/api/customers/' + id, { method: 'DELETE' });
    toast('تمت الأرشفة');
    await refreshLookups();
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

// ============================================================ الأصناف

async function renderItems(container) {
  const data = await api('/api/items');
  state.items = data.items;

  container.innerHTML = `
    <div class="page-head">
      <h2>الأصناف والخدمات</h2>
      <div class="page-actions">
        <button class="btn btn-primary" onclick="itemModal()">+ صنف جديد</button>
      </div>
    </div>
    <p class="muted" style="margin-top:-8px">الأصناف المحفوظة تُدخل في الفاتورة بنقرة واحدة بدل كتابتها كل مرة.</p>
    <div class="card">
      ${state.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>الاسم</th><th>الوحدة</th><th>السعر</th><th>الضريبة</th><th></th></tr></thead>
        <tbody>${state.items.map((item) => `<tr>
          <td><strong>${esc(item.name)}</strong></td>
          <td>${esc(item.unit)}</td>
          <td class="nowrap">${amountHtml(item.unit_price)}</td>
          <td>${esc(VAT_LABELS[item.vat_category] || item.vat_category)}</td>
          <td class="text-end nowrap">
            <button class="btn btn-ghost btn-small" onclick="itemModal(${item.id})">تعديل</button>
            <button class="btn btn-ghost btn-small" onclick="archiveItem(${item.id})">أرشفة</button>
          </td>
        </tr>`).join('')}</tbody>
      </table></div>`
      : '<div class="empty"><span class="empty-icon">📦</span>لم تضف أصنافًا بعد.</div>'}
    </div>
  `;
}

function itemModal(id) {
  const item = id ? state.items.find((candidate) => candidate.id === id) : null;
  openModal(item ? 'تعديل صنف' : 'صنف جديد', `
    <form class="modal-form" id="item-form">
      <label>الاسم *
        <input type="text" name="name" required value="${esc(item ? item.name : '')}">
      </label>
      <div class="form-row">
        <label>السعر (ر.ع)
          <input type="text" inputmode="decimal" class="amount" name="unit_price"
                 value="${esc(item ? money(item.unit_price) : '')}" placeholder="0.000">
        </label>
        <label>الوحدة
          <input type="text" name="unit" value="${esc(item ? item.unit : 'قطعة')}">
        </label>
      </div>
      <label>الفئة الضريبية
        <select name="vat_category">
          ${Object.entries(VAT_LABELS).map(([value, label]) =>
            `<option value="${value}" ${item && item.vat_category === value ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
      </label>
      <div class="modal-actions">
        <button type="submit" class="btn btn-primary">حفظ</button>
        <button type="button" class="btn" onclick="closeModal()">إلغاء</button>
      </div>
    </form>
  `);

  document.getElementById('item-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      if (item) await api('/api/items/' + item.id, { method: 'PUT', body: data });
      else await api('/api/items', { method: 'POST', body: data });
      closeModal();
      toast('تم الحفظ');
      await refreshLookups();
      render();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function archiveItem(id) {
  if (!confirm('أرشفة هذا الصنف؟')) return;
  try {
    await api('/api/items/' + id, { method: 'DELETE' });
    toast('تمت الأرشفة');
    await refreshLookups();
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

// ============================================================ التقارير

async function renderReports(container) {
  const period = renderReports.period || {
    from: today().slice(0, 8) + '01',
    to: today(),
  };

  const data = await api(`/api/reports/vat?from=${period.from}&to=${period.to}`);
  const report = data.vat_return;

  container.innerHTML = `
    <div class="page-head">
      <h2>التقارير والإقرار الضريبي</h2>
      <div class="page-actions">
        <label style="font-weight:400">من
          <input type="date" id="r-from" value="${esc(period.from)}">
        </label>
        <label style="font-weight:400">إلى
          <input type="date" id="r-to" value="${esc(period.to)}">
        </label>
        <button class="btn" id="r-apply" style="align-self:flex-end">تطبيق</button>
        <button class="btn" id="r-export" style="align-self:flex-end">تصدير Excel</button>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat">
        <div class="stat-label">المبيعات قبل الضريبة</div>
        <div class="stat-value">${amountHtml(report.total_taxable)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">ضريبة القيمة المضافة المستحقة</div>
        <div class="stat-value">${amountHtml(report.total_vat)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">عدد الفواتير</div>
        <div class="stat-value">${report.invoice_count}</div>
      </div>
    </div>

    <div class="card">
      <h3>تفصيل حسب الفئة الضريبية</h3>
      ${report.breakdown.length ? `<div class="table-wrap"><table>
        <thead><tr><th>الفئة</th><th>النسبة</th><th class="text-end">الوعاء الضريبي</th><th class="text-end">الضريبة</th></tr></thead>
        <tbody>${report.breakdown.map((bucket) => `<tr>
          <td>${esc(VAT_LABELS[bucket.category] || bucket.category)}</td>
          <td><span class="num">${bucket.rate_bp / 100}%</span></td>
          <td class="text-end">${amountHtml(bucket.taxable)}</td>
          <td class="text-end">${amountHtml(bucket.vat)}</td>
        </tr>`).join('')}
        <tr class="total-row">
          <td colspan="2">الإجمالي</td>
          <td class="text-end">${amountHtml(report.total_taxable)}</td>
          <td class="text-end">${amountHtml(report.total_vat)}</td>
        </tr></tbody>
      </table></div>`
      : '<div class="empty">لا توجد فواتير صادرة في هذه الفترة.</div>'}
    </div>

    <div class="notice" style="margin-top:16px">
      هذه الأرقام تشمل الفواتير الصادرة والمدفوعة فقط — المسودات والفواتير الملغاة مستبعدة.
      راجعها مع محاسبك قبل تقديم الإقرار.
    </div>
  `;

  document.getElementById('r-apply').addEventListener('click', () => {
    renderReports.period = {
      from: document.getElementById('r-from').value,
      to: document.getElementById('r-to').value,
    };
    render();
  });

  document.getElementById('r-export').addEventListener('click', () => {
    const from = document.getElementById('r-from').value;
    const to = document.getElementById('r-to').value;
    window.location.href = `/api/reports/export.csv?from=${from}&to=${to}`;
  });
}

// ============================================================ الإعدادات

async function renderSettings(container) {
  const data = await api('/api/me');
  state.org = data.org;
  const org = state.org;

  container.innerHTML = `
    <div class="page-head"><h2>الإعدادات</h2></div>

    <div class="card">
      <h3>بيانات المنشأة</h3>
      <p class="muted" style="margin-top:-8px">هذه البيانات تظهر في أعلى كل فاتورة. الرقم الضريبي مطلوب نظامًا في الفاتورة الضريبية.</p>
      <form class="modal-form" id="org-form">
        <label>اسم المنشأة *
          <input type="text" name="name" required value="${esc(org.name)}">
        </label>
        <div class="form-row">
          <label>الرقم الضريبي
            <input type="text" name="vat_number" value="${esc(org.vat_number)}" placeholder="OM1100000000">
          </label>
          <label>رقم السجل التجاري
            <input type="text" name="cr_number" value="${esc(org.cr_number)}">
          </label>
        </div>
        <div class="form-row">
          <label>الهاتف
            <input type="text" name="phone" value="${esc(org.phone)}">
          </label>
          <label>البريد الإلكتروني
            <input type="email" name="email" value="${esc(org.email)}">
          </label>
        </div>
        <label>العنوان
          <input type="text" name="address" value="${esc(org.address)}">
        </label>
        <label>بادئة رقم الفاتورة
          <input type="text" name="invoice_prefix" value="${esc(org.invoice_prefix)}" maxlength="10">
          <small class="muted">مثال: بادئة INV تُنتج أرقامًا مثل INV-00001</small>
        </label>
        <div class="modal-actions">
          <button type="submit" class="btn btn-primary">حفظ البيانات</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3>الباقة</h3>
      <p>باقتك الحالية: <strong>${esc(org.plan_limits.label)}</strong></p>
      ${org.plan === 'free' ? `
        <p class="muted">الباقة المجانية: ${org.plan_limits.invoices_per_month} فواتير شهريًا و${org.plan_limits.customers} عميلًا.</p>
        <button class="btn btn-primary" onclick="upgradePlan()">الترقية إلى الاحترافية</button>
      ` : `
        <p class="muted">فواتير وعملاء بلا حد.</p>
        <button class="btn" onclick="downgradePlan()">الرجوع إلى المجانية</button>
      `}
    </div>
  `;

  document.getElementById('org-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      const result = await api('/api/org', { method: 'PUT', body: data });
      state.org = result.org;
      document.getElementById('org-name').textContent = state.org.name;
      toast('تم حفظ بيانات المنشأة');
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function upgradePlan() {
  openModal('الترقية إلى الباقة الاحترافية', `
    <div class="modal-body" style="padding:0">
      <p>الباقة الاحترافية تفتح فواتير وعملاء بلا حد.</p>
      <div class="notice">
        لم يُربط نظام دفع بعد. هذا الزر يفعّل الباقة مباشرة للتجربة —
        اربطه ببوابة دفع قبل استقبال مشتركين حقيقيين (التفاصيل في ملف README).
      </div>
      <div class="modal-actions">
        <button class="btn btn-primary" id="confirm-upgrade">تفعيل الباقة الاحترافية</button>
        <button class="btn" onclick="closeModal()">إلغاء</button>
      </div>
    </div>
  `);

  document.getElementById('confirm-upgrade').addEventListener('click', async () => {
    try {
      const result = await api('/api/org/plan', { method: 'POST', body: { plan: 'pro' } });
      state.org = result.org;
      closeModal();
      toast('تم تفعيل الباقة الاحترافية');
      showApp();
      render();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

async function downgradePlan() {
  try {
    const result = await api('/api/org/plan', { method: 'POST', body: { plan: 'free' } });
    state.org = result.org;
    toast('تم الرجوع إلى الباقة المجانية');
    showApp();
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

// ============================================================ النافذة المنبثقة

function openModal(title, html) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = `<div class="modal-body">${html}</div>`;
  document.getElementById('modal-backdrop').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
  document.getElementById('modal-body').innerHTML = '';
}

// ============================================================ الإقلاع

async function boot() {
  setupAuthScreen();

  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => navigate(item.dataset.view));
  });

  document.getElementById('logout-btn').addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' }).catch(() => {});
    state.user = null;
    state.org = null;
    showAuth();
  });

  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal-backdrop').addEventListener('click', (event) => {
    if (event.target.id === 'modal-backdrop') closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
  });

  // استعادة الجلسة إن كانت ما زالت صالحة
  try {
    const me = await api('/api/me');
    state.user = me.user;
    state.org = me.org;
    await afterLogin();
  } catch (error) {
    showAuth();
  }
}

boot();
