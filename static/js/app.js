/* static/js/app.js - Version unifiée HTMX + gestion formulaire contrat */
(() => {
  'use strict';

  // ======================================
  // === APP GLOBAL ===
  // ======================================
  class AppManager {
    constructor() {
      this.timers = new Map();
      this.cache = new Map();
      this.ac = new AbortController();
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

    // -------- Context Detection
    detectContext() {
      if (document.getElementById('contrat-form')) {
        this.contract = new ContractFormManager(this, this.ac.signal);
        this.bindContractValidation();
      }
      if (document.querySelector('.profile-form')) {
        this.initProfile();
      }
    }

    initProfile() { /* réservé */ }

    // -------- Validation temps réel (côté client)
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
        if (!el || el.offsetParent === null || el.disabled) continue;

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

    // -------- Utilitaires
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
      const colorMap = { success: 'bg-green-600', error: 'bg-red-600', warning: 'bg-yellow-600', info: 'bg-blue-600' };
      const iconMap = { success: 'fa-check-circle', error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };
      const color = colorMap[type] || 'bg-blue-600';
      const icon = iconMap[type] || 'fa-info-circle';

      const existing = document.querySelectorAll('.app-toast');
      if (existing.length >= 3) existing[0].remove();

      const el = document.createElement('div');
      el.className = `app-toast fixed top-4 right-4 ${color} text-white px-6 py-3 rounded-lg shadow-lg z-50 transform translate-x-full transition-transform duration-300`;
      el.setAttribute('role', 'alert');
      el.innerHTML = `
        <div class="flex items-center space-x-3">
          <i class="fas ${icon}" aria-hidden="true"></i>
          <span>${this.escape(msg)}</span>
          <button class="ml-2 hover:opacity-75 focus:outline-none" aria-label="Fermer">&times;</button>
        </div>`;
      el.querySelector('button').onclick = () => {
        el.style.transform = 'translateX(100%)';
        setTimeout(() => el.remove(), 300);
      };
      document.body.appendChild(el);
      setTimeout(() => el.style.transform = 'translateX(0)', 10);
      setTimeout(() => {
        el.style.transform = 'translateX(100%)';
        setTimeout(() => el.remove(), 300);
      }, ms);
    }

    escape(str) { const div = document.createElement('div'); div.textContent = str; return div.innerHTML; }

    // -------- HTMX global + Spinner
    bindGlobalEvents() {
      const signal = this.ac.signal;

      document.body.addEventListener('htmx:configRequest', (evt) => {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (csrf) evt.detail.headers['X-CSRFToken'] = csrf;
      }, { signal });

      ['htmx:responseError','htmx:sendError','htmx:timeout'].forEach(evtName => {
        document.body.addEventListener(evtName, (evt) => {
          this.hideSpinner();
          let msg = "Une erreur est survenue.";
          if (evt.detail?.xhr) {
            const s = evt.detail.xhr.status;
            if (s === 0) msg = "Erreur de connexion réseau. Vérifiez votre internet.";
            else if (s >= 500) msg = "Erreur serveur (500). Réessayez plus tard.";
            else if (s === 404) msg = "Ressource non trouvée.";
            else if (s === 403) msg = "Accès refusé.";
          }
          this.toast(msg, 'error');
          const triggeringElt = evt.detail?.requestConfig?.elt;
          if (triggeringElt && triggeringElt.disabled) triggeringElt.disabled = false;
        }, { signal });
      });

      document.body.addEventListener('htmx:beforeRequest', () => this.showSpinner(), { signal });
      document.body.addEventListener('htmx:afterRequest', () => this.hideSpinner(), { signal });
    }

    showSpinner() {
      const spinner = document.getElementById('global-spinner');
      if (!spinner) return;
      spinner.classList.remove('hidden');
      if (this.spinnerTimer) clearTimeout(this.spinnerTimer);
      this.spinnerTimer = setTimeout(() => {
        this.hideSpinner();
        this.toast('La requête prend plus de temps que prévu.', 'warning');
      }, 60000);
    }

    hideSpinner() {
      const spinner = document.getElementById('global-spinner');
      if (!spinner) return;
      spinner.classList.add('hidden');
      if (this.spinnerTimer) { clearTimeout(this.spinnerTimer); this.spinnerTimer = null; }
    }

    // -------- Inactivité
    initInactivity() {
      this.inactivity = new InactivityManager({
        appSignal: this.ac.signal,
        logoutAfter: 120 * 60 * 1000,
        warningBefore: 5 * 60 * 1000,
        onWarning: () => this.toast('Vous serez déconnecté dans 5 minute par inactivité.', 'warning', 60000)
      });
    }

    // -------- Nettoyage
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
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'csrfmiddlewaretoken';
        input.value = csrf;
        form.appendChild(input);
      }
      document.body.appendChild(form);
      form.submit();
    }
    destroy() { clearTimeout(this.timer); clearTimeout(this.warnTimer); }
  }

  // ======================================
  // === CONTRACT FORM MANAGER (UNIFIÉ) ===
  // ======================================
  class ContractFormManager {
    constructor(app, signal) {
      this.app = app;
      this.signal = signal;

      this.STORAGE_KEY = 'contrat_form_data';

      this.initWidgets();
      this.bindSelect2Bridge();         // Pont Select2 → événements natifs
      this.bindUppercase();             // Uppercase auto
      this.bindCategorie();             // Bascule catégories/sous-catégories/charge utile
      this.bindSimulationView();        // Gestion affichages après injection HTMX
      this.bindButtons();               // Bouton "modifier contrat"
      this.bindHTMXHooks();             // Sauvegarde/restore + succès émission

      // Expose pour un bouton "Restaurer" éventuel
      window.showContractForm = this.showFormWrapper.bind(this);

      // Restauration initiale
      this.restoreFormData();
      // Enforce required après restauration
      setTimeout(() => { this.toggleDependentFields(); this.enforceRequired(); }, 300);
    }

    // -------- Champs requis dynamiques
    requiredIds() {
      const base = [
        'id_prenom','id_nom','id_telephone','id_adresse',
        'id_immatriculation','id_marque','id_modele','id_categorie',
        'id_carburant','id_puissance_fiscale','id_nombre_places',
        'id_duree','id_date_effet'
      ];
      const sc = document.getElementById('id_sous_categorie');
      if (sc && !sc.disabled && sc.offsetParent !== null) base.push('id_sous_categorie');
      // const cu = document.getElementById('id_charge_utile'); // <-- CORRIGÉ (Supprimé)
      // const cat = document.getElementById('id_categorie')?.value; // <-- CORRIGÉ (Supprimé)
      // if (cu && cat === '520') base.push('id_charge_utile'); // <-- CORRIGÉ (Supprimé)
      return base;
    }
    enforceRequired() {
      this.requiredIds().forEach(id => {
        const el = document.getElementById(id);
        if (el && el.offsetParent !== null) {
          el.setAttribute('required','required');
          el.setAttribute('aria-required','true');
        }
      });
    }

    // -------- Widgets
    initWidgets() {
      this.initSelect2();
      this.initDatePicker();
    }
    initSelect2() {
      if (typeof $ === 'undefined' || !$.fn?.select2) return;
      try {
        const cfg = { width:'100%', dropdownCssClass:'animate-fadeInCalendar' };
        $('#id_marque').select2({ ...cfg, placeholder:'Sélectionner une marque', allowClear:true });
        $('#id_categorie').select2({ ...cfg, minimumResultsForSearch:Infinity, placeholder:'Sélectionner une catégorie' });
        $('#id_carburant').select2({ ...cfg, minimumResultsForSearch:Infinity, placeholder:'Sélectionner un carburant' });
        $('#id_duree').select2({ ...cfg, minimumResultsForSearch:Infinity, placeholder:'Durée' });
      } catch (e) { console.error('Erreur Select2:', e); }
    }
    initDatePicker() {
      if (typeof flatpickr === 'undefined') return;
      try {
        flatpickr('#id_date_effet', {
          locale:'fr', dateFormat:'Y-m-d', altInput:true, altFormat:'d/m/Y',
          minDate:'today', maxDate:new Date().fp_incr(60),
          onChange: () => this.app.clearCache()
        });
      } catch (e) { console.error('Erreur Flatpickr:', e); }
    }

    // -------- Uppercase auto
    bindUppercase() {
      const form = document.getElementById('contrat-form');
      if (!form) return;
      const fields = form.querySelectorAll(
        'input[type="text"]:not([data-no-uppercase]):not([readonly]), textarea:not([data-no-uppercase])'
      );
      fields.forEach(input => {
        input.addEventListener('input', function () {
          if (this.dataset.noUppercase !== undefined) return;
          const { selectionStart:start, selectionEnd:end } = this;
          const oldValue = this.value;
          const newValue = oldValue.toUpperCase();
          if (oldValue !== newValue) {
            this.value = newValue;
            this.setSelectionRange(start, end);
          }
        }, { signal: this.signal });
      });
    }

    // -------- Pont Select2 → événements natifs pour HTMX
    bindSelect2Bridge() {
      if (typeof $ === 'undefined' || !$.fn?.select2) return;
      // <-- CORRIGÉ : Ajout de #id_sous_categorie
      $('#id_categorie, #id_marque, #id_carburant, #id_duree, #id_modele, #id_sous_categorie').on(
        'select2:select select2:clear select2:unselect',
        (e) => e.target.dispatchEvent(new Event('change', { bubbles:true }))
      );
      // fallback jQuery change → input
      $('#id_marque, #id_categorie, #id_carburant, #id_modele')
        .on('change.app', function(){ this.dispatchEvent(new Event('input', { bubbles:true })); });
    }

    // -------- Logique Catégorie/Sous-catégorie/Charge utile
    bindCategorie() {
      const cat = document.getElementById('id_categorie');
      if (!cat) return;
      const handler = this.toggleDependentFields.bind(this);
      cat.addEventListener('change', handler, { signal: this.signal });

      // Select2 déjà ponté. Exécution initiale
      this.toggleDependentFields();
    }

    toggleDependentFields() {
      const categorieSelect = document.getElementById('id_categorie');
      const sousCatWrapper = document.getElementById('sous-categorie-wrapper');
      // const chargeUtileWrapper = document.getElementById('charge-utile-wrapper'); // <-- CORRIGÉ (Supprimé)
      if (!categorieSelect) return;

      let val = categorieSelect.value;
      if (typeof $!== 'undefined' &&$.fn?.select2) {
        const $cat = $(categorieSelect);
        if ($cat.data('select2')) val = $cat.val();
      }
      val = String(val || '').trim();
      const isTPC = val === '520';
      const isMoto = val === '550';
      const showSousCat = isTPC || isMoto;

      // Wrapper sous-catégorie <-- CORRIGÉ (Logique de chargement manuel remplacée)
      if (sousCatWrapper) {
        if (showSousCat) {
          sousCatWrapper.classList.remove('hidden');
          const sousCatField = document.getElementById('id_sous_categorie');

          // Si on doit afficher et que rien n'est encore injecté, on force un change
          if (!sousCatField) {
            // délenche le mécanisme HTMX déjà câblé sur le select catégorie
            categorieSelect.dispatchEvent(new Event('change', { bubbles: true }));
          }
        } else {
          sousCatWrapper.classList.add('hidden');
        }
      }

      // Champ sous-catégorie
      const sousCatField = document.getElementById('id_sous_categorie');
      if (sousCatField) {
        if (showSousCat) {
          sousCatField.disabled = false;
          sousCatField.setAttribute('required','required');
          sousCatField.setAttribute('aria-required','true');
        } else {
          sousCatField.disabled = true;
          sousCatField.removeAttribute('required');
          sousCatField.setAttribute('aria-required','false');
          sousCatField.setAttribute('aria-disabled','true');
          if (typeof $!== 'undefined' &&$.fn?.select2 && $(sousCatField).data('select2')) {
            $(sousCatField).val('').trigger('change.select2');
          } else {
            sousCatField.value = '';
          }
        }
      }

      // Charge utile toujours caché → on force juste la valeur <-- CORRIGÉ (Logique simplifiée)
      const chargeUtileField = document.getElementById('id_charge_utile');
      if (chargeUtileField) {
        chargeUtileField.disabled = false;      // ne jamais désactiver un champ à soumettre
        chargeUtileField.removeAttribute('required');
        chargeUtileField.value = isTPC ? '3500' : '0';
      }

      this.app.clearCache();
      this.app.validate(false);
    }

    // -------- Sauvegarde session
    saveFormData() {
      const form = document.getElementById('contrat-form');
      if (!form) return;
      try {
        const fd = new FormData(form);
        const obj = {};
        fd.forEach((value, key) => {
          if (key !== 'csrfmiddlewaretoken' && value) obj[key] = value;
        });
        sessionStorage.setItem(this.STORAGE_KEY, JSON.stringify(obj));
      } catch (e) { console.warn('Erreur sauvegarde formulaire:', e); }
    }
    restoreFormData() {
      const form = document.getElementById('contrat-form');
      if (!form) return;
      try {
        const raw = sessionStorage.getItem(this.STORAGE_KEY);
        if (!raw) return;
        const obj = JSON.parse(raw);
        Object.keys(obj).forEach(k => {
          const el = form.querySelector(`[name="${CSS.escape(k)}"]`);
          if (!el) return;
          if (el.type === 'checkbox' || el.type === 'radio') {
            el.checked = el.value === obj[k];
          } else {
            el.value = obj[k];
            if (typeof $!== 'undefined' &&$.fn?.select2) {
              const $el = $(el);
              if ($el.hasClass('select2-hidden-accessible')) {
                try { $el.val(obj[k]).trigger('change.select2'); } catch {}
              }
            }
          }
        });
      } catch (e) { console.warn('Erreur restauration formulaire:', e); }
    }
    clearFormData() {
      try { sessionStorage.removeItem(this.STORAGE_KEY); } catch {}
    }

    // -------- Affichage wrapper formulaire
    showFormWrapper() {
      const formWrapper = document.getElementById('contrat-form-wrapper');
      const simulationResult = document.getElementById('simulation-result');
      const emissionResult = document.getElementById('emission-result');
      formWrapper?.classList.remove('hidden');
      if (simulationResult) { simulationResult.classList.add('hidden'); simulationResult.innerHTML = ''; }
      if (emissionResult)   { emissionResult.classList.add('hidden');   emissionResult.innerHTML   = ''; }
      this.restoreFormData();
      setTimeout(() => formWrapper?.scrollIntoView({ behavior:'smooth', block:'start' }), 100);
    }

    // -------- Hooks HTMX ciblés formulaire
    bindHTMXHooks() {
      // Sauvegarde avant requête
      document.body.addEventListener('htmx:beforeRequest', (e) => {
        const elt = e.detail?.elt;
        if (elt && elt.closest('#contrat-form')) this.saveFormData();
      }, { signal: this.signal });

      // Après swap
      document.body.addEventListener('htmx:afterSwap', (e) => {
        const target = e.detail?.target;
        if (!target) return;

        // Réinit Select2 sous-catégorie après injection
        if (target.id === 'sous-categorie-wrapper' || target.querySelector?.('#id_sous_categorie')) {
          if (typeof $!== 'undefined' &&$.fn?.select2) {
            const $sc = $('#id_sous_categorie');
            if ($sc.length) {
              if ($sc.data('select2')) $sc.select2('destroy');
              $sc.select2({
                minimumResultsForSearch: Infinity,
                placeholder: 'Genre / Sous-catégorie',
                width: '100%',
                dropdownCssClass: 'animate-fadeInCalendar'
              });
            }
          }
          setTimeout(() => { this.toggleDependentFields(); this.enforceRequired(); }, 150);
        }
      }, { signal: this.signal });

      // Détection succès émission pour purge session
      document.body.addEventListener('htmx:afterOnLoad', (e) => {
        const body = e.detail?.xhr?.responseText || '';
        const successIndicators = ['bg-green-','Contrat émis','Émission réussie','success-message','alert-success'];
        if (successIndicators.some(ind => body.includes(ind))) {
          this.clearFormData();
          if (this.app?.toast) this.app.toast('Contrat émis avec succès !', 'success', 5000);
        }
      }, { signal: this.signal });

      // Bouton "restaurer"
      document.body.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="restore-form"]');
        if (btn) { e.preventDefault(); this.showFormWrapper(); }
      }, { signal: this.signal });

      // Sauvegarde avant quitter
      window.addEventListener('beforeunload', () => {
        const form = document.getElementById('contrat-form');
        if (!form) return;
        const fd = new FormData(form);
        let hasData = false;
        fd.forEach((value, key) => {
          if (key !== 'csrfmiddlewaretoken' && value) hasData = true;
        });
        if (hasData) this.saveFormData();
      }, { signal: this.signal });
    }

    // -------- Affichages après injection HTMX
    bindSimulationView() {
      const handler = (evt) => {
        const target = evt.detail?.target;
        if (!target) return;

        const formWrap = document.getElementById('contrat-form-wrapper');
        const simulationResult = document.getElementById('simulation-result');
        const emissionResult = document.getElementById('emission-result');

        if (target === simulationResult && target.innerHTML.trim()) {
          formWrap?.classList.add('hidden');
          simulationResult.classList.remove('hidden');
        }
        if (target === emissionResult && target.innerHTML.trim()) {
          simulationResult?.classList.add('hidden');
          emissionResult.classList.remove('hidden');
        }
      };
      document.body.addEventListener('htmx:afterSwap', handler, { signal: this.signal });
    }

    // -------- Boutons
    bindButtons() {
      const clickHandler = (e) => {
        if (e.target.closest('#btn-modifier-contrat')) {
          document.getElementById('contrat-form-wrapper')?.classList.remove('hidden');
          document.getElementById('simulation-result')?.classList.add('hidden');
          document.getElementById('emission-result')?.classList.add('hidden');
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      };
      document.body.addEventListener('click', clickHandler, { signal: this.signal });
    }

    // -------- Nettoyage
    destroy() {
      if (typeof $ !== 'undefined') {
        $('#id_categorie, #id_marque, #id_carburant, #id_duree, #id_modele, #id_sous_categorie')
          .off('select2:select select2:clear select2:unselect change.app');
      }
    }
  }

  // ======================================
  // === INITIALISATION ===
  // ======================================
  document.addEventListener('DOMContentLoaded', () => {
    window.appManager = new AppManager();
  });
  window.addEventListener('beforeunload', () => {
    window.appManager?.destroy();
  });

})();