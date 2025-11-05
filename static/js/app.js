/* app.js */
(() => {
  'use strict';

  // ======================================
  // === APP GLOBAL ===
  // ======================================
  class AppManager {
    constructor() {
      this.timers = new Map();
      this.cache = new Map();
      this.ac = new AbortController(); // AbortController global pour cleanup
      this.spinnerTimer = null;
      this.inactivity = null;
      this.contract = null;
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
        // Passe le signal global au ContractFormManager
        this.contract = new ContractFormManager(this, this.ac.signal);
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

      const DEBOUNCE_KEY = 'form-validation';
      const debouncedValidate = () => this.debounce(DEBOUNCE_KEY, () => this.validate(false), 300);

      form.querySelectorAll('input, select, textarea').forEach(el => {
        el.addEventListener('input', debouncedValidate, { signal: this.ac.signal });
        el.addEventListener('change', () => this.validate(false), { signal: this.ac.signal });
      });

      const calcBtn = document.querySelector('#btn-calculer-tarif');
      if (calcBtn) {
        calcBtn.addEventListener('click', (e) => {
          this.clearDebounce(DEBOUNCE_KEY);
          if (!this.validate(true)) {
            e.preventDefault();
            e.stopPropagation();
            this.toast('Veuillez remplir tous les champs obligatoires', 'error', 4000);
          }
        }, { signal: this.ac.signal });
      }
    }

    validate(showErrors = false) {
      const requiredIds = this.contract?.requiredIds();
      if (!requiredIds) return true;

      const get = (id) => {
        if (!this.cache.has(id)) this.cache.set(id, document.getElementById(id));
        return this.cache.get(id);
      };

      let ok = true;
      for (const id of requiredIds) {
        const el = get(id);
        // ignore les champs non visibles
        if (!el || el.offsetParent === null) continue;

        const empty = !String(el.value ?? '').trim();

        if (empty) {
          ok = false;
          if (showErrors) {
            el.classList.add('border-red-500');
            el.classList.remove('border-green-500');
            el.setAttribute('aria-invalid', 'true');
          }
        } else {
          el.classList.remove('border-red-500');
          el.classList.add('border-green-500');
          el.setAttribute('aria-invalid', 'false');
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

      // max 3 toasts
      const existing = document.querySelectorAll('.app-toast');
      if (existing.length >= 3) existing[0].remove();

      const el = document.createElement('div');
      el.className = `app-toast fixed top-4 right-4 ${color} text-white px-6 py-3 rounded-lg shadow-lg z-50 transform translate-x-full transition-transform duration-300`;
      el.setAttribute('role', 'alert');
      el.innerHTML = `
        <div class="flex items-center space-x-3">
          <i class="fas ${icon}" aria-hidden="true"></i>
          <span>${this.escape(msg)}</span>
          <button class="ml-2 hover:opacity-75" aria-label="Fermer la notification">&times;</button>
        </div>`;
      el.querySelector('button').onclick = () => {
        el.style.transform = 'translateX(100%)';
        setTimeout(() => el.remove(), 300);
      };

      document.body.appendChild(el);
      setTimeout(() => el.style.transform = 'translateX(0)', 10);
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
                           `Erreur lors de la requête (Code: ${status})`;
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
      if (this.spinnerTimer) clearTimeout(this.spinnerTimer);

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
        appSignal: this.ac.signal,
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

  // ======================================
  // === INACTIVITY MANAGER ===
  // ======================================
  class InactivityManager {
    constructor({ logoutAfter = 600000, warningBefore = 60000, logoutUrl = '/accounts/logout/', onWarning = null, appSignal = null } = {}) {
      this.logoutAfter = logoutAfter;
      this.warningBefore = warningBefore;
      this.logoutUrl = logoutUrl;
      this.onWarning = onWarning;
      this.appSignal = appSignal;
      this.timer = null;
      this.warnTimer = null;
      this.bind();
    }

    bind() {
      const reset = this.reset.bind(this);
      const options = { passive: true, signal: this.appSignal };
      ['load','mousemove','keypress','click','scroll','touchstart'].forEach(ev =>
        window.addEventListener(ev, reset, options)
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
      if (this.appSignal?.aborted) return;
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

  // ======================================
  // === CONTRACT FORM MANAGER ===
  // ======================================
  class ContractFormManager {
    constructor(app, signal) {
      this.app = app;
      this.signal = signal;
      this.listeners = []; // Gardé au cas où
      this.initWidgets();
      this.bindCategorie();          // fixe la valeur de id_charge_utile
      this.bindSimulationView();     // gère l’affichage et ré-init Select2 sous-catégorie
      this.bindButtons();
    }

    // ---- Champs requis dynamiques
    requiredIds() {
      const baseIds = [
        'id_prenom','id_nom','id_adresse','id_telephone',
        'id_immatriculation','id_marque','id_modele','id_categorie',
        'id_carburant','id_puissance_fiscale','id_nombre_places',
        'id_duree','id_date_effet'
      ];

      const cat = document.getElementById('id_categorie');
      const selectedCat = cat?.value;
      const isTPC  = selectedCat === '520';
      const isMoto = selectedCat === '550'; // NOUVELLE VÉRIFICATION

      const ids = [...baseIds];

      // Sous-catégorie requise si TPC ou 2 roues, et visible
      const scWrap = document.getElementById('sous-categorie-wrapper');
      // Vérifie si le wrapper contient un <select> (donc n'est pas vide)
      if ((isTPC || isMoto) && scWrap && scWrap.querySelector('select')) {
        ids.push('id_sous_categorie');
      }

      return ids;
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
        $('#id_marque').select2({ placeholder:'Sélectionner une marque', width:'100%', allowClear:true, dropdownCssClass: 'animate-fadeInCalendar' });
        $('#id_categorie').select2({ minimumResultsForSearch: Infinity, placeholder:'Sélectionner une catégorie', dropdownCssClass: 'animate-fadeInCalendar' });
        $('#id_carburant').select2({ minimumResultsForSearch: Infinity, placeholder:'Sélectionner un carburant', dropdownCssClass: 'animate-fadeInCalendar' });
        // Laisse HTMX injecter #id_sous_categorie
        $('#id_duree').select2({ minimumResultsForSearch: Infinity, placeholder:'Durée', dropdownCssClass: 'animate-fadeInCalendar' });
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

    // ---- Catégorie -> charge utile
    // Ne gère QUE la valeur du champ caché id_charge_utile
    bindCategorie() {
      const cat = document.getElementById('id_categorie');
      if (!cat) return;

      const toggle = () => {
        const selectedCat = (cat.value || '').trim();
        const isTPC = selectedCat === '520';

        const cu = document.getElementById('id_charge_utile'); // champ caché
        if (cu) {
          cu.value = isTPC ? '3500' : '0';
          cu.removeAttribute('disabled'); // garantir la soumission
          // console.log('[ContractForm] Charge utile (cachée) =', cu.value);
        }

        this.app.clearCache();
        this.app.validate(false);
      };

      // init
      toggle();

      // events
      cat.addEventListener('change', toggle, { signal: this.signal });

        // jQuery/Select2
        if (typeof $ !== 'undefined' && $.fn?.select2) {
          $('#id_categorie')
            .off('.app') // évite doublons
            .on('change.app select2:select.app select2:clear.app', toggle);
        }
      } // Fin de bindCategorie()

    // ---- Affichage simulation / formulaire + re-init Select2 sur sous-catégorie
    bindSimulationView() {
      const handler = (evt) => {
        const target = evt.detail?.target;
        if (!target) return;

        const formWrap = document.getElementById('contrat-form-wrapper');
        const simulationResult = document.getElementById('simulation-result');
        const emissionResult = document.getElementById('emission-result');

        // Simulation
        if (target === simulationResult) {
          if (target.innerHTML.trim()) {
            formWrap?.classList.add('hidden');
            simulationResult.classList.remove('hidden');
          } else {
            formWrap?.classList.remove('hidden');
            simulationResult.classList.add('hidden');
          }
        }

        // Emission
        if (target === emissionResult && target.innerHTML.trim()) {
          simulationResult?.classList.add('hidden');
          emissionResult.classList.remove('hidden');
        }

        // Ré-init Select2 après swap HTMX de la sous-catégorie
        if (target.id === 'sous-categorie-wrapper' && typeof $ !== 'undefined' && $.fn?.select2) {
          const $sc = $('#id_sous_categorie');
          if ($sc.length) {
            if ($sc.data('select2')) $sc.select2('destroy');
            $sc.select2({
              minimumResultsForSearch: Infinity,
              placeholder: 'Genre / Sous-catégorie',
              width: '100%',
              dropdownCssClass: 'animate-fadeInCalendar'
            });
            this.app.validate(false);
          }
        }
      };

      document.body.addEventListener('htmx:afterSwap', handler, { signal: this.signal });
    }

    // ---- Boutons (Modifier Contrat)
    bindButtons() {
      const click = (e) => {
        if (e.target.closest('#btn-modifier-contrat')) {
          document.getElementById('contrat-form-wrapper')?.classList.remove('hidden');
          document.getElementById('simulation-result')?.classList.add('hidden');
          document.getElementById('emission-result')?.classList.add('hidden');
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      };
      document.body.addEventListener('click', click, { signal: this.signal });
    }

    // ---- Teardown
    destroy() {
      // tout listener a été attaché avec {signal: this.signal}
      console.log('ContractFormManager destroyed.');
    }
  } // Fin de ContractFormManager

  // === BOOT ===
  document.addEventListener('DOMContentLoaded', () => {
    window.appManager = new AppManager();
  });

  window.addEventListener('beforeunload', () => {
    window.appManager?.destroy();
  });
})();