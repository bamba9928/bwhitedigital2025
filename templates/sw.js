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
const STATIC_ASSETS = [
  '/', // L'URL racine pour 'dashboard:home'
  '{% static "css/style.css" %}',
  '{% static "js/app.js" %}',
  '{% static "icons/icon-192x192.png" %}',
  '{% static "icons/icon-512x512.png" %}',
  '/offline.html', // L'URL racine pour 'offline'
];

// Configuration
const CONFIG = {
  fetchTimeout: 8000,
  maxCacheItems: 50,
  maxCacheAge: 7 * 24 * 60 * 60 * 1000, // 7 jours en ms
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
  if (cacheName !== DYNAMIC_CACHE) return; // Sécurité

  try {
    const cache = await caches.open(cacheName);
    const keys = await cache.keys();

    if (keys.length > maxItems) {
      console.log(`🗑️ Trim cache ${cacheName}: ${keys.length} -> ${maxItems}`);
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
 */
async function cleanExpiredCache(cacheName) {
  try {
    const cache = await caches.open(cacheName);
    const requests = await cache.keys();
    const now = Date.now();

    const cleanPromises = requests.map(async (request) => {
      const response = await cache.match(request);
      if (response) {
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
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => {
        console.log(`✅ [SW ${VERSION}] Installé avec succès`);
        return self.skipWaiting(); // Active immédiatement
      })
      .catch(error => {
        console.error('❌ Erreur installation (un ou plusieurs assets ont échoué):', error);
        console.error('Assets concernés:', STATIC_ASSETS);
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
      // Supprimer les anciens caches
      caches.keys().then(cacheNames => {
        return Promise.all(
          cacheNames.map(cacheName => {
            if (cacheName !== STATIC_CACHE && cacheName !== DYNAMIC_CACHE) {
              console.log('🗑️ Suppression ancien cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      }),
      cleanExpiredCache(DYNAMIC_CACHE),
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

  if (request.method !== 'GET') {
    return;
  }
  if (url.protocol === 'chrome-extension:') {
    return;
  }

  // Router selon le type de ressource
  if (request.destination === 'image') {
    event.respondWith(handleImageRequest(request));
  } else if (url.pathname.startsWith('/api/')) {
    event.respondWith(handleAPIRequest(request));
  } else if (request.destination === 'document') {
    event.respondWith(handleDocumentRequest(request));
  } else if (request.destination === 'style' || request.destination === 'script') {
    event.respondWith(handleStaticRequest(request));
  } else {
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
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    const networkResponse = await fetchWithTimeout(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
      trimCache(DYNAMIC_CACHE);
    }
    return networkResponse;
  } catch (error) {
    console.log('📷 Image non disponible:', request.url, error.message);
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
    const networkResponse = await fetchWithTimeout(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, networkResponse.clone());
      trimCache(DYNAMIC_CACHE);
    }
    return networkResponse;
  } catch (error) {
    console.log('🌐 API hors-ligne:', request.url, error.message);
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      console.log('✅ API cache hit:', request.url);
      return cachedResponse;
    }
    return new Response(
      JSON.stringify({
        error: 'Service indisponible hors-ligne',
        offline: true,
        timestamp: new Date().toISOString(),
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
 */
async function handleDocumentRequest(request) {
  const url = new URL(request.url);

  // Routes critiques (données sensibles) à ne JAMAIS mettre en cache
  const NO_CACHE_ROUTES = [
      '/dashboard/',
      '/payments/',
      '/contracts/',
      '/accounts/profile/'
  ];

  const isCritical = NO_CACHE_ROUTES.some(route => url.pathname.startsWith(route));

  try {
    // 1. Toujours tenter le réseau en premier
    const networkResponse = await fetchWithTimeout(request);

    if (networkResponse && networkResponse.ok) {
       // 2. Ne met en cache que si ce N'EST PAS une route critique
       if (!isCritical) {
           const cache = await caches.open(DYNAMIC_CACHE);
           cache.put(request, networkResponse.clone());
       }
       return networkResponse;
    }
    // 3. Si le réseau répond mais pas "ok" (ex: 404), on retourne l'erreur
    return networkResponse;

  } catch (error) {
    // 4. Le réseau a échoué (offline)
    console.log('Document hors-ligne:', request.url);

    // 5. Essayer le cache SEULEMENT si ce n'est pas critique
    if (!isCritical) {
        const cachedResponse = await caches.match(request);
        if (cachedResponse) return cachedResponse;
    }

    // 6. Fallback final : page hors-ligne
    // CORRECTION : Nous utilisons le chemin racine
    const offlinePage = await caches.match('/offline.html');
    if (offlinePage) return offlinePage;

    // 7. Dernier recours
    return new Response(
      '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Hors ligne</title></head><body><h1>Service indisponible</h1><p>Veuillez vérifier votre connexion Internet.</p></body></html>',
      {
        status: 503,
        headers: { 'Content-Type': 'text/html' },
      }
    );
  }
} // <-- Fin de handleDocumentRequest

/**
 * Cache First - Pour les ressources statiques (CSS, JS) (STATIC_CACHE)
 */
async function handleStaticRequest(request) {
  try {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    const networkResponse = await fetchWithTimeout(request);
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
// GESTION DES MESSAGES
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

  // Les autres fonctions (GET_CACHE_SIZE, etc.) sont supprimées pour la clarté
});

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

console.log(`🎯 Service Worker BWHITE DIGITAL v${VERSION} initialisé`);