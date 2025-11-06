/**
 * Service Worker BWHITE DIGITAL
 * Version: 1.0.0
 * Stratégies de cache multiples pour optimiser les performances
 */
{% load static %}
const VERSION = '1.0.0';
// Les noms de cache sont basés sur la version pour le nettoyage à l'activation
const STATIC_CACHE = `bwhite-static-v${VERSION}`;
const DYNAMIC_CACHE = `bwhite-dynamic-v${VERSION}`;

// Ressources critiques à mettre en cache immédiatement (Pre-cache)
// Ces chemins doivent être résolus par le moteur de template Django
const STATIC_ASSETS = [
  '/',  // landing page
  '{% static "css/main.css" %}',
  '{% static "js/main.js" %}',
  '{% static "icons/icon-192x192.png" %}',
  '{% static "icons/icon-512x512.png" %}',
  '/offline.html',
];

// Configuration
const CONFIG = {
  fetchTimeout: 8000,
  maxCacheItems: 50,
  maxCacheAge: 7 * 24 * 60 * 60 * 1000, // 7 jours en ms (pour cleanExpiredCache)
};

/**
 * Fetch avec timeout et retry
 */
async function fetchWithTimeout(request, timeout = CONFIG.fetchTimeout, retries = 1) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(request, {
      signal: controller.signal,
      credentials: 'same-origin',
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);

    // Retry une fois si abort/network error
    if (retries > 0 && (error.name === 'AbortError' || error.name === 'TypeError')) {
      console.log(`🔄 Retry fetch: ${request.url}`);
      await new Promise(resolve => setTimeout(resolve, 1000)); // Délai 1s
      return fetchWithTimeout(request, timeout, retries - 1);
    }

    throw error;
  }
}

/**
 * Limiter la taille du cache (FIFO)
 * Appliqué uniquement au DYNAMIC_CACHE
 */
async function trimCache(cacheName, maxItems = CONFIG.maxCacheItems) {
  if (cacheName !== DYNAMIC_CACHE) return; // Sécurité: ne pas trimmer le cache statique

  try {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();

    if (keys.length > maxItems) {
      console.log(`🗑️ Trim cache ${cacheName}: ${keys.length} -> ${maxItems}`);
      // Supprime les éléments les plus anciens (FIFO)
      const deletePromises = keys
        .slice(0, keys.length - maxItems)
        .map(key => cache.delete(key));
      await Promise.all(deletePromises);
    }
  } catch (error) {
    console.error(`❌ Erreur trim cache ${cacheName}:`, error);
  }
}

/**
 * Supprimer les entrées de cache expirées
 * NOTE: Se base sur le header 'Date' de la réponse, qui est la date de la réponse du serveur,
 * et non la date de mise en cache par le SW.
 */
async function cleanExpiredCache(cacheName) {
  try {
    const cache = await caches.open(cacheName);
    const requests = await cache.keys();
    const now = Date.now();

    const cleanPromises = requests.map(async (request) => {
      const response = await cache.match(request);
      if (response) {
        // Le header 'Date' n'est pas toujours fiable ou présent sur une réponse en cache
        const dateHeader = response.headers.get('date');
        if (dateHeader) {
          const responseDate = new Date(dateHeader).getTime();
          if (now - responseDate > CONFIG.maxCacheAge) {
            console.log(`🧹 Cache expiré (${cacheName}): ${request.url}`);
            return cache.delete(request);
          }
        }
      }
    });

    await Promise.all(cleanPromises);
  } catch (error) {
    console.error(`❌ Erreur clean cache ${cacheName}:`, error);
  }
}

// ========================================
// ÉVÉNEMENTS DU SERVICE WORKER
// ========================================

/**
 * Installation
 */
self.addEventListener('install', (event) => {
  console.log(`🚀 [SW ${VERSION}] Installation...`);

  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => {
        console.log('📦 Mise en cache des ressources statiques...');
        // On gère la requête '/offline.html' séparément pour éviter les problèmes de cross-origin
        // et s'assurer qu'elle est mise en cache même si le réseau échoue pour d'autres assets.
        const assetsToCache = STATIC_ASSETS.filter(asset => asset !== '/offline.html');
        const offlinePageRequest = STATIC_ASSETS.find(asset => asset === '/offline.html');

        return Promise.all([
            cache.addAll(assetsToCache),
            fetch(offlinePageRequest).then(response => cache.put(offlinePageRequest, response)),
        ]);
      })
      .then(() => {
        console.log(`✅ [SW ${VERSION}] Installé avec succès`);
        return self.skipWaiting(); // Active immédiatement la nouvelle version
      })
      .catch(error => {
        console.error('❌ Erreur installation (un ou plusieurs assets ont échoué):', error);
        // L'installation échoue si addAll échoue, mais on peut continuer si c'est juste un warning
        // Ici, on laisse l'erreur remonter pour un comportement strict.
      })
  );
});

/**
 * Activation
 */
