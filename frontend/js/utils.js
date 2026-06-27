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

// Navigation Tab Switching
export function switchTab(tabId) {
    // Esconder todos os painéis de abas
    document.querySelectorAll('.tab-pane').forEach(panel => {
        panel.classList.remove('active');
        panel.style.display = 'none';
    });
    
    // Remover classe ativa de todos os botões de aba
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.style.color = 'var(--text-muted)';
        btn.style.borderBottomColor = 'transparent';
    });
    
    // Mostrar o painel selecionado
    const activePanel = document.getElementById(tabId);
    if (activePanel) {
        activePanel.classList.add('active');
        activePanel.style.display = 'block';
    }
    
    // Marcar botão correspondente como ativo
    const correspondingBtn = document.querySelector(`.tab-btn[onclick*="${tabId}"]`);
    if (correspondingBtn) {
        correspondingBtn.classList.add('active');
        correspondingBtn.style.color = 'var(--text-primary)';
        correspondingBtn.style.borderBottomColor = 'var(--primary)';
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
