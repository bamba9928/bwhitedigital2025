// === APP GLOBAL ===
class AppManager {
  constructor() {
    this.timers = new Map();
    this.cache = new Map();
    this.ac = new AbortController();
    this.spinnerTimer = null;
    this.inactivity = null;
    this.init();
  }

  init() {
    this.detectContext();
    this.bindGlobalEvents();
    this.initInactivity();
  }

  // -------- Context
  detectContext() {
    if (document.getElementById('contrat-form')) {
      this.contract = new ContractFormManager(this);
      this.bindContractValidation();
    }
    if (document.querySelector('.profile-form')) {
      this.initProfile();
    }
  }

  initProfile() {
    // réservé
  }

  // -------- Validation contrat
  bindContractValidation() {
    const form = document.querySelector('#contrat-form');
    if (!form) return;

    const debouncedValidate = () => this.debounce('v', () => this.validate(false), 300);

    form.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input', debouncedValidate, { signal: this.ac.signal });
      el.addEventListener('change', () => this.validate(false), { signal: this.ac.signal });
    });

    const calcBtn = document.querySelector('#btn-calculer-tarif');
    if (calcBtn) {
      calcBtn.addEventListener('click', (e) => {
        this.clearDebounce('v');
        if (!this.validate(true)) {
          e.preventDefault();
          e.stopPropagation();
          this.toast('Veuillez remplir tous les champs obligatoires', 'error', 4000);
        }
      }, { signal: this.ac.signal });
    }
  }

  requiredIds() {
    return [
      'id_prenom','id_nom','id_adresse','id_telephone',
      'id_immatriculation','id_marque','id_modele','id_categorie',
      'id_carburant','id_puissance_fiscale','id_nombre_places',
      'id_duree','id_date_effet'
    ];
  }

  validate(showErrors = false) {
    const get = (id) => {
      if (!this.cache.has(id)) this.cache.set(id, document.getElementById(id));
      return this.cache.get(id);
    };

    const cat = get('id_categorie');
    const needTPC = cat?.value === '520';

    const ids = [...this.requiredIds()];
    const scWrap = document.getElementById('sous-categorie-wrapper');
    const cuWrap = document.getElementById('charge-utile-wrapper');
    if (needTPC && scWrap && !scWrap.classList.contains('hidden')) ids.push('id_sous_categorie');
    if (needTPC && cuWrap && !cuWrap.classList.contains('hidden')) ids.push('id_charge_utile');

    let ok = true;
    for (const id of ids) {
      const el = get(id);
      if (!el || el.offsetParent === null) continue;
      const empty = !String(el.value ?? '').trim();
      if (empty) {
        ok = false;
        if (showErrors) el.classList.add('border-red-500'), el.classList.remove('border-green-500');
      } else {
        el.classList.remove('border-red-500'); el.classList.add('border-green-500');
      }
    }
    return ok;
  }

  // -------- Utils
  debounce(key, cb, delay = 300) {
    this.clearDebounce(key);
    const t = setTimeout(cb, delay);
    this.timers.set(key, t);
  }
  clearDebounce(key) {
    const t = this.timers.get(key);
    if (t) clearTimeout(t);
    this.timers.delete(key);
  }
  clearCache() { this.cache.clear(); }

  toast(msg, type = 'info', ms = 5000) {
    const color = { success:'bg-green-600', error:'bg-red-600', warning:'bg-yellow-600', info:'bg-blue-600' }[type] || 'bg-blue-600';
    const icon  = { success:'fa-check-circle', error:'fa-times-circle', warning:'fa-exclamation-triangle', info:'fa-info-circle' }[type] || 'fa-info-circle';

    const existing = document.querySelectorAll('.app-toast');
    if (existing.length >= 3) existing[0].remove();

    const el = document.createElement('div');
    el.className = `app-toast fixed top-4 right-4 ${color} text-white px-6 py-3 rounded-lg shadow-lg z-50 transform translate-x-full transition-transform duration-300`;
    el.innerHTML = `
      <div class="flex items-center space-x-3">
        <i class="fas ${icon}"></i>
        <span>${this.escape(msg)}</span>
        <button class="ml-2 hover:opacity-75" aria-label="Fermer">&times;</button>
      </div>`;
    el.querySelector('button').onclick = () => el.remove();

    document.body.appendChild(el);
    requestAnimationFrame(() => el.style.transform = 'translateX(0)');
    setTimeout(() => { el.style.transform = 'translateX(100%)'; setTimeout(() => el.remove(), 300); }, ms);
  }

  escape(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  // -------- Global HTMX + spinner
  bindGlobalEvents() {
    const signal = this.ac.signal;

    document.body.addEventListener('htmx:configRequest', (evt) => {
      const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
      if (csrf) evt.detail.headers['X-CSRFToken'] = csrf;
    }, { signal });

    document.body.addEventListener('htmx:responseError', (evt) => {
      const status = evt.detail.xhr?.status;
      const msg =
        status === 500 ? 'Erreur serveur. Veuillez réessayer.' :
        status === 404 ? 'Ressource non trouvée' :
        status === 403 ? 'Accès refusé' :
        status === 0   ? 'Erreur de connexion réseau' :
                         'Erreur lors de la requête';
      this.toast(msg, 'error');
      this.hideSpinner();
    }, { signal });

    document.body.addEventListener('htmx:timeout', () => {
      this.toast('La requête a pris trop de temps', 'warning');
      this.hideSpinner();
    }, { signal });

    document.body.addEventListener('htmx:beforeRequest', () => this.showSpinner(), { signal });
    document.body.addEventListener('htmx:afterRequest',  () => this.hideSpinner(), { signal });
  }

  showSpinner() {
    const sp = document.getElementById('global-spinner');
    if (!sp) return;
    sp.classList.remove('hidden');
    this.spinnerTimer = setTimeout(() => {
      this.hideSpinner();
      this.toast('La requête prend plus de temps que prévu…', 'warning');
    }, 60000);
  }
  hideSpinner() {
    const sp = document.getElementById('global-spinner');
    if (!sp) return;
    sp.classList.add('hidden');
    if (this.spinnerTimer) clearTimeout(this.spinnerTimer);
    this.spinnerTimer = null;
  }

  // -------- Inactivité
  initInactivity() {
    this.inactivity = new InactivityManager({
      logoutAfter: 10 * 60 * 1000,
      warningBefore: 60 * 1000,
      onWarning: () => this.toast('Vous serez déconnecté dans 1 minute par inactivité', 'warning', 60000)
    });
  }

  // -------- Teardown
  destroy() {
    this.ac.abort();
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
    this.clearCache();
    if (this.spinnerTimer) clearTimeout(this.spinnerTimer);
    if (this.inactivity) this.inactivity.destroy();
    if (this.contract) this.contract.destroy();
  }
}