self.addEventListener('activate', (event) => {
  console.log(`🔄 [SW ${VERSION}] Activation...`);

  event.waitUntil(
    Promise.all([
      // Supprimer les anciens caches (basés sur le nom)
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            // Supprime les caches qui ne correspondent pas aux noms actuels
            if (cacheName !== STATIC_CACHE && cacheName !== DYNAMIC_CACHE) {
              console.log('🗑️ Suppression ancien cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      }),

      // Nettoyer les entrées expirées dans le cache dynamique
      cleanExpiredCache(DYNAMIC_CACHE),

      // Prendre le contrôle immédiatement
      self.clients.claim(),
    ])
      .then(() => {
        console.log(`✅ [SW ${VERSION}] Activé`);
      })
      .catch(error => {
        console.error('❌ Erreur activation:', error);
      })
  );
});

/**
 * Interception des requêtes
 */
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignorer les requêtes non-GET ou cross-origin qui ne sont pas des documents
  if (request.method !== 'GET') {
    return;
  }

  // Ignorer les requêtes Chrome extension
  if (url.protocol === 'chrome-extension:') {
    return;
  }

  // Ignorer les assets tiers sauf s'ils sont des images
  if (!url.pathname.startsWith('/static/') && url.origin !== location.origin && request.destination !== 'image') {
      return;
  }

  // Router selon le type de ressource
  if (request.destination === 'image') {
    event.respondWith(handleImageRequest(request)); // Cache First
  } else if (url.pathname.startsWith('/api/')) {
    event.respondWith(handleAPIRequest(request)); // Network First
  } else if (request.destination === 'document') {
    event.respondWith(handleDocumentRequest(request)); // Network First with Cache Fallback
  } else if (request.destination === 'style' || request.destination === 'script') {
    event.respondWith(handleStaticRequest(request)); // Cache First (pour les assets versionnés)
  } else {
    // Autres ressources (fonts, XHR non-API, etc.) : Network First
    event.respondWith(handleNetworkFirst(request));
  }
});

// ========================================
// STRATÉGIES DE CACHE
// ========================================

/**
 * Cache First - Pour les images (DYNAMIC_CACHE)
 */
async function handleImageRequest(request) {
  try {
    // 1. Chercher dans le cache
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    // 2. Sinon, fetch depuis le réseau
    const networkResponse = await fetchWithTimeout(request);

    // 3. Mettre en cache si succès
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
      trimCache(DYNAMIC_CACHE); // Limiter la taille du cache dynamique
    }

    return networkResponse;
  } catch (error) {
    console.log('📷 Image non disponible:', request.url, error.message);

    // Retourner une image placeholder SVG
    return new Response(
      '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><rect fill="#ddd" width="200" height="200"/><text x="100" y="100" text-anchor="middle" dominant-baseline="middle" fill="#999" font-size="12">Image non disponible</text></svg>',
      { headers: { 'Content-Type': 'image/svg+xml' } }
    );
  }
}

/**
 * Network First - Pour les API (DYNAMIC_CACHE)
 */
async function handleAPIRequest(request) {
  try {
    // 1. Essayer le réseau d'abord
    const networkResponse = await fetchWithTimeout(request);

    // 2. Mettre en cache si GET et succès
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
      trimCache(DYNAMIC_CACHE);
    }

    return networkResponse;
  } catch (error) {
    console.log('🌐 API hors-ligne:', request.url, error.message);

    // 3. Fallback vers le cache pour les GET
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      console.log('✅ API cache hit:', request.url);
      return cachedResponse;
    }

    // 4. Retourner une erreur JSON structurée
    return new Response(
      JSON.stringify({
        error: 'Service indisponible hors-ligne',
        offline: true,
        timestamp: new Date().toISOString(),
        method: request.method,
        url: request.url,
      }),
      {
        status: 503,
        statusText: 'Service Unavailable',
        headers: {
          'Content-Type': 'application/json',
          'X-Offline': 'true',
        },
      }
    );
  }
}
/**
 * Network ONLY pour les pages critiques, avec fallback offline.html
 * On évite 'Network First' pour le dashboard pour garantir des données financières à jour.
 */
async function handleDocumentRequest(request) {
  const url = new URL(request.url);

  // Liste des routes qui ne DOIVENT PAS être mises en cache (données financières sensibles)
  const NO_CACHE_ROUTES = [
      '/dashboard/',
      '/payments/',
      '/contracts/',
      '/accounts/profile/'
  ];

  const isCritical = NO_CACHE_ROUTES.some(route => url.pathname.startsWith(route));

  try {
    // Toujours tenter le réseau en premier
    const networkResponse = await fetchWithTimeout(request);

    if (networkResponse && networkResponse.ok) {
       // On ne met en cache que si ce N'EST PAS une route critique
       if (!isCritical) {
           const cache = await caches.open(DYNAMIC_CACHE);
           cache.put(request, networkResponse.clone());
       }
       return networkResponse;
    }
  } catch (error) {
    console.log('Document hors-ligne:', request.url);

    // Si hors-ligne, essayer le cache SEULEMENT si ce n'est pas critique
    if (!isCritical) {
        const cachedResponse = await caches.match(request);
        if (cachedResponse) return cachedResponse;
    }

    // Fallback final : page hors-ligne générique
    const offlinePage = await caches.match('/offline.html');
    if (offlinePage) return offlinePage;
  }
}
    // 5. Dernier recours
    return new Response(
      '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Hors ligne</title></head><body><h1>Service indisponible</h1><p>Veuillez vérifier votre connexion Internet.</p></body></html>',
      {
        status: 503,
        headers: { 'Content-Type': 'text/html' },
      }
    );
  }
}

