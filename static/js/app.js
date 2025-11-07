/* static/js/app.js - Version corrigée pour HTMX */
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

    initProfile() {
      // Réservé pour gestion profil utilisateur
    }

    // -------- Validation temps réel du formulaire contrat
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

    clearCache() {
      this.cache.clear();
    }

    toast(msg, type = 'info', ms = 5000) {
      const colorMap = {
        success: 'bg-green-600',
        error: 'bg-red-600',
        warning: 'bg-yellow-600',
        info: 'bg-blue-600'
      };
      const iconMap = {
        success: 'fa-check-circle',
        error: 'fa-times-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
      };

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

      const closeBtn = el.querySelector('button');
      if (closeBtn) {
        closeBtn.onclick = () => {
          el.style.transform = 'translateX(100%)';
          setTimeout(() => el.remove(), 300);
        };
      }

      document.body.appendChild(el);
      setTimeout(() => el.style.transform = 'translateX(0)', 10);
      setTimeout(() => {
        el.style.transform = 'translateX(100%)';
        setTimeout(() => el.remove(), 300);
      }, ms);
    }

    escape(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    // -------- Événements globaux HTMX + Spinner
    bindGlobalEvents() {
      const signal = this.ac.signal;

      // CSRF Token pour toutes les requêtes HTMX
      document.body.addEventListener('htmx:configRequest', (evt) => {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (csrf) evt.detail.headers['X-CSRFToken'] = csrf;
      }, { signal });

      // Gestion des erreurs réseau
      ['htmx:responseError', 'htmx:sendError', 'htmx:timeout'].forEach(evtName => {
        document.body.addEventListener(evtName, (evt) => {
          this.hideSpinner();

          let msg = "Une erreur est survenue.";
          if (evt.detail.xhr) {
            if (evt.detail.xhr.status === 0) msg = "Erreur de connexion réseau. Vérifiez votre internet.";
            else if (evt.detail.xhr.status >= 500) msg = "Erreur serveur (500). Réessayez plus tard.";
            else if (evt.detail.xhr.status === 404) msg = "Ressource non trouvée.";
            else if (evt.detail.xhr.status === 403) msg = "Accès refusé.";
          }
          this.toast(msg, 'error');

          // Déverrouiller manuellement les boutons si nécessaire
          const triggeringElt = evt.detail.requestConfig?.elt;
          if (triggeringElt && triggeringElt.disabled) {
            triggeringElt.disabled = false;
          }
        }, { signal });
      });

      // Spinner global
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

      if (this.spinnerTimer) {
        clearTimeout(this.spinnerTimer);
        this.spinnerTimer = null;
      }
    }

    // -------- Gestion inactivité utilisateur
    initInactivity() {
      this.inactivity = new InactivityManager({
        appSignal: this.ac.signal,
        logoutAfter: 10 * 60 * 1000, // 10 minutes
        warningBefore: 60 * 1000, // 1 minute
        onWarning: () => this.toast('Vous serez déconnecté dans 1 minute par inactivité.', 'warning', 60000)
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
    constructor({
      logoutAfter = 600000,
      warningBefore = 60000,
      logoutUrl = '/accounts/logout/',
      onWarning = null,
      appSignal = null
    } = {}) {
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
      ['load', 'mousemove', 'keypress', 'click', 'scroll', 'touchstart'].forEach(ev =>
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

    warn() {
      if (this.onWarning) this.onWarning();
    }

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

    destroy() {
      clearTimeout(this.timer);
      clearTimeout(this.warnTimer);
    }
  }

  // ======================================
  // === CONTRACT FORM MANAGER (CORRIGÉ) ===
  // ======================================
  class ContractFormManager {
    constructor(app, signal) {
      this.app = app;
      this.signal = signal;
      this.initWidgets();
      // ⚠️ SUPPRIMÉ : this.bindCategorie() - Conflit avec HTMX
      this.bindSelect2Bridge(); // ✅ AJOUTÉ : Pont Select2 → HTMX
      this.bindSimulationView();
      this.bindButtons();
    }

    // -------- Champs requis dynamiques (Validation JS côté client)
    requiredIds() {
      const baseIds = [
        'id_prenom', 'id_nom', 'id_adresse', 'id_telephone',
        'id_immatriculation', 'id_marque', 'id_modele', 'id_categorie',
        'id_carburant', 'id_puissance_fiscale', 'id_nombre_places',
        'id_duree', 'id_date_effet'
      ];

      // Ajout dynamique de sous-catégorie si visible et actif
      const scSelect = document.getElementById('id_sous_categorie');
      if (scSelect && !scSelect.disabled && scSelect.offsetParent !== null) {
        baseIds.push('id_sous_categorie');
      }

      return baseIds;
    }

    // -------- Initialisation des widgets (Select2, Flatpickr)
    initWidgets() {
      this.initSelect2();
      this.initDatePicker();
    }

    initSelect2() {
      if (typeof $ === 'undefined' || !$.fn?.select2) return;

      try {
        const commonConfig = {
          width: '100%',
          dropdownCssClass: 'animate-fadeInCalendar'
        };

        $('#id_marque').select2({
          ...commonConfig,
          placeholder: 'Sélectionner une marque',
          allowClear: true
        });

        $('#id_categorie').select2({
          ...commonConfig,
          minimumResultsForSearch: Infinity,
          placeholder: 'Sélectionner une catégorie'
        });

        $('#id_carburant').select2({
          ...commonConfig,
          minimumResultsForSearch: Infinity,
          placeholder: 'Sélectionner un carburant'
        });

        $('#id_duree').select2({
          ...commonConfig,
          minimumResultsForSearch: Infinity,
          placeholder: 'Durée'
        });
      } catch (e) {
        console.error('Erreur Select2:', e);
      }
    }

    initDatePicker() {
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
      } catch (e) {
        console.error('Erreur Flatpickr:', e);
      }
    }

    // -------- ✅ NOUVEAU : Pont Select2 → HTMX
    // Force les événements natifs 'change' pour que HTMX les détecte
    bindSelect2Bridge() {
      if (typeof $ === 'undefined' || !$.fn?.select2) return;

      $('#id_categorie, #id_marque, #id_carburant, #id_duree').on(
        'select2:select select2:clear select2:unselect',
        (e) => {
          // Déclenche un événement natif 'change' pour HTMX
          e.target.dispatchEvent(new Event('change', { bubbles: true }));
        }
      );
    }

    // -------- Gestion des vues après injection HTMX
    bindSimulationView() {
      const handler = (evt) => {
        const target = evt.detail?.target;
        if (!target) return;

        const formWrap = document.getElementById('contrat-form-wrapper');
        const simulationResult = document.getElementById('simulation-result');
        const emissionResult = document.getElementById('emission-result');

        // Affichage résultat simulation
        if (target === simulationResult && target.innerHTML.trim()) {
          formWrap?.classList.add('hidden');
          simulationResult.classList.remove('hidden');
        }

        // Affichage résultat émission
        if (target === emissionResult && target.innerHTML.trim()) {
          simulationResult?.classList.add('hidden');
          emissionResult.classList.remove('hidden');
        }

        // ✅ Réinitialisation Select2 pour sous-catégorie après injection HTMX
        if (target.id === 'sous-categorie-wrapper') {
          const $sc = $(target).find('select');
          if ($sc.length && typeof $ !== 'undefined' && $.fn?.select2) {
            // Détruire l'instance existante si présente
            if ($sc.data('select2')) $sc.select2('destroy');

            // Réinitialiser avec la bonne config
            $sc.select2({
              minimumResultsForSearch: Infinity,
              placeholder: 'Genre / Sous-catégorie',
              width: '100%',
              dropdownCssClass: 'animate-fadeInCalendar'
            });

            // Revalider le formulaire
            this.app.validate(false);
          }
        }
      };

      document.body.addEventListener('htmx:afterSwap', handler, { signal: this.signal });
    }

    // -------- Gestion boutons (Modifier contrat)
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
      // Nettoyage automatique via AbortController signal
      if (typeof $ !== 'undefined') {
        $('#id_categorie, #id_marque, #id_carburant, #id_duree').off('select2:select select2:clear select2:unselect');
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