// === INACTIVITY ===
class InactivityManager {
  constructor({ logoutAfter = 600000, warningBefore = 60000, logoutUrl = '/accounts/logout/', onWarning = null } = {}) {
    this.logoutAfter = logoutAfter;
    this.warningBefore = warningBefore;
    this.logoutUrl = logoutUrl;
    this.onWarning = onWarning;
    this.timer = null;
    this.warnTimer = null;
    this.bind();
  }

  bind() {
    const reset = this.reset.bind(this);
    ['load','mousemove','keypress','click','scroll','touchstart'].forEach(ev =>
      window.addEventListener(ev, reset, { passive: true })
    );
    this.reset();
  }

  reset() {
    clearTimeout(this.timer);
    clearTimeout(this.warnTimer);
    this.warnTimer = setTimeout(() => this.warn(), Math.max(0, this.logoutAfter - this.warningBefore));
    this.timer = setTimeout(() => this.logout(), this.logoutAfter);
  }

  warn() { if (this.onWarning) this.onWarning(); }

  logout() {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = this.logoutUrl;
    form.style.display = 'none';
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    if (csrf) {
      const i = document.createElement('input');
      i.type = 'hidden'; i.name = 'csrfmiddlewaretoken'; i.value = csrf;
      form.appendChild(i);
    }
    document.body.appendChild(form);
    form.submit();
  }

  destroy() {
    clearTimeout(this.timer);
    clearTimeout(this.warnTimer);
  }
}

// === CONTRACT FORM ===
class ContractFormManager {
  constructor(app) {
    this.app = app;
    this.listeners = [];
    this.initWidgets();
    this.bindCategorie();
    this.bindSimulationView();
    this.bindButtons();
  }

  // ---- Widgets
  initWidgets() {
    this.initSelect2();
    this.initDate();
    this.ensurePlaceholders();
  }

