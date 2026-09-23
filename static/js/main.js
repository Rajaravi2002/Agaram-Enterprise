// ─── Sidebar Toggle ──────────────────────────────────────────────────────────
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('main-content');
const toggleBtn = document.getElementById('sidebarToggle');

if (toggleBtn) {
  toggleBtn.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
      sidebar.classList.toggle('mobile-open');
    } else {
      sidebar.classList.toggle('collapsed');
      mainContent.classList.toggle('expanded');
    }
  });
}

// Close sidebar on mobile when clicking outside
document.addEventListener('click', (e) => {
  if (window.innerWidth <= 768 && sidebar && !sidebar.contains(e.target) && e.target !== toggleBtn) {
    sidebar.classList.remove('mobile-open');
  }
});

// ─── HTML-escaping helper ───────────────────────────────────────────────────
// Every value below comes from the database (customer/loan/payment names
// entered by staff) and gets interpolated into innerHTML. Without this, a
// customer name containing e.g. <img src=x onerror=...> would execute in
// anyone's browser who searches for it -- escape everything untrusted
// before it goes into a template string.
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// ─── Global Search ────────────────────────────────────────────────────────────
const searchInput = document.getElementById('globalSearch');
const searchResults = document.getElementById('searchResults');
let searchTimeout;

if (searchInput) {
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (q.length < 2) {
      searchResults.classList.remove('show');
      return;
    }
    searchTimeout = setTimeout(() => performSearch(q), 300);
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      searchResults.classList.remove('show');
      searchInput.value = '';
    }
  });

  document.addEventListener('click', (e) => {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.classList.remove('show');
    }
  });
}

async function performSearch(q) {
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    renderSearchResults(data);
  } catch (err) {
    console.error('Search error:', err);
  }
}

function renderSearchResults(data) {
  const { customers, loans, payments } = data;
  if (!customers.length && !loans.length && !payments.length) {
    searchResults.innerHTML = '<div class="search-result-item text-muted">No results found.</div>';
    searchResults.classList.add('show');
    return;
  }

  let html = '';
  if (customers.length) {
    html += `<div class="search-result-section">
      <div class="search-result-header"><i class="bi bi-person me-1"></i>Customers</div>
      ${customers.map(c => `
        	        <div class="search-result-item" onclick="location.href='/customers/${encodeURIComponent(c.id)}'">
	          <i class="bi bi-person-circle text-primary" style="font-size:16px"></i>
	          <div>
	            <div class="fw-600">${escapeHtml(c.name)}</div>
	            <div class="text-muted" style="font-size:11px">${escapeHtml(c.phone)}</div>
	          </div>
	        </div>`).join('')}
    </div>`;
  }
  if (loans.length) {
    html += `<div class="search-result-section">
      <div class="search-result-header"><i class="bi bi-cash me-1"></i>Loans</div>
      ${loans.map(l => `
        <div class="search-result-item" onclick="location.href='/loans/${encodeURIComponent(l.loan_id)}'">
          <i class="bi bi-cash-coin text-success" style="font-size:16px"></i>
          <div>
            <div class="fw-600">${escapeHtml(l.loan_id)} – ${escapeHtml(l.customer_name)}</div>
            <div class="text-muted" style="font-size:11px">₹${(l.loan_amount||0).toLocaleString('en-IN')} · <span class="text-capitalize">${escapeHtml(l.loan_status)}</span></div>
          </div>
        </div>`).join('')}
    </div>`;
  }
  if (payments.length) {
    html += `<div class="search-result-section">
      <div class="search-result-header"><i class="bi bi-receipt me-1"></i>Payments</div>
      ${payments.map(p => `
        <div class="search-result-item" onclick="location.href='/payments/receipt/${encodeURIComponent(p.payment_id)}'">
          <i class="bi bi-receipt text-warning" style="font-size:16px"></i>
          <div>
            <div class="fw-600">${escapeHtml(p.payment_id)} – ${escapeHtml(p.customer_name)}</div>
            <div class="text-muted" style="font-size:11px">₹${(p.paid_amount||0).toLocaleString('en-IN')} · ${escapeHtml(p.collection_date||'')}</div>
          </div>
        </div>`).join('')}
    </div>`;
  }

  searchResults.innerHTML = html;
  searchResults.classList.add('show');
}