/**
 * Cache First - Pour les ressources statiques (CSS, JS) (STATIC_CACHE)
 */
async function handleStaticRequest(request) {
  try {
    // 1. Chercher dans le cache
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    // 2. Sinon, fetch depuis le réseau
    const networkResponse = await fetchWithTimeout(request);

    // 3. Mettre en cache si succès (pas de trim sur le STATIC_CACHE)
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, networkResponse.clone());
    }

    return networkResponse;
  } catch (error) {
    console.log('⚡ Ressource statique non dispo:', request.url, error.message);
    return new Response('', { status: 404 });
  }
}

/**
 * Network First - Pour les autres ressources (DYNAMIC_CACHE)
 */
async function handleNetworkFirst(request) {
  try {
    const networkResponse = await fetchWithTimeout(request);

    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
      trimCache(DYNAMIC_CACHE);
    }

    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    return new Response('', { status: 404 });
  }
}

// ========================================
// GESTION DES MESSAGES (Conservation des fonctions utilitaires)
// ========================================

self.addEventListener('message', (event) => {
  const { action, data, type } = event.data || {};

  if (action === 'SKIP_WAITING') {
    self.skipWaiting();
    event.ports[0]?.postMessage({ success: true, version: VERSION });
  }

  if (action === 'CLEAR_CACHE') {
    clearAllCaches()
      .then(() => event.ports[0]?.postMessage({ success: true }))
      .catch(error => event.ports[0]?.postMessage({ success: false, error: error.message }));
  }

  // Les fonctions GET_CACHE_SIZE et GET_CACHE_INFO sont gourmandes en calcul,
  // elles sont conservées ici pour la complétude du débogage.

  if (action === 'GET_CACHE_SIZE') {
    getCacheSize()
      .then(size => event.ports[0]?.postMessage({ size }))
      .catch(error => event.ports[0]?.postMessage({ size: 0, error: error.message }));
  }

  if (action === 'GET_CACHE_INFO') {
    getCacheInfo()
      .then(info => event.ports[0]?.postMessage({ info }))
      .catch(error => event.ports[0]?.postMessage({ info: null, error: error.message }));
  }

  if (type === 'CHECK_UPDATE') {
    event.waitUntil(
      self.registration.update()
        .then(() => {
          event.ports[0]?.postMessage({
            type: 'UPDATE_CHECKED',
            hasUpdate: self.registration.waiting !== null,
            version: VERSION,
          });
        })
        .catch(error => {
          event.ports[0]?.postMessage({
            type: 'UPDATE_ERROR',
            error: error.message,
          });
        })
    );
  }
});

// ... (Les fonctions utilitaires clearAllCaches, getCacheSize, getCacheInfo restent inchangées)

/**
 * Supprimer tous les caches
 */
async function clearAllCaches() {
  try {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames.map(name => caches.delete(name)));
    console.log('🧹 Tous les caches supprimés');
  } catch (error) {
    console.error('❌ Erreur suppression caches:', error);
    throw error;
  }
}

/**
 * Calculer la taille totale du cache
 */
async function getCacheSize() {
  try {
    const cacheNames = await caches.keys();
    let totalSize = 0;

    for (const name of cacheNames) {
      const cache = await caches.open(name);
      const requests = await cache.keys();

      for (const request of requests) {
        const response = await cache.match(request);
        if (response) {
          // Note: response.blob() peut être coûteux et lent
          const blob = await response.blob();
          totalSize += blob.size;
        }
      }
    }

    return totalSize;
  } catch (error) {
    console.error('❌ Erreur calcul taille cache:', error);
    return 0;
  }
}

/**
 * Obtenir les infos détaillées du cache
 */
async function getCacheInfo() {
  try {
    const cacheNames = await caches.keys();
    const info = {};

    for (const name of cacheNames) {
      const cache = await caches.open(name);
      const keys = await cache.keys();
      info[name] = {
        count: keys.length,
        urls: keys.map(req => req.url),
      };
    }

    return info;
  } catch (error) {
    console.error('❌ Erreur info cache:', error);
    return null;
  }
}

console.log(`🎯 Service Worker BWHITE DIGITAL v${VERSION} initialisé`);