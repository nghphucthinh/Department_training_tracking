/* ── JTP Training Tracker — main.js ───────────────────────────────────── */

// ── CSRF helper ──────────────────────────────────────────────────────────────
function getCsrfToken() {
  const name = 'csrftoken';
  for (const cookie of document.cookie.split(';')) {
    const [k, v] = cookie.trim().split('=');
    if (k === name) return decodeURIComponent(v);
  }
  // Fallback: read from a meta tag or hidden input
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) return meta.content;
  const input = document.querySelector('[name="csrfmiddlewaretoken"]');
  if (input) return input.value;
  return '';
}

// ── Generic JSON POST helper ─────────────────────────────────────────────────
async function postJSON(url, payload) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken(),
    },
    body: JSON.stringify(payload),
  });
  return resp.json();
}

// ── Toast notification ────────────────────────────────────────────────────────
function showToast(message, type = 'success') {
  const toastEl  = document.getElementById('appToast');
  const msgEl    = document.getElementById('appToastMsg');
  if (!toastEl || !msgEl) return;

  // Reset classes
  toastEl.className = 'toast align-items-center border-0';
  if (type === 'danger') {
    toastEl.classList.add('text-bg-danger');
  } else {
    toastEl.classList.add('text-bg-success');
  }

  msgEl.textContent = message;
  const toast = bootstrap.Toast.getOrCreateInstance(toastEl);
  toast.show();
}

// ── Confirm modal helper ──────────────────────────────────────────────────────
function showConfirm(title, body, onConfirm) {
  const modalEl  = document.getElementById('confirmModal');
  const titleEl  = document.getElementById('confirmModalTitle');
  const bodyEl   = document.getElementById('confirmModalBody');
  const okBtn    = document.getElementById('confirmModalOk');

  titleEl.textContent = title;
  bodyEl.innerHTML    = body;

  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

  // Remove previous listener
  const newOkBtn = okBtn.cloneNode(true);
  okBtn.parentNode.replaceChild(newOkBtn, okBtn);

  newOkBtn.addEventListener('click', () => {
    modal.hide();
    onConfirm();
  });

  modal.show();
}

// ── Manual login form ─────────────────────────────────────────────────────────
(function setupManualLogin() {
  const submitBtn = document.getElementById('auth-submit');
  if (!submitBtn) return;

  async function doLogin() {
    const isid     = document.getElementById('manual-isid').value.trim();
    const password = document.getElementById('manual-password').value;
    const errEl    = document.getElementById('auth-error');
    errEl.classList.add('d-none');

    if (!isid || !password) {
      errEl.textContent = 'Please enter your ISID and password.';
      errEl.classList.remove('d-none');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Signing in…';

    try {
      const resp = await fetch('/api/set-user-info/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ isid, email: `${isid}@intel.com`, name: isid }),
      });
      const data = await resp.json();
      if (data.success) {
        location.reload();
      } else {
        errEl.textContent = data.error || 'Authentication failed.';
        errEl.classList.remove('d-none');
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i>Sign In';
      }
    } catch (e) {
      errEl.textContent = 'Network error. Please try again.';
      errEl.classList.remove('d-none');
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<i class="bi bi-box-arrow-in-right me-1"></i>Sign In';
    }
  }

  submitBtn.addEventListener('click', doLogin);
  document.getElementById('manual-password')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });
})();
