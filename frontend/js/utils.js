// Display Toast Notifications
export function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    const icon = document.getElementById('toast-icon');
    const msgSpan = document.getElementById('toast-message');
    if (!toast || !icon || !msgSpan) return;
    
    // Set icon classes based on type
    icon.className = 'fa-solid';
    if (type === 'success') {
        icon.classList.add('fa-circle-check');
        toast.className = 'toast show success';
    } else if (type === 'error') {
        icon.classList.add('fa-circle-xmark');
        toast.className = 'toast show error';
    } else {
        icon.classList.add('fa-circle-info');
        toast.className = 'toast show info';
    }
    
    msgSpan.innerText = message;
    
    // Hide toast after 4 seconds
    setTimeout(() => {
        toast.classList.remove('show');
    }, 4000);
}

// Shared AbortController for fetch race-condition prevention
let _activeAbortController = null;

export function getActiveAbortController() {
  return _activeAbortController;
}

export function createAbortController() {
  if (_activeAbortController) {
    _activeAbortController.abort();
  }
  _activeAbortController = new AbortController();
  return _activeAbortController;
}

// Navigation Tab Switching
export function switchTab(tabId) {
    // Esconder todos os painéis de abas
    document.querySelectorAll('.tab-pane').forEach(panel => {
        panel.classList.remove('active');
        panel.style.display = 'none';
    });

    // Remover classe ativa de todos os botões de aba (old tab bar)
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.color = 'var(--text-muted)';
        btn.style.borderBottomColor = 'transparent';
    });

    // Remover classe ativa da nova side nav
    document.querySelectorAll('.sidenav-item').forEach(item => item.classList.remove('active'));

    // Mostrar o painel selecionado
    const activePanel = document.getElementById(tabId);
    if (activePanel) {
        activePanel.classList.add('active');
        activePanel.style.display = 'block';
    }

    // Marcar botão correspondente como ativo (old tab bar)
    const correspondingBtn = document.querySelector(`.tab-btn[onclick*="${tabId}"]`);
    if (correspondingBtn) {
        correspondingBtn.classList.add('active');
        correspondingBtn.style.color = 'var(--text-primary)';
        correspondingBtn.style.borderBottomColor = 'var(--primary)';
    }

    // Marcar item da side nav como ativo
    const sideNavItem = document.querySelector(`.sidenav-item[onclick*="${tabId}"]`);
    if (sideNavItem) {
        sideNavItem.classList.add('active');
    }

    // Auto-load history when switching to history tab
    if (tabId === 'tab-history' && typeof window.loadHistoryTab === 'function') {
        window.loadHistoryTab();
    }
}

// Format numbers
export function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
}

export function formatPct(value) {
    return `${value.toFixed(2)}%`;
}

// Toggle multi-select group checkbox list helper
export function toggleGroup(groupEl, event) {
    if (event) {
        event.stopPropagation();
        if (event.stopImmediatePropagation) {
            event.stopImmediatePropagation();
        }
    }
    
    let checkboxes = [];
    let el = groupEl.nextElementSibling;
    while (el && !el.classList.contains('multiselect-optgroup')) {
        if (el.tagName === 'LABEL' || el.classList.contains('multiselect-option-item')) {
            const cb = el.querySelector('input[type="checkbox"]');
            if (cb) checkboxes.push(cb);
        }
        el = el.nextElementSibling;
    }
    
    if (checkboxes.length > 0) {
        const allChecked = checkboxes.every(cb => cb.checked);
        checkboxes.forEach(cb => { 
            cb.checked = !allChecked;
            cb.dispatchEvent(new Event('change'));
        });
    }
}

// Count-up animation for metric values
export function animateValue(el, start, end, duration = 600, formatter = (v) => v) {
    if (!el) return;
    // Cancel any previous animation on this element
    if (el._animFrame) { cancelAnimationFrame(el._animFrame); }
    if (el._animFallback) { clearTimeout(el._animFallback); }
    const startTime = performance.now();
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) { el.textContent = formatter(end); return; }
    function step(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        const current = start + (end - start) * eased;
        el.textContent = formatter(current);
        if (progress < 1) { el._animFrame = requestAnimationFrame(step); }
    }
    el._animFrame = requestAnimationFrame(step);
    // Safety net: ensure final value is set even if rAF never fires (headless browsers, background tabs)
    el._animFallback = setTimeout(() => {
        cancelAnimationFrame(el._animFrame);
        el.textContent = formatter(end);
    }, duration + 100);
}

export function toggleStakeLabel() {
    const rule = document.getElementById('stake-rule').value;
    const label = document.getElementById('stake-val-label');
    const stakeValGroup = document.getElementById('stake-val-group');
    const kellySliderContainer = document.getElementById('kelly-slider-container');
    
    if (rule === 'fixed') {
        if (label) label.innerText = 'Valor Fixo ($):';
        if (stakeValGroup) stakeValGroup.style.display = 'block';
        if (kellySliderContainer) kellySliderContainer.style.display = 'none';
    } else if (rule === 'proportional') {
        if (label) label.innerText = 'Risco na Banca (%):';
        if (stakeValGroup) stakeValGroup.style.display = 'block';
        if (kellySliderContainer) kellySliderContainer.style.display = 'none';
    } else {
        if (stakeValGroup) stakeValGroup.style.display = 'none';
        if (kellySliderContainer) kellySliderContainer.style.display = 'flex';
    }
}