  initSelect2() {
    if (typeof $ === 'undefined' || !$.fn?.select2) return;
    try {
      $('#id_marque').select2({ placeholder:'Sélectionner une marque', width:'100%', allowClear:true });
      $('#id_categorie').select2({ minimumResultsForSearch: Infinity, placeholder:'Sélectionner une catégorie' });
      $('#id_carburant').select2({ minimumResultsForSearch: Infinity, placeholder:'Sélectionner un carburant' });
      $('#id_sous_categorie').select2({ minimumResultsForSearch: Infinity, placeholder:'Sous-catégorie' });
      $('#id_duree').select2({ minimumResultsForSearch: Infinity, placeholder:'Durée' });
    } catch (e) { console.error('Select2:', e); }
  }

  initDate() {
    if (typeof flatpickr === 'undefined') return;
    try {
      flatpickr('#id_date_effet', {
        locale: 'fr',
        dateFormat: 'Y-m-d',
        altInput: true,
        altFormat: 'd/m/Y',
        minDate: 'today',
        maxDate: new Date().fp_incr(60),
        onChange: () => this.app.clearCache()
      });
    } catch (e) { console.error('Flatpickr:', e); }
  }

  ensurePlaceholders() {
    const cat = document.getElementById('id_categorie');
    if (cat && !cat.querySelector("option[value='']")) {
      const opt = new Option('Sélectionner une catégorie', '', true, true);
      opt.disabled = true;
      cat.insertBefore(opt, cat.firstChild);
    }
  }

  // ---- Catégorie -> champs TPC
  bindCategorie() {
    const cat = document.getElementById('id_categorie');
    const scWrap = document.getElementById('sous-categorie-wrapper');
    const cuWrap = document.getElementById('charge-utile-wrapper');
    if (!cat) return;

    const toggle = () => {
      const isTPC = cat.value === '520';
      const sc = document.getElementById('id_sous_categorie');
      const cu = document.getElementById('id_charge_utile');

      if (isTPC) {
        scWrap?.classList.remove('hidden'); cuWrap?.classList.remove('hidden');
        sc?.setAttribute('required', 'required'); cu?.setAttribute('required', 'required');
      } else {
        scWrap?.classList.add('hidden'); cuWrap?.classList.add('hidden');
        sc?.removeAttribute('required'); cu?.removeAttribute('required');
        if (sc) sc.value = ''; if (cu) cu.value = '';
      }
      this.app.clearCache();
    };

    toggle();
    const handler = toggle;
    cat.addEventListener('change', handler);
    this.listeners.push({ el: cat, ev: 'change', fn: handler });
  }

  // ---- Affichage simulation / formulaire
  bindSimulationView() {
    const handler = (evt) => {
      const target = evt.detail?.target;
      if (!target) return;

      if (target.id === 'simulation-result') {
        const formWrap = document.getElementById('contrat-form-wrapper');
        if (target.innerHTML.trim()) {
          formWrap?.classList.add('hidden');
          target.classList.remove('hidden');
        } else {
          formWrap?.classList.remove('hidden');
        }
      }

      if (target.id === 'emission-result' && target.innerHTML.trim()) {
        document.getElementById('simulation-result')?.classList.add('hidden');
        target.classList.remove('hidden');
      }
    };

    document.body.addEventListener('htmx:afterSwap', handler);
    this.listeners.push({ el: document.body, ev: 'htmx:afterSwap', fn: handler });
  }

  // ---- Boutons
  bindButtons() {
    const click = (e) => {
      if (e.target.closest('#btn-modifier-contrat')) {
        document.getElementById('contrat-form-wrapper')?.classList.remove('hidden');
        document.getElementById('simulation-result')?.classList.add('hidden');
        document.getElementById('emission-result')?.classList.add('hidden');
      }
    };
    document.body.addEventListener('click', click);
    this.listeners.push({ el: document.body, ev: 'click', fn: click });
  }

  // ---- Teardown
  destroy() {
    this.listeners.forEach(({ el, ev, fn }) => el.removeEventListener(ev, fn));
    this.listeners = [];
  }
}

// === BOOT ===
document.addEventListener('DOMContentLoaded', () => {
  window.appManager = new AppManager();
});

window.addEventListener('beforeunload', () => {
  window.appManager?.destroy();
});