// ─── Rupee Formatter ─────────────────────────────────────────────────────────
function formatRupee(amount) {
  return '₹' + parseFloat(amount || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ─── Auto-dismiss Alerts ──────────────────────────────────────────────────────
document.querySelectorAll('.alert').forEach(alert => {
  setTimeout(() => {
    const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
    if (bsAlert) bsAlert.close();
  }, 6000);
});

// ─── Confirm Delete ───────────────────────────────────────────────────────────
document.querySelectorAll('[data-confirm]').forEach(el => {
  el.addEventListener('click', (e) => {
    if (!confirm(el.dataset.confirm)) e.preventDefault();
  });
});

// ─── Number Format Helper ─────────────────────────────────────────────────────
document.querySelectorAll('.format-rupee').forEach(el => {
  const val = parseFloat(el.textContent.replace(/[^0-9.-]/g, ''));
  if (!isNaN(val)) el.textContent = '₹' + val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});

// ─── Autocomplete Widget ──────────────────────────────────────────────────────
/**
 * attachAutocomplete(inputEl, apiPath, onSelect)
 * Creates a dropdown below inputEl that fetches /api/suggest/<apiPath>?q=...
 * onSelect(item) is called when user picks a suggestion.
 */
function attachAutocomplete(inputEl, apiPath, onSelect) {
  if (!inputEl) return;

  // Create dropdown container
  const wrapper = document.createElement('div');
  wrapper.style.cssText = 'position:relative;display:inline-block;width:100%';
  inputEl.parentNode.insertBefore(wrapper, inputEl);
  wrapper.appendChild(inputEl);

  const dropdown = document.createElement('div');
  dropdown.className = 'autocomplete-dropdown';
  dropdown.style.cssText = [
    'position:absolute;top:100%;left:0;right:0;z-index:9999',
    'background:white;border:1px solid var(--border)',
    'border-radius:var(--radius-sm);box-shadow:var(--shadow-lg)',
    'max-height:220px;overflow-y:auto;display:none'
  ].join(';');
  wrapper.appendChild(dropdown);

  let _timer, _active = -1, _items = [];

  inputEl.addEventListener('input', () => {
    clearTimeout(_timer);
    _active = -1;
    const q = inputEl.value.trim();
    if (q.length < 1) { dropdown.style.display = 'none'; return; }
    _timer = setTimeout(async () => {
      try {
        const r = await fetch(`/api/suggest/${apiPath}?q=${encodeURIComponent(q)}`);
        _items = await r.json();
        if (!_items.length) { dropdown.style.display = 'none'; return; }
        dropdown.innerHTML = _items.map((item, i) =>
          `<div class="ac-item" data-i="${i}"
                style="padding:9px 14px;cursor:pointer;font-size:13px;border-bottom:1px solid var(--border)"
                onmousedown="event.preventDefault()"
                onclick="window._acSelect_${inputEl.id}(${i})">${escapeHtml(item.label)}</div>`
        ).join('');
        dropdown.style.display = 'block';
      } catch(e) { console.error('Autocomplete error', e); }
    }, 220);
  });

  // Keyboard navigation
  inputEl.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.ac-item');
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _active = Math.min(_active + 1, items.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _active = Math.max(_active - 1, 0);
    } else if (e.key === 'Enter' && _active >= 0) {
      e.preventDefault();
      window[`_acSelect_${inputEl.id}`](_active);
      return;
    } else if (e.key === 'Escape') {
      dropdown.style.display = 'none'; return;
    }
    items.forEach((el, i) => el.style.background = i === _active ? 'var(--bg)' : '');
  });

  inputEl.addEventListener('blur', () => setTimeout(() => { dropdown.style.display = 'none'; }, 200));

  window[`_acSelect_${inputEl.id}`] = (i) => {
    const item = _items[i];
    inputEl.value = item.value;
    dropdown.style.display = 'none';
    if (onSelect) onSelect(item);
    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
  };
}

// ─── Loan ID duplicate check ──────────────────────────────────────────────────
function attachLoanIdCheck(inputEl, statusEl) {
  if (!inputEl) return;
  let _timer;
  inputEl.addEventListener('input', () => {
    clearTimeout(_timer);
    const val = inputEl.value.trim().toUpperCase();
    inputEl.value = val;
    if (!val) { statusEl.innerHTML = ''; return; }
    _timer = setTimeout(async () => {
      const r = await fetch(`/api/check-loan-id?id=${encodeURIComponent(val)}`);
      const d = await r.json();
      if (d.exists) {
        statusEl.innerHTML =
          `<span class="text-danger fw-600">
             <i class="bi bi-exclamation-triangle-fill me-1"></i>
             Loan ID <strong>${escapeHtml(val)}</strong> already exists for
             <strong>${escapeHtml(d.customer_name)}</strong> (${escapeHtml(d.loan_status)}).
             Choose a different ID.
           </span>`;
        inputEl.classList.add('is-invalid');
      } else {
        statusEl.innerHTML =
          `<span class="text-success">
             <i class="bi bi-check-circle me-1"></i>
             Loan ID <strong>${escapeHtml(val)}</strong> is available.
           </span>`;
        inputEl.classList.remove('is-invalid');
      }
    }, 350);
  });
}

// ─── Interest rate reverse-calculator ────────────────────────────────────────
/**
 * Given interest_amount and tenure (months), compute % per month:
 *   rate = (interest_amount / (principle * tenure)) * 100
 */
function calcRateFromAmount(principle, interestAmount, tenure) {
  if (!principle || !tenure || principle <= 0 || tenure <= 0) return 0;
  return Math.round((interestAmount / (principle * tenure)) * 10000) / 100; // 4 decimal places
}
