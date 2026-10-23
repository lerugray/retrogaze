/* OSS free build: missing SaaS DOM must not crash the generator. */
(function () {
  var _ge = document.getElementById.bind(document);
  document.getElementById = function (id) {
    var el = _ge(id);
    if (el) return el;
    var noop = function () {};
    var stubEl = {
      __rgStub: true,
      nodeType: 0,
      addEventListener: noop,
      removeEventListener: noop,
      classList: { add: noop, remove: noop, contains: function () { return false; }, toggle: function () { return false; } },
      style: {},
      value: '',
      textContent: '',
      innerHTML: '',
      checked: false,
      disabled: false,
      hidden: true,
      focus: noop,
      blur: noop,
      click: noop,
      reset: noop,
      appendChild: function (c) { return c; },
      removeChild: function (c) { return c; },
      insertBefore: function (c) { return c; },
      setAttribute: noop,
      getAttribute: function () { return null; },
      removeAttribute: noop,
      closest: function () { return null; },
      querySelector: function () { return null; },
      querySelectorAll: function () { return []; },
      parentNode: { insertBefore: function (c) { return c; }, removeChild: function (c) { return c; } },
      firstChild: null,
      dataset: {},
      files: [],
      length: 0,
      id: id,
      className: '',
      type: '',
      name: '',
      href: '',
      src: ''
    };
    return stubEl;
  };
})();

/* ============================================================
   Retrogaze: Frontend Application
   ============================================================ */

var API_BASE = window.location.origin;

function legacyShareCodeForUser(userId) {
  var api = window.RetrogazeLegacyShares;
  return api && api.codeForUser ? api.codeForUser(userId) : null;
}

function getStoredLegacyShare(userId) {
  var api = window.RetrogazeLegacyShares;
  return api && api.getStored ? api.getStored(userId) : null;
}

var _legacyShareCapturePromise = window.retrogazeLegacyShareCapture || Promise.resolve();

/* ============================================================
   Telemetry: lightweight event tracking
   ============================================================ */
var _telemetrySessionId = sessionStorage.getItem('rg_session_id');
if (!_telemetrySessionId) {
  _telemetrySessionId = crypto.randomUUID ? crypto.randomUUID() : (Math.random().toString(36).slice(2) + Date.now().toString(36));
  sessionStorage.setItem('rg_session_id', _telemetrySessionId);
}

var _deviceInfo = {
  user_agent: navigator.userAgent.slice(0, 200),
  viewport_width: window.innerWidth,
  is_mobile: window.innerWidth < 768,
};

function trackEvent(eventType, metadata) {
  var payload = {
    session_id: _telemetrySessionId,
    event_type: eventType,
    metadata: Object.assign({}, _deviceInfo, metadata || {}),
  };
  // Fire-and-forget: don't block UI
  fetch(API_BASE + '/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(function() { /* swallow errors: telemetry is non-critical */ });
}

// Conversion-funnel event (client-observed subset: usage_meter_90_shown,
// openSource_click). Requires session auth: the /funnel-events endpoint rejects
// anon: so this no-ops when not logged in. Fire-and-forget.
function trackFunnel(eventType, metadata) {
  if (!isLoggedIn()) return;
  fetch(API_BASE + '/funnel-events', {
    method: 'POST',
    headers: Object.assign(
      { 'Content-Type': 'application/json' },
      getAuthHeaders()
    ),
    body: JSON.stringify({ event_type: eventType, metadata: metadata || {} }),
  }).catch(function() { /* swallow: funnel telemetry is non-critical */ });
}
// Guard so the >=90% meter nudge only reports once per page-session (the usage
// meter re-renders on every /usage poll + after each generation).
var _funnelMeter90Fired = { daily: false, monthly: false };

// Session start event
trackEvent('session_start', { referrer: document.referrer || '' });

// Session heartbeat (every 60s while tab is visible)
var _heartbeatInterval = null;
function startHeartbeat() {
  if (_heartbeatInterval) return;
  _heartbeatInterval = setInterval(function() {
    if (!document.hidden) {
      trackEvent('session_heartbeat');
    }
  }, 60000);
}
startHeartbeat();
document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    clearInterval(_heartbeatInterval);
    _heartbeatInterval = null;
  } else {
    startHeartbeat();
  }
});

/* ============================================================
   Supabase Client
   ============================================================ */

// These will be populated from the backend /config endpoint or env
var SUPABASE_URL = '';
var SUPABASE_ANON_KEY = '';
var OAUTH_PROVIDERS = [];
var supabaseClient = null;
var currentUser = null;
var currentSession = null;

// Supabase init lifecycle: used to surface distinct auth-block reasons (rg-016)
var _supabaseInitPromise = null;
var _supabaseInitSettled = false;
var _supabaseInitUserFacingError = null;

var _CDN_WAIT_MS = 8000;
var _CDN_POLL_MS = 100;

function _waitForGlobalSupabase() {
  return new Promise(function(resolve) {
    var deadline = Date.now() + _CDN_WAIT_MS;
    function tick() {
      if (typeof window.supabase !== 'undefined') {
        resolve(true);
        return;
      }
      if (Date.now() >= deadline) {
        resolve(false);
        return;
      }
      setTimeout(tick, _CDN_POLL_MS);
    }
    tick();
  });
}

async function getSupabaseAuthUnavailableMessage() {
  if (_supabaseInitPromise && !_supabaseInitSettled) {
    trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'auth_blocked_still_loading' });
    return 'still loading, try again in a moment';
  }
  await initSupabase();
  if (supabaseClient) return null;
  if (_supabaseInitUserFacingError) return _supabaseInitUserFacingError;
  // No client after init, but no mapped failure (e.g. server returned empty Supabase keys).
  trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'auth_no_client_no_recorded_error' });
  return 'Supabase rejected credentials';
}

function initSupabase() {
  if (_supabaseInitPromise) return _supabaseInitPromise;

  _supabaseInitSettled = false;
  _supabaseInitUserFacingError = null;

  var work = (async function() {
    var resp = null;
    try {
      resp = await fetch(API_BASE + '/config');
    } catch (fetchErr) {
      _supabaseInitUserFacingError = '/config endpoint returned 0';
      trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'config_fetch_threw' });
      return;
    }

    if (!resp.ok) {
      _supabaseInitUserFacingError = '/config endpoint returned ' + resp.status;
      trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'config_non_2xx', http_status: resp.status });
      return;
    }

    try {
      var config = await resp.json();
      SUPABASE_URL = config.supabase_url || '';
      SUPABASE_ANON_KEY = config.supabase_anon_key || '';
      OAUTH_PROVIDERS = config.oauth_providers || [];
    } catch (parseErr) {
      _supabaseInitUserFacingError = '/config endpoint returned 0';
      trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'config_json_parse_failed' });
      return;
    }

    var cdnReady = await _waitForGlobalSupabase();
    if (!cdnReady) {
      _supabaseInitUserFacingError =
        'Supabase client library (CDN) did not load. Try disabling content blockers for cdn.jsdelivr.net';
      trackEvent('TODO_TELEMETRY_EVENT_NAME', { supabase_init_branch: 'cdn_global_missing' });
      return;
    }

    if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
      return;
    }

    try {
      supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

      supabaseClient.auth.onAuthStateChange(function(event, session) {
        currentSession = session;
        currentUser = session ? session.user : null;
        updateAuthUI();
        if (event === 'PASSWORD_RECOVERY') {
          document.getElementById('auth-modal').classList.add('open');
          showAuthPanel('reset');
          var pwEl = document.getElementById('reset-password');
          if (pwEl) pwEl.focus();
        }
        if (event === 'SIGNED_IN') {
          checkConsentBackfill();
        }
      });

      var sessionResult = await supabaseClient.auth.getSession();
      if (sessionResult.error) {
        throw sessionResult.error;
      }
      var data = sessionResult.data;
      if (data && data.session) {
        currentSession = data.session;
        currentUser = data.session.user;
        // Page load with an already-restored session (doesn't fire SIGNED_IN).
        checkConsentBackfill();
      }
      updateAuthUI();
      updateOAuthButtons();
    } catch (authInitErr) {
      supabaseClient = null;
      _supabaseInitUserFacingError = 'Supabase rejected credentials';
      trackEvent('TODO_TELEMETRY_EVENT_NAME', {
        supabase_init_branch: 'client_or_session_failed',
        detail: (authInitErr && authInitErr.message) ? String(authInitErr.message).slice(0, 200) : '',
      });
    }
  })();

  _supabaseInitPromise = work.finally(function() {
    _supabaseInitSettled = true;
  });

  return _supabaseInitPromise;
}

function getAuthHeaders() {
  if (!currentSession) return {};
  return { 'Authorization': 'Bearer ' + currentSession.access_token };
}

function isLoggedIn() {
  return currentUser !== null && !currentUser.is_anonymous;
}

/* ============================================================
   OAuth Social AuthGate (Google, GitHub)
   ============================================================ */

function updateOAuthButtons() {
  var show = OAUTH_PROVIDERS.length > 0 && supabaseClient;
  var groups = ['authGate-oauth-buttons', 'joinGate-oauth-buttons'];
  groups.forEach(function(id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.style.display = show ? '' : 'none';
    if (!show) return;
    // Only show buttons for providers in OAUTH_PROVIDERS
    el.querySelectorAll('.oauth-btn').forEach(function(btn) {
      var provider = btn.getAttribute('data-provider');
      btn.style.display = OAUTH_PROVIDERS.indexOf(provider) !== -1 ? '' : 'none';
    });
  });
}

async function signInWithOAuth(provider) {
  // Redirect-based OAuth: the browser navigates to the provider, then
  // back here with a session that onAuthStateChange picks up.
  await _legacyShareCapturePromise;
  supabaseClient.auth.signInWithOAuth({
    provider: provider,
    options: {
      redirectTo: window.location.origin,
      data: { legacyShare_code: getStoredLegacyShare() },
    },
  }).then(function(result) {
    if (result.error) {
      showToast(result.error.message || 'OAuth sign-in failed.', 'error');
    } else {
      trackEvent('oauth_authGate', { provider: provider });
    }
  }).catch(function(err) {
    showToast(err.message || 'OAuth sign-in failed.', 'error');
  });
}

// Wire up all OAuth buttons (authGate + joinGate panels share the same handler).
// On the joinGate panel, OAuth is itself a joinGate path: gate it on the same
// checkbox the email/password form requires, so "joinGate is impossible
// without agreeing" holds for every way to continue, not just the form.
document.querySelectorAll('.oauth-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var provider = this.getAttribute('data-provider');
    var isJoinGatePanel = !!this.closest('#joinGate-oauth-buttons');
    if (isJoinGatePanel) {
      var tosCheckbox = document.getElementById('joinGate-tos-agree');
      if (!tosCheckbox || !tosCheckbox.checked) {
        var errorEl = document.getElementById('joinGate-error');
        errorEl.textContent = 'You must agree to the Terms of Service and Privacy Policy to create an profile.';
        errorEl.classList.remove('hidden');
        return;
      }
    }
    signInWithOAuth(provider);
  });
});

/* ============================================================
   DOM Helper: clear all children safely
   ============================================================ */
function clearChildren(el) {
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/* ============================================================
   Focus Trap (for modals)
   ============================================================ */
function trapFocus(modalEl, closeCallback) {
  modalEl.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeCallback();
      return;
    }
    if (e.key !== 'Tab') return;

    var focusable = modalEl.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length === 0) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}

/* ============================================================
   Toast System
   ============================================================ */
function showToast(message, type) {
  type = type || 'info';
  var container = document.getElementById('toast-container');
  var toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(function() {
    toast.classList.add('removing');
    setTimeout(function() {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 200);
  }, 4000);
}

/* ============================================================
   Page Navigation
   ============================================================ */
var currentPage = 'generate';

function navigateTo(pageName) {
  // Hide all pages
  document.querySelectorAll('.page').forEach(function(el) {
    el.classList.remove('active');
  });
  // Show target page
  var target = document.getElementById('page-' + pageName);
  if (target) {
    target.classList.add('active');
  }

  // Update nav links
  document.querySelectorAll('.nav-link[data-page]').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-page') === pageName);
  });

  currentPage = pageName;

  // Update page title
  var pageTitles = { generate: 'Generate', history: 'History', settings: 'Settings', generate: 'Generate' };
  document.title = 'Retrogaze: ' + (pageTitles[pageName] || 'Classic Console Pixel Art Generator');

  // Track page view
  trackEvent('page_view', { page: pageName });

  // Load page data
  if (pageName === 'history') loadHistory();
  if (pageName === 'settings') loadSettings();
  /* legacyPlans page removed */
}

// Nav link clicks
document.querySelectorAll('[data-page]').forEach(function(el) {
  el.addEventListener('click', function(e) {
    e.preventDefault();
    navigateTo(this.getAttribute('data-page'));
    // Close mobile menu on navigation
    var menu = document.getElementById('topnav-links');
    var btn = document.getElementById('hamburger-btn');
    if (menu && btn) { menu.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
  });
});

// Hamburger menu toggle
(function() {
  var btn = document.getElementById('hamburger-btn');
  var menu = document.getElementById('topnav-links');
  if (btn && menu) {
    btn.addEventListener('click', function() {
      var open = menu.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
})();

/* ============================================================
   Auth UI
   ============================================================ */
function updateAuthUI() {
  var authBtn = document.getElementById('btn-open-auth');
  var userInfo = document.getElementById('nav-user-info');
  var userEmail = document.getElementById('nav-user-email');
  var historyAuthPrompt = document.getElementById('history-auth-prompt');
  var historyEmpty = document.getElementById('history-empty');
  var settingsAuthPrompt = document.getElementById('settings-auth-prompt');
  var settingsContent = document.getElementById('settings-content');

  if (isLoggedIn()) {
    authBtn.classList.add('hidden');
    userInfo.classList.remove('hidden');
    userEmail.textContent = currentUser.email || 'User';

    // History page: show content, hide auth prompt
    if (historyAuthPrompt) historyAuthPrompt.classList.add('hidden');

    // Settings page: show content, hide auth prompt
    if (settingsAuthPrompt) settingsAuthPrompt.classList.add('hidden');
    if (settingsContent) settingsContent.classList.remove('hidden');
  } else {
    authBtn.classList.remove('hidden');
    userInfo.classList.add('hidden');

    // History page: show auth prompt
    if (historyAuthPrompt) historyAuthPrompt.classList.remove('hidden');
    if (historyEmpty) historyEmpty.classList.add('hidden');

    // Settings page: show auth prompt, hide content
    if (settingsAuthPrompt) settingsAuthPrompt.classList.remove('hidden');
    if (settingsContent) settingsContent.classList.add('hidden');
  }
}

// Open auth modal
document.getElementById('btn-open-auth').addEventListener('click', function() {
  openAuthModal();
});

// Also wire up the authGate buttons on history/settings pages
document.getElementById('btn-history-authGate').addEventListener('click', function() {
  openAuthModal();
});
document.getElementById('btn-settings-authGate').addEventListener('click', function() {
  openAuthModal();
});

function openAuthModal() {
  document.getElementById('auth-modal').classList.add('open');
  document.getElementById('authGate-email').focus();
}

function closeAuthModal() {
  document.getElementById('auth-modal').classList.remove('open');
  // Clear form errors
  document.getElementById('authGate-error').classList.add('hidden');
  document.getElementById('joinGate-error').classList.add('hidden');
  var forgotErr = document.getElementById('forgot-error');
  if (forgotErr) forgotErr.classList.add('hidden');
  var forgotOk = document.getElementById('forgot-success');
  if (forgotOk) { forgotOk.classList.add('hidden'); forgotOk.textContent = ''; }
  var resetErr = document.getElementById('reset-error');
  if (resetErr) resetErr.classList.add('hidden');
  // Reset to authGate panel so the next open is predictable
  showAuthPanel('authGate');
}

// Shared panel switcher: works for tab-btn-driven (authGate/joinGate) and
// link-driven (forgot/reset) transitions. The tab-btns are kept
// ARIA-synced; panels without a tab-btn (forgot/reset) just show.
function showAuthPanel(name) {
  document.querySelectorAll('.tab-panel').forEach(function(p) {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    var isActive = b.getAttribute('data-tab') === name;
    b.classList.toggle('active', isActive);
    b.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });
}

document.getElementById('btn-close-auth').addEventListener('click', closeAuthModal);
document.getElementById('auth-modal').addEventListener('click', function(e) {
  if (e.target === this) closeAuthModal();
});

// Focus trap for auth modal
trapFocus(document.getElementById('auth-modal'), closeAuthModal);

// Tab switching (with ARIA)
document.querySelectorAll('.tab-btn[data-tab]').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var tabName = this.getAttribute('data-tab');
    document.querySelectorAll('.tab-btn').forEach(function(b) {
      var isActive = b.getAttribute('data-tab') === tabName;
      b.classList.toggle('active', isActive);
      b.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(function(p) {
      p.classList.toggle('active', p.id === 'tab-' + tabName);
    });
  });
});

// AuthGate form
document.getElementById('authGate-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('authGate-error');
  errorEl.classList.add('hidden');

  var email = document.getElementById('authGate-email').value.trim();
  var password = document.getElementById('authGate-password').value;

  if (!email || !password) {
    errorEl.textContent = 'Email and password are required.';
    errorEl.classList.remove('hidden');
    return;
  }

  var authBlock = await getSupabaseAuthUnavailableMessage();
  if (authBlock) {
    errorEl.textContent = authBlock;
    errorEl.classList.remove('hidden');
    return;
  }

  var submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'LOGGING IN...';

  try {
    var { data, error } = await supabaseClient.auth.signInWithPassword({
      email: email,
      password: password,
    });
    if (error) throw error;
    closeAuthModal();
    trackEvent('authGate');
    showToast('Logged in as ' + email, 'success');
  } catch (err) {
    errorEl.textContent = err.message || 'AuthGate failed.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'CONTINUE';
  }
});

// JoinGate form
document.getElementById('joinGate-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('joinGate-error');
  errorEl.classList.add('hidden');

  var email = document.getElementById('joinGate-email').value.trim();
  var password = document.getElementById('joinGate-password').value;
  var confirm = document.getElementById('joinGate-password-confirm').value;
  var tosCheckbox = document.getElementById('joinGate-tos-agree');

  if (!email || !password) {
    errorEl.textContent = 'Email and password are required.';
    errorEl.classList.remove('hidden');
    return;
  }
  if (password.length < 6) {
    errorEl.textContent = 'Password must be at least 6 characters.';
    errorEl.classList.remove('hidden');
    return;
  }
  if (password !== confirm) {
    errorEl.textContent = 'Passwords do not match.';
    errorEl.classList.remove('hidden');
    return;
  }
  // JoinGate must be impossible without agreeing to the Terms/Privacy Policy.
  if (!tosCheckbox || !tosCheckbox.checked) {
    errorEl.textContent = 'You must agree to the Terms of Service and Privacy Policy to create an profile.';
    errorEl.classList.remove('hidden');
    return;
  }

  var authBlock = await getSupabaseAuthUnavailableMessage();
  if (authBlock) {
    errorEl.textContent = authBlock;
    errorEl.classList.remove('hidden');
    return;
  }

  var submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'SIGNING UP...';

  try {
    await _legacyShareCapturePromise;
    var { data, error } = await supabaseClient.auth.joinGate({
      email: email,
      password: password,
      options: { data: { legacyShare_code: getStoredLegacyShare() } },
    });
    if (error) throw error;

    if (data.user && !data.session) {
      // Email confirmation required: no session yet, so consent can't be
      // recorded via the authenticated /consent/accept endpoint until they
      // confirm and continue. checkConsentBackfill() catches it at that point.
      closeAuthModal();
      showToast('Check your email to confirm your profile.', 'info');
    } else {
      closeAuthModal();
      trackEvent('joinGate');
      showToast('Profile created! Welcome to Retrogaze.', 'success');
      // They just explicitly checked the box: record it immediately so
      // they never see the backfill prompt (guard skips the SIGNED_IN-
      // triggered check that fires around the same time; see its comment).
      _skipNextConsentBackfillCheck = true;
      recordConsentAcceptance();
    }
  } catch (err) {
    errorEl.textContent = err.message || 'JoinGate failed.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'CONTINUE';
  }
});

/* ============================================================
   ToS/Privacy Consent: joinGate checkbox backfill for existing users
   ============================================================ */

// Guards against the backfill modal flashing open right after a fresh
// joinGate: supabase-js fires a SIGNED_IN auth event as part of joinGate()
// resolving, which triggers checkConsentBackfill() around the same time the
// joinGate handler is itself recording consent for the box the user just
// checked. Set right before that recording call; checkConsentBackfill()
// consumes it once so that one SIGNED_IN-triggered check is skipped.
var _skipNextConsentBackfillCheck = false;

// Best-effort: record that the current user accepted the current ToS
// version. Failures are non-fatal: checkConsentBackfill() is the safety
// net that re-prompts on the next authGate if this never landed.
async function recordConsentAcceptance() {
  if (!currentSession) return false;
  try {
    var resp = await fetch(API_BASE + '/consent/accept', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeaders()),
    });
    return resp.ok;
  } catch (e) {
    return false;
  }
}

// Checked after every sign-in (fresh authGate, joinGate-with-session, or a
// restored session on page load). Fails open: a network hiccup here must
// never lock a logged-in user out of the app.
async function checkConsentBackfill() {
  if (!isLoggedIn()) return;
  if (_skipNextConsentBackfillCheck) {
    _skipNextConsentBackfillCheck = false;
    return;
  }
  try {
    var resp = await fetch(API_BASE + '/consent', { headers: getAuthHeaders() });
    if (!resp.ok) return;
    var data = await resp.json();
    if (data.needs_acceptance) {
      openConsentModal();
    }
  } catch (e) { /* fail open */ }
}

function openConsentModal() {
  document.getElementById('consent-error').classList.add('hidden');
  document.getElementById('consent-tos-agree').checked = false;
  document.getElementById('consent-modal').classList.add('open');
}

function closeConsentModal() {
  document.getElementById('consent-modal').classList.remove('open');
}

// Blocking: no close button, no backdrop-dismiss. Tab still cycles inside
// the modal; Escape is a no-op here (unlike the dismissable auth modal).
trapFocus(document.getElementById('consent-modal'), function() {});

document.getElementById('consent-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('consent-error');
  errorEl.classList.add('hidden');

  var checkbox = document.getElementById('consent-tos-agree');
  if (!checkbox.checked) {
    errorEl.textContent = 'You must agree to the Terms of Service and Privacy Policy to continue.';
    errorEl.classList.remove('hidden');
    return;
  }

  var submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'SAVING...';

  var ok = await recordConsentAcceptance();

  submitBtn.disabled = false;
  submitBtn.textContent = 'I AGREE & CONTINUE';

  if (ok) {
    closeConsentModal();
  } else {
    errorEl.textContent = 'Could not save your response. Please try again.';
    errorEl.classList.remove('hidden');
  }
});

// Forgot Password: link click switches the modal to the forgot panel
document.getElementById('link-forgot-password').addEventListener('click', function(e) {
  e.preventDefault();
  // Pre-fill the email if the user already typed it into the authGate form
  var authGateEmail = document.getElementById('authGate-email').value.trim();
  if (authGateEmail) document.getElementById('forgot-email').value = authGateEmail;
  document.getElementById('authGate-error').classList.add('hidden');
  document.getElementById('forgot-error').classList.add('hidden');
  document.getElementById('forgot-success').classList.add('hidden');
  showAuthPanel('forgot');
  document.getElementById('forgot-email').focus();
});

document.getElementById('link-back-to-authGate').addEventListener('click', function(e) {
  e.preventDefault();
  document.getElementById('forgot-error').classList.add('hidden');
  showAuthPanel('authGate');
  document.getElementById('authGate-email').focus();
});

// Forgot-password form: request a reset email
document.getElementById('forgot-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('forgot-error');
  var successEl = document.getElementById('forgot-success');
  errorEl.classList.add('hidden');
  successEl.classList.add('hidden');

  var email = document.getElementById('forgot-email').value.trim();
  if (!email) {
    errorEl.textContent = 'Email is required.';
    errorEl.classList.remove('hidden');
    return;
  }

  var authBlock = await getSupabaseAuthUnavailableMessage();
  if (authBlock) {
    errorEl.textContent = authBlock;
    errorEl.classList.remove('hidden');
    return;
  }

  var submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'SENDING...';

  try {
    var { error } = await supabaseClient.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin + '/app',
    });
    if (error) throw error;
    // Don't leak whether the email exists: same success message either way.
    successEl.textContent = 'If an profile exists for ' + email + ', a reset link is on its way. Check your inbox (and spam).';
    successEl.classList.remove('hidden');
    trackEvent('password_reset_requested');
  } catch (err) {
    errorEl.textContent = err.message || 'Could not send reset email.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'SEND RESET LINK';
  }
});

// Reset-password form: user arrived via a recovery link with an
// active recovery session; this sets the new password via updateUser.
document.getElementById('reset-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('reset-error');
  errorEl.classList.add('hidden');

  var pw = document.getElementById('reset-password').value;
  var confirm = document.getElementById('reset-password-confirm').value;

  if (!pw || pw.length < 6) {
    errorEl.textContent = 'Password must be at least 6 characters.';
    errorEl.classList.remove('hidden');
    return;
  }
  if (pw !== confirm) {
    errorEl.textContent = 'Passwords do not match.';
    errorEl.classList.remove('hidden');
    return;
  }
  var authBlock = await getSupabaseAuthUnavailableMessage();
  if (authBlock) {
    errorEl.textContent = authBlock;
    errorEl.classList.remove('hidden');
    return;
  }

  var submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'SAVING...';

  try {
    var { error } = await supabaseClient.auth.updateUser({ password: pw });
    if (error) throw error;
    closeAuthModal();
    trackEvent('password_reset_completed');
    showToast('Password updated. You are now logged in.', 'success');
    // Clean the recovery hash out of the URL so a refresh doesn't
    // re-open the reset panel.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  } catch (err) {
    errorEl.textContent = err.message || 'Could not set new password.';
    errorEl.classList.remove('hidden');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'SET NEW PASSWORD';
  }
});

// Logout
document.getElementById('btn-logout').addEventListener('click', async function() {
  if (supabaseClient) {
    await supabaseClient.auth.signOut();
  }
  currentUser = null;
  currentSession = null;
  updateAuthUI();
  showToast('Logged out.', 'info');
  navigateTo('generate');
});

/* ============================================================
   State element references (generation page)
   ============================================================ */
var states = {
  form:    document.getElementById('state-form'),
  loading: document.getElementById('state-loading'),
  result:  document.getElementById('state-result'),
  error:   document.getElementById('state-error'),
};

function showState(name) {
  Object.entries(states).forEach(function(entry) {
    var key = entry[0];
    var el  = entry[1];
    if (key === name) {
      el.classList.remove('hidden');
      el.classList.add('active');
    } else {
      el.classList.add('hidden');
      el.classList.remove('active');
    }
  });

  // Announce state changes to screen readers
  var statusEl = document.getElementById('generation-status');
  if (statusEl) {
    var messages = {
      loading: 'Generating sprite, please wait...',
      result:  'Sprite generated successfully.',
      error:   'Generation failed.',
    };
    statusEl.textContent = messages[name] || '';
  }
}

/* ============================================================
   Reference image upload handling
   ============================================================ */
var refInput      = document.getElementById('reference-image');
var refPreview    = document.getElementById('reference-preview');
var clearRefBtn   = document.getElementById('btn-clear-reference');
var strengthGroup = document.getElementById('strength-group');
var strengthSlider = document.getElementById('reference-strength');
var strengthLabel = document.getElementById('strength-label');

var currentRefBase64 = null;

refInput.addEventListener('change', function(e) {
  var file = e.target.files[0];
  if (!file) return;

  var reader = new FileReader();
  reader.onload = function(evt) {
    currentRefBase64 = evt.target.result.split(',')[1];
    refPreview.src = evt.target.result;
    refPreview.classList.remove('hidden');
    clearRefBtn.classList.remove('hidden');
    strengthGroup.style.display = '';
    trackEvent('reference_uploaded');
  };
  reader.readAsDataURL(file);
});

clearRefBtn.addEventListener('click', function() {
  currentRefBase64 = null;
  refInput.value = '';
  refPreview.src = '';
  refPreview.classList.add('hidden');
  clearRefBtn.classList.add('hidden');
  strengthGroup.style.display = 'none';
});

strengthSlider.addEventListener('input', function() {
  // Slider reads as user-facing "Reference Strength": high = strong adherence,
  // low = creative freedom. The FLUX img2img `strength` param is inverted
  // (0 = exact copy, 1 = ignore reference), so we flip the value at the API
  // boundary. Labels match the user-facing direction.
  var val = parseInt(strengthSlider.value);
  var label = val < 30 ? 'Heavy variation' : val < 70 ? 'Moderate variation' : 'Close to reference';
  strengthLabel.textContent = val + '%: ' + label;
});

/* ============================================================
   Palette lock
   ============================================================ */
var NES_COLORS = [
    "#626262", "#002C88", "#1B0076", "#3B0076", "#560044", "#5A0002", "#4F0800", "#351000",
    "#1A1802", "#002E00", "#003200", "#002A14", "#00234A", "#000000",
    "#ABABAB", "#0D56D0", "#4220D0", "#6A12C2", "#92088A", "#9A1032", "#913800", "#7A5400",
    "#536800", "#0E7800", "#007A00", "#007028", "#006486",
    "#FFFFFF", "#4CA0FE", "#7C78FE", "#A862FE", "#D85CFE", "#E47ABA", "#E09264", "#C8B216",
    "#A0CC00", "#6ADA02", "#46E438", "#3AD67E", "#3EC4D2", "#4E4E4E",
    "#B6D8FE", "#C8C4FE", "#DAB8FE", "#EEBAFE", "#F4C4E2", "#F0CEB2", "#E4DE94",
    "#D0E882", "#BCF07E", "#B0F29C", "#ACF0C2", "#B2ECEE", "#ACACAC"
];

var lockedColors = [];
var MAX_LOCKED = 6;

var gridEl = document.getElementById('nes-palette-grid');
gridEl.setAttribute('role', 'group');
gridEl.setAttribute('aria-label', 'NES palette colors: click to lock');
NES_COLORS.forEach(function(hex) {
    var swatch = document.createElement('div');
    swatch.className = 'palette-swatch';
    swatch.style.background = hex;
    swatch.title = hex;
    swatch.setAttribute('data-color', hex);
    swatch.setAttribute('role', 'checkbox');
    swatch.setAttribute('aria-checked', 'false');
    swatch.setAttribute('aria-label', hex);
    swatch.setAttribute('tabindex', '0');
    swatch.addEventListener('click', function() {
        togglePaletteColor(hex, swatch);
    });
    swatch.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            togglePaletteColor(hex, swatch);
        }
    });
    gridEl.appendChild(swatch);
});

function togglePaletteColor(hex, swatchEl) {
    var idx = lockedColors.indexOf(hex);
    if (idx >= 0) {
        lockedColors.splice(idx, 1);
        swatchEl.classList.remove('selected');
        swatchEl.setAttribute('aria-checked', 'false');
    } else if (lockedColors.length < MAX_LOCKED) {
        lockedColors.push(hex);
        swatchEl.classList.add('selected');
        swatchEl.setAttribute('aria-checked', 'true');
        trackEvent('palette_locked', { color_count: lockedColors.length });
    }
    updateLockedDisplay();
}

function updateLockedDisplay() {
    var label = document.getElementById('locked-label');
    var swatches = document.getElementById('locked-swatches');
    var clearBtn = document.getElementById('btn-clear-palette');

    clearChildren(swatches);

    if (lockedColors.length > 0) {
        label.classList.remove('hidden');
        clearBtn.classList.remove('hidden');
        lockedColors.forEach(function(hex) {
            var s = document.createElement('span');
            s.className = 'locked-color';
            s.style.background = hex;
            s.title = hex;
            swatches.appendChild(s);
        });
    } else {
        label.classList.add('hidden');
        clearBtn.classList.add('hidden');
    }
}

document.getElementById('btn-clear-palette').addEventListener('click', function() {
    lockedColors = [];
    document.querySelectorAll('.palette-swatch.selected').forEach(function(el) {
        el.classList.remove('selected');
    });
    updateLockedDisplay();
});

/* ============================================================
   Sprite sheet animation options show/hide
   ============================================================ */
var assetTypeSelect = document.getElementById('asset-type');
var animationOptions = document.getElementById('animation-options');

assetTypeSelect.addEventListener('change', function() {
  animationOptions.style.display = assetTypeSelect.value === 'spritesheet' ? '' : 'none';
});

// Console selector hint
var consoleHints = {
  'nes':        '54 fixed colors, 4 per tile, 8x8 grid',
  'snes':       '32,768 colors, 16 per tile, Mode 7',
  'genesis':    '512 colors (9-bit RGB), 16 per tile',
  'gb_dmg':     '4 shades of green, sculpt with light',
  'gbc':        '32,768 colors, 4 per tile, per-tile palette',
  'c64':        '16 fixed colors, 2 per 8x8 cell',
  'pc_engine':  '512 colors, 16 per tile, 16 palettes'
};
var consoleSelect = document.getElementById('console');
var consoleHint   = document.getElementById('console-hint');
if (consoleSelect && consoleHint) {
  consoleSelect.addEventListener('change', function() {
    consoleHint.textContent = consoleHints[consoleSelect.value] || '';
  });
}

// Background color toggle
var bgColorToggle = document.getElementById('bg-color-toggle');
var bgColorInput  = document.getElementById('background-color');
if (bgColorToggle && bgColorInput) {
  bgColorToggle.addEventListener('change', function() {
    bgColorInput.disabled = !bgColorToggle.checked;
  });
}

/* ============================================================
   Form submission
   ============================================================ */
var form      = document.getElementById('generate-form');
var formError = document.getElementById('form-error');

function buildPayload() {
  var description = form.description.value.trim();
  if (!description) return null;

  var payload = {
    description:   description,
    asset_type:    form.asset_type.value,
    size:          form.size.value,
    view:          form.view.value,
    palette_mood:  form.palette_mood.value,
    outline:       form.outline.value,
    era:           form.era.value,
    console:       form.console.value,
  };

  if (currentRefBase64) {
    payload.reference_image = currentRefBase64;
    // Invert: user slider "Reference Strength" 100% = strong adherence,
    // FLUX img2img `strength` 0.0 = exact copy. See generate.py:_generate_from_reference.
    payload.reference_strength = (100 - parseInt(form.reference_strength.value)) / 100;
  }

  var bgToggle = document.getElementById('bg-color-toggle');
  if (bgToggle && bgToggle.checked) {
    payload.background_color = document.getElementById('background-color').value;
  }

  var flipCheck = document.getElementById('flip-horizontal');
  if (flipCheck && flipCheck.checked) {
    payload.flip_horizontal = true;
  }

  var strictCheck = document.getElementById('strict-size');
  if (strictCheck && strictCheck.checked) {
    payload.strict_size = true;
  }

  var scaleVal = parseInt(document.getElementById('scale-factor').value, 10);
  if (scaleVal > 1) {
    payload.scale_factor = scaleVal;
  }

  var exportPalette = document.getElementById('export-palette').value;
  if (exportPalette) {
    payload.export_palette = exportPalette;
  }

  if (lockedColors.length > 0) {
    payload.palette_colors = lockedColors.slice();
  }

  if (payload.asset_type === 'spritesheet') {
    payload.frame_count = parseInt(form.frame_count.value);
    payload.animation_type = form.animation_type.value;
  }

  return payload;
}

function submitGeneration(payload) {
  var promptLines = [
    'Description: ' + payload.description,
    'Asset Type:   ' + payload.asset_type,
    'Size:         ' + payload.size,
    'View:         ' + payload.view,
    'Palette Mood: ' + payload.palette_mood,
    'Outline:      ' + payload.outline,
    'Era:          ' + payload.era,
  ];
  document.getElementById('loading-prompt-display').textContent = promptLines.join('\n');

  showState('loading');

  var headers = { 'Content-Type': 'application/json' };
  var authHeaders = getAuthHeaders();
  if (authHeaders.Authorization) {
    headers.Authorization = authHeaders.Authorization;
  }

  fetch(API_BASE + '/generate', {
    method:  'POST',
    headers: headers,
    body:    JSON.stringify(payload),
  })
  .then(function(response) {
    if (!response.ok) {
      return response.json().then(function(errData) {
        var msg = errData.detail || errData.error || ('Server error: ' + response.status);
        throw new Error(msg);
      }).catch(function(parseErr) {
        if (parseErr.message && parseErr.message !== '[object Object]') throw parseErr;
        throw new Error('Server error: ' + response.status + ' ' + response.statusText);
      });
    }
    return response.json();
  })
  .then(function(data) {
    renderResult(data, payload.size, payload.asset_type);
    // Update usage meter after successful generation
    if (isLoggedIn()) loadUsage();
  })
  .catch(function(err) {
    showError(err.message || 'An unexpected error occurred.');
  });
}

form.addEventListener('submit', function(e) {
  e.preventDefault();
  formError.classList.add('hidden');
  formError.textContent = '';

  var payload = buildPayload();
  if (!payload) {
    formError.textContent = 'Please enter a description before generating.';
    formError.classList.remove('hidden');
    return;
  }
  trackEvent('generation_start', { asset_type: payload.asset_type, era: payload.era, size: payload.size, has_reference: !!payload.reference_image, has_palette_lock: !!(payload.palette_colors && payload.palette_colors.length) });
  submitGeneration(payload);
});

// 4 Variations button: same payload with num_candidates=4
document.getElementById('btn-variations').addEventListener('click', function() {
  formError.classList.add('hidden');
  formError.textContent = '';

  var payload = buildPayload();
  if (!payload) {
    formError.textContent = 'Please enter a description before generating.';
    formError.classList.remove('hidden');
    return;
  }
  payload.num_candidates = 4;
  trackEvent('variations_requested', { asset_type: payload.asset_type });
  submitGeneration(payload);
});

/* ============================================================
   Render result
   ============================================================ */
function renderResult(data, sizeStr, assetType) {
  var image_base64 = data.image_base64;
  var metadata     = data.metadata;

  if (!image_base64) {
    showError('Response did not include image data.');
    return;
  }

  var dataURI = 'data:image/png;base64,' + image_base64;

  // Native image
  var nativeImg = document.getElementById('result-img-native');
  nativeImg.src = dataURI;
  nativeImg.style.imageRendering = 'pixelated';

  // Zoomed image
  var zoomedImg = document.getElementById('result-img-zoomed');
  zoomedImg.src = dataURI;

  // Parse dimensions
  var widthPx  = 16;
  var heightPx = 16;
  if (metadata && metadata.dimensions) {
    widthPx  = metadata.dimensions.width_px  || 16;
    heightPx = metadata.dimensions.height_px || 16;
  } else if (sizeStr) {
    var parts = sizeStr.split('x');
    if (parts.length === 2) {
      widthPx  = parseInt(parts[0], 10) || 16;
      heightPx = parseInt(parts[1], 10) || 16;
    }
  }

  var maxPreviewSize = 384;
  var zoom = Math.max(1, Math.floor(maxPreviewSize / Math.max(widthPx, heightPx)));
  zoomedImg.style.width  = (widthPx  * zoom) + 'px';
  zoomedImg.style.height = (heightPx * zoom) + 'px';
  nativeImg.style.width  = '';
  nativeImg.style.height = '';

  // Dimension label under zoomed preview. When the delivered dims differ
  // from the requested size (Image2Pixel chose a quality-tuned scale),
  // surface both so users see the gap and can opt into Strict size.
  var dimLabel = document.getElementById('result-dim-label');
  if (dimLabel) {
    var requestedW = null, requestedH = null;
    if (metadata && metadata.target_dimensions) {
      requestedW = metadata.target_dimensions.width_px;
      requestedH = metadata.target_dimensions.height_px;
    } else if (sizeStr) {
      var rparts = sizeStr.split('x');
      if (rparts.length === 2) {
        requestedW = parseInt(rparts[0], 10);
        requestedH = parseInt(rparts[1], 10);
      }
    }

    var dimText = 'Delivered ' + widthPx + '\u00d7' + heightPx + ' px';
    if (requestedW && requestedH && (requestedW !== widthPx || requestedH !== heightPx)) {
      dimText += ' \u00b7 requested ' + requestedW + '\u00d7' + requestedH;
    }
    dimLabel.textContent = dimText;
    dimLabel.classList.remove('hidden');
  }

  // Tile grid overlay: 8px tiles at zoom scale
  var overlay = document.getElementById('tile-overlay');
  overlay.style.backgroundSize = (8 * zoom) + 'px ' + (8 * zoom) + 'px';

  // Console badge
  var consoleName = (metadata && metadata.console_display_name) ? metadata.console_display_name : 'NES';
  var consoleBadge = document.getElementById('badge-console');
  if (consoleBadge) consoleBadge.textContent = consoleName + '-COMPLIANT';

  // Compliance badges
  var compliance = (metadata && metadata.compliance) ? metadata.compliance : {};
  setBadge('badge-palette', compliance.nes_palette_valid,      'PALETTE VALID',    'PALETTE FAIL');
  setBadge('badge-grid',    compliance.grid_aligned,           'GRID ALIGNED',     'GRID MISALIGNED');
  setBadge('badge-colors',  compliance.colors_per_tile_valid,  'COLORS/TILE OK',   'COLORS/TILE FAIL');
  setBadge('badge-attr',    compliance.attribute_table_valid,  'ATTR TABLE OK',    'ATTR TABLE FAIL');

  // Animation frames row (spritesheet type)
  var existingFramesRow = document.getElementById('frames-row');
  if (existingFramesRow) {
    existingFramesRow.parentNode.removeChild(existingFramesRow);
  }

  var framesB64 = data.frames_base64;
  if (framesB64 && framesB64.length > 0) {
    var framesRow = document.createElement('div');
    framesRow.id = 'frames-row';
    framesRow.className = 'frames-row';

    var directionLabels = ["Front", "Right", "Back", "Left"];

    framesB64.forEach(function(b64, idx) {
      var frameWrap = document.createElement('div');
      frameWrap.className = 'frame-wrap';

      var frameImg = document.createElement('img');
      frameImg.src = 'data:image/png;base64,' + b64;
      var label = (assetType === 'directional' && idx < directionLabels.length)
        ? directionLabels[idx]
        : 'Frame ' + (idx + 1);
      frameImg.alt = label;
      frameImg.style.imageRendering = 'pixelated';
      frameImg.style.width = '64px';
      frameImg.style.height = '64px';
      frameImg.style.objectFit = 'contain';

      var frameLabel = document.createElement('span');
      frameLabel.className = 'frame-label';
      frameLabel.textContent = label;

      var frameDlBtn = document.createElement('button');
      frameDlBtn.className = 'btn btn--ghost btn--small frame-dl-btn';
      frameDlBtn.textContent = '\u2913';
      frameDlBtn.title = 'Download ' + label;
      frameDlBtn.setAttribute('data-frame-idx', idx);

      frameWrap.appendChild(frameImg);
      frameWrap.appendChild(frameLabel);
      frameWrap.appendChild(frameDlBtn);
      framesRow.appendChild(frameWrap);
    });

    var complianceBadges = document.getElementById('compliance-badges');
    complianceBadges.parentNode.insertBefore(framesRow, complianceBadges.nextSibling);

    // Per-frame download handlers
    framesRow.querySelectorAll('[data-frame-idx]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var idx = parseInt(this.getAttribute('data-frame-idx'), 10);
        var d = window._retrogazeData;
        if (!d || !d.frames_base64 || !d.frames_base64[idx]) return;
        var blob = base64ToBlob(d.frames_base64[idx], 'image/png');
        var baseName = buildFilename(d.metadata, 'png').replace('.png', '');
        triggerDownload(blob, baseName + '_frame_' + (idx + 1) + '.png');
      });
    });
  }

  // Palette swatches
  var paletteRow = document.getElementById('palette-display');
  clearChildren(paletteRow);

  var hexColors = (metadata && metadata.palette && metadata.palette.hex)
    ? metadata.palette.hex
    : [];

  if (hexColors.length === 0) {
    paletteRow.style.display = 'none';
  } else {
    paletteRow.style.display = '';
    hexColors.forEach(function(hex) {
      var safeHex = /^#[0-9A-Fa-f]{3,8}$/.test(hex) ? hex : '#000000';

      var swatch   = document.createElement('div');
      swatch.className = 'swatch';

      var colorBox = document.createElement('span');
      colorBox.className = 'swatch-color';
      colorBox.style.background = safeHex;
      colorBox.title = safeHex.toUpperCase();

      var labelEl = document.createElement('span');
      labelEl.className = 'swatch-hex';
      labelEl.textContent = safeHex.toUpperCase();

      swatch.appendChild(colorBox);
      swatch.appendChild(labelEl);
      paletteRow.appendChild(swatch);
    });
  }

  // Metadata panel
  document.getElementById('metadata-display').textContent =
    JSON.stringify(metadata || {}, null, 2);

  // Flipped sprite display
  var existingFlippedRow = document.getElementById('flipped-row');
  if (existingFlippedRow) existingFlippedRow.parentNode.removeChild(existingFlippedRow);

  if (data.flipped_base64) {
    var flippedRow = document.createElement('div');
    flippedRow.id = 'flipped-row';
    flippedRow.className = 'flipped-row';

    var flippedLabel = document.createElement('span');
    flippedLabel.className = 'preview-label';
    flippedLabel.textContent = 'Flipped';

    var flippedImg = document.createElement('img');
    flippedImg.src = 'data:image/png;base64,' + data.flipped_base64;
    flippedImg.style.imageRendering = 'pixelated';
    flippedImg.style.width = (widthPx * zoom) + 'px';
    flippedImg.style.height = (heightPx * zoom) + 'px';
    flippedImg.alt = 'Flipped sprite';

    var flippedDlBtn = document.createElement('button');
    flippedDlBtn.className = 'btn btn--ghost btn--small';
    flippedDlBtn.textContent = 'Download Flipped';
    flippedDlBtn.addEventListener('click', function() {
      var blob = base64ToBlob(data.flipped_base64, 'image/png');
      var baseName = buildFilename(metadata, 'png').replace('.png', '');
      triggerDownload(blob, baseName + '_flipped.png');
    });

    flippedRow.appendChild(flippedLabel);
    flippedRow.appendChild(flippedImg);
    flippedRow.appendChild(flippedDlBtn);

    var actionRow = document.querySelector('.action-row');
    actionRow.parentNode.insertBefore(flippedRow, actionRow);
  }

  // Candidates grid (variations)
  var existingCandGrid = document.getElementById('candidates-grid');
  if (existingCandGrid) existingCandGrid.parentNode.removeChild(existingCandGrid);

  var candidatesB64 = data.candidates_base64;
  if (candidatesB64 && candidatesB64.length > 1) {
    var candGrid = document.createElement('div');
    candGrid.id = 'candidates-grid';
    candGrid.className = 'candidates-grid';

    var candTitle = document.createElement('span');
    candTitle.className = 'preview-label';
    candTitle.textContent = 'Variations (' + candidatesB64.length + ')';
    candGrid.appendChild(candTitle);

    var candRow = document.createElement('div');
    candRow.className = 'candidates-row';

    candidatesB64.forEach(function(b64, idx) {
      var candWrap = document.createElement('div');
      candWrap.className = 'candidate-wrap';
      // idx 0 is the primary on first render: mark it active so the
      // user sees which thumb maps to the main preview.
      if (idx === 0) candWrap.classList.add('is-active');
      candWrap.setAttribute('data-cand-wrap-idx', idx);
      candWrap.setAttribute('role', 'button');
      candWrap.setAttribute('tabindex', '0');
      candWrap.setAttribute('aria-label', 'View variation ' + (idx + 1) + ' larger');

      var candImg = document.createElement('img');
      candImg.src = 'data:image/png;base64,' + b64;
      candImg.style.imageRendering = 'pixelated';
      var candZoom = Math.max(1, Math.floor(192 / Math.max(widthPx, heightPx)));
      candImg.style.width = (widthPx * candZoom) + 'px';
      candImg.style.height = (heightPx * candZoom) + 'px';
      candImg.alt = 'Variation ' + (idx + 1);

      var candLabel = document.createElement('span');
      candLabel.className = 'frame-label';
      candLabel.textContent = '#' + (idx + 1);

      var candDlBtn = document.createElement('button');
      candDlBtn.className = 'btn btn--ghost btn--small';
      candDlBtn.textContent = '\u2913';
      candDlBtn.title = 'Download variation ' + (idx + 1);
      candDlBtn.setAttribute('data-cand-idx', idx);

      // Bug 2 fix: clicking the wrap (anywhere except the download
      // button) opens the lightbox for this variation. Keyboard
      // Enter/Space mirrors the click. The lightbox provides the
      // "Make main" CTA that promotes this variation to the primary.
      var openForThisCand = function() {
        openLightbox({
          dataURI: 'data:image/png;base64,' + b64,
          widthPx: widthPx,
          heightPx: heightPx,
          candIdx: idx,
          totalCands: candidatesB64.length,
          isPrimary: false,
        });
      };
      candWrap.addEventListener('click', function(e) {
        if (e.target.closest('[data-cand-idx]')) return;  // download btn
        openForThisCand();
      });
      candWrap.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openForThisCand();
        }
      });

      candWrap.appendChild(candImg);
      candWrap.appendChild(candLabel);
      candWrap.appendChild(candDlBtn);
      candRow.appendChild(candWrap);
    });

    candGrid.appendChild(candRow);
    var actionRow = document.querySelector('.action-row');
    actionRow.parentNode.insertBefore(candGrid, actionRow);

    // Candidate download handlers
    candRow.querySelectorAll('[data-cand-idx]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var idx = parseInt(this.getAttribute('data-cand-idx'), 10);
        if (!candidatesB64[idx]) return;
        var blob = base64ToBlob(candidatesB64[idx], 'image/png');
        var baseName = buildFilename(metadata, 'png').replace('.png', '');
        triggerDownload(blob, baseName + '_var_' + (idx + 1) + '.png');
      });
    });
  }

  // Palette file download button
  var existingPalBtn = document.getElementById('btn-download-palette');
  if (existingPalBtn) existingPalBtn.parentNode.removeChild(existingPalBtn);

  if (data.palette_file_base64 && data.palette_file_format) {
    var palBtn = document.createElement('button');
    palBtn.id = 'btn-download-palette';
    palBtn.className = 'btn btn--secondary btn--small';
    palBtn.textContent = 'Download Palette (.' + data.palette_file_format + ')';
    palBtn.addEventListener('click', function() {
      var mimeType = data.palette_file_format === 'pal' ? 'application/octet-stream' : 'text/plain';
      var blob = base64ToBlob(data.palette_file_base64, mimeType);
      var baseName = buildFilename(metadata, 'png').replace('.png', '');
      triggerDownload(blob, baseName + '_palette.' + data.palette_file_format);
    });
    var actionRow = document.querySelector('.action-row');
    actionRow.appendChild(palBtn);
  }

  // Atlas JSON download button
  var existingAtlasBtn = document.getElementById('btn-download-atlas');
  if (existingAtlasBtn) existingAtlasBtn.parentNode.removeChild(existingAtlasBtn);

  if (data.atlas_json) {
    var atlasBtn = document.createElement('button');
    atlasBtn.id = 'btn-download-atlas';
    atlasBtn.className = 'btn btn--secondary btn--small';
    atlasBtn.textContent = 'Download Atlas (.json)';
    atlasBtn.addEventListener('click', function() {
      var blob = new Blob(
        [JSON.stringify(data.atlas_json, null, 2)],
        { type: 'application/json' }
      );
      var baseName = buildFilename(metadata, 'png').replace('.png', '');
      triggerDownload(blob, baseName + '_atlas.json');
    });
    var actionRow = document.querySelector('.action-row');
    actionRow.appendChild(atlasBtn);
  }

  // Store for download
  window._retrogazeData = { image_base64: image_base64, metadata: metadata, sizeStr: sizeStr, frames_base64: framesB64 || [] };

  trackEvent('generation_success', { asset_type: metadata && metadata.asset_type ? metadata.asset_type : '' });
  showState('result');
}

/* ============================================================
   Badge helper
   ============================================================ */
function setBadge(id, passing, passLabel, failLabel) {
  var el = document.getElementById(id);
  el.style.opacity = '';
  el.classList.remove('fail', 'unknown');
  if (passing === true) {
    el.textContent = passLabel;
  } else if (passing === false) {
    el.textContent = failLabel;
    el.classList.add('fail');
  } else {
    el.textContent = passLabel + ' (?)';
    el.classList.add('unknown');
    el.setAttribute('aria-label', passLabel + ' (unverified)');
  }
}

/* ============================================================
   Error state
   ============================================================ */
function isNonRetryableDemoNotice(message) {
  var m = String(message || '');
  return (
    m.indexOf('Image generation is not available on this server right now') !== -1 ||
    m.indexOf('The free demo credits are used up') !== -1
  );
}

function linkifyRepoUrls(text) {
  var REPO_RE = /(https:\/\/github\.com\/lerugray\/retrogaze)/g;
  var frag = document.createDocumentFragment();
  var last = 0;
  var match;
  while ((match = REPO_RE.exec(text)) !== null) {
    if (match.index > last) {
      frag.appendChild(document.createTextNode(text.slice(last, match.index)));
    }
    var a = document.createElement('a');
    a.href = match[1];
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = match[1];
    frag.appendChild(a);
    last = match.index + match[1].length;
  }
  if (last < text.length) {
    frag.appendChild(document.createTextNode(text.slice(last)));
  }
  return frag;
}

function showError(message) {
  trackEvent('generation_error', { error_message: (message || '').slice(0, 100) });
  var errorMsg = document.getElementById('error-message');
  var errorCard = document.querySelector('#state-error .error-card');
  var notice = isNonRetryableDemoNotice(message);

  clearChildren(errorMsg);
  if (notice) {
    errorMsg.appendChild(linkifyRepoUrls(String(message || '')));
    if (errorCard) errorCard.classList.add('error-card--notice');
  } else {
    errorMsg.textContent = message;
    if (errorCard) errorCard.classList.remove('error-card--notice');
  }

  // OpenSource / plans UI removed in the free open-source build.

  showState('error');
}

/* ============================================================
   Download helpers
   ============================================================ */
function base64ToBlob(base64, mimeType) {
  var byteChars = atob(base64);
  var byteNums  = new Uint8Array(byteChars.length);
  for (var i = 0; i < byteChars.length; i++) {
    byteNums[i] = byteChars.charCodeAt(i);
  }
  return new Blob([byteNums], { type: mimeType });
}

function triggerDownload(blob, filename) {
  var url = URL.createObjectURL(blob);
  var a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildFilename(metadata, ext) {
  var prompt = (metadata && metadata.prompt) ? metadata.prompt : 'sprite';
  var desc = prompt
    .replace(/[^a-z0-9]+/gi, '_')
    .replace(/^_|_$/, '')
    .toLowerCase()
    .slice(0, 40);
  return 'retrogaze_' + desc + '.' + ext;
}

document.getElementById('btn-download-png').addEventListener('click', function() {
  var d = window._retrogazeData;
  if (!d) return;
  trackEvent('download_png', { asset_type: d.metadata && d.metadata.asset_type ? d.metadata.asset_type : '' });
  var blob = base64ToBlob(d.image_base64, 'image/png');
  triggerDownload(blob, buildFilename(d.metadata, 'png'));
});

document.getElementById('btn-download-bundle').addEventListener('click', function() {
  var d = window._retrogazeData;
  if (!d) return;
  trackEvent('download_bundle', { asset_type: d.metadata && d.metadata.asset_type ? d.metadata.asset_type : '' });

  var pngBlob = base64ToBlob(d.image_base64, 'image/png');
  triggerDownload(pngBlob, buildFilename(d.metadata, 'png'));

  setTimeout(function() {
    var jsonBlob = new Blob(
      [JSON.stringify(d.metadata || {}, null, 2)],
      { type: 'application/json' }
    );
    triggerDownload(jsonBlob, buildFilename(d.metadata, 'json'));
  }, 200);
});

document.getElementById('btn-generate-another').addEventListener('click', function() {
  window._retrogazeData = null;
  ['badge-palette', 'badge-grid', 'badge-colors', 'badge-attr'].forEach(function(id) {
    document.getElementById(id).style.opacity = '';
  });
  document.getElementById('metadata-panel').removeAttribute('open');
  lockedColors = [];
  document.querySelectorAll('.palette-swatch.selected').forEach(function(el) {
    el.classList.remove('selected');
  });
  updateLockedDisplay();
  showState('form');
});

document.getElementById('btn-error-back').addEventListener('click', function() {
  showState('form');
});

/* ============================================================
   History Page
   ============================================================ */
var historyLimit = 20;
var historyTotal = 0;
var historyCursor = null;
var historyHasMore = false;
var historyLoading = false;

async function loadHistory() {
  if (!isLoggedIn()) {
    document.getElementById('history-auth-prompt').classList.remove('hidden');
    document.getElementById('history-empty').classList.add('hidden');
    clearChildren(document.getElementById('history-grid'));
    document.getElementById('usage-summary').classList.add('hidden');
    return;
  }

  document.getElementById('history-auth-prompt').classList.add('hidden');

  // Load usage stats
  loadUsage();

  // Reset cursor state for a fresh page load.
  historyCursor = null;
  historyHasMore = false;
  await fetchHistoryPage(false);
}

// Fetch one page of history. When `append` is true, uses the cursor from
// the previous page (keyset pagination); otherwise loads from the top.
// Guarded by historyLoading so concurrent scroll/click events don't
// double-fetch.
async function fetchHistoryPage(append) {
  if (historyLoading) return;
  if (append && !historyCursor) return;
  historyLoading = true;

  var loadMoreBtn = document.getElementById('btn-load-more');
  if (loadMoreBtn) loadMoreBtn.textContent = 'Loading\u2026';

  try {
    var headers = getAuthHeaders();
    headers['Content-Type'] = 'application/json';
    var url = API_BASE + '/history?limit=' + historyLimit;
    if (append && historyCursor) {
      url += '&cursor=' + encodeURIComponent(historyCursor);
    }
    var resp = await fetch(url, { headers: headers });
    if (!resp.ok) throw new Error('Failed to load history');
    var data = await resp.json();

    historyTotal = data.total;
    historyHasMore = !!data.has_more;
    historyCursor = data.next_cursor || null;

    var grid = document.getElementById('history-grid');
    var empty = document.getElementById('history-empty');
    var loadMore = document.getElementById('history-load-more');

    if (!append) {
      clearChildren(grid);
    }

    if (data.items.length === 0 && !append) {
      empty.classList.remove('hidden');
      grid.classList.add('hidden');
    } else {
      empty.classList.add('hidden');
      grid.classList.remove('hidden');
      data.items.forEach(function(item) {
        grid.appendChild(createHistoryCard(item));
      });
    }

    // Show/hide load more. With IntersectionObserver this sentinel is
    // also the infinite-scroll trigger; it stays visible while more rows
    // exist so scrolling to the bottom auto-fetches the next page.
    if (historyHasMore) {
      loadMore.classList.remove('hidden');
    } else {
      loadMore.classList.add('hidden');
    }
  } catch (err) {
    showToast('Failed to load history: ' + err.message, 'error');
  } finally {
    historyLoading = false;
    if (loadMoreBtn) loadMoreBtn.textContent = 'Load More';
  }
}

// Load the next page (called by both the Load More button and the
// IntersectionObserver). No-op when already loading or no more rows.
function loadHistoryNext() {
  if (historyLoading || !historyHasMore) return;
  fetchHistoryPage(true);
}

/* ============================================================
   Variation lightbox (Bug 2)
   ============================================================ */

// Open the lightbox for a given image. `opts` carries:
//   dataURI: image source (data: URI for variations, signed URL ok)
//   widthPx/heightPx: sprite dimensions for zoom math
//   candIdx: variation index (0-based, only for variations)
//   totalCands: total candidate count (omit for primary)
//   isPrimary: true when opened from #result-img-zoomed
// The "Make main" button is hidden when isPrimary=true.
function openLightbox(opts) {
  var backdrop = document.getElementById('variation-lightbox');
  if (!backdrop) return;
  var img = document.getElementById('lightbox-img');
  var caption = document.getElementById('lightbox-caption');
  var makeBtn = document.getElementById('lightbox-make-main');
  var dlBtn = document.getElementById('lightbox-download');

  // 4× the generate-screen preview, capped at the viewport.
  var maxSize = Math.min(window.innerWidth - 64, window.innerHeight - 200, 768);
  var zoom = Math.max(1, Math.floor(maxSize / Math.max(opts.widthPx, opts.heightPx)));
  img.src = opts.dataURI;
  img.style.imageRendering = 'pixelated';
  img.style.width = (opts.widthPx * zoom) + 'px';
  img.style.height = (opts.heightPx * zoom) + 'px';
  img.alt = opts.isPrimary
    ? 'Main sprite, enlarged'
    : 'Variation ' + (opts.candIdx + 1) + ', enlarged';

  if (opts.isPrimary) {
    caption.textContent = 'Main sprite: ' + opts.widthPx + '×' + opts.heightPx + ' px';
    makeBtn.classList.add('hidden');
  } else {
    caption.textContent = 'Variation ' + (opts.candIdx + 1) + ' of ' + opts.totalCands;
    makeBtn.classList.remove('hidden');
    makeBtn.onclick = function() {
      promoteVariationToMain(opts.candIdx, opts.dataURI);
      closeLightbox();
    };
  }
  dlBtn.onclick = function() {
    var d = window._retrogazeData;
    var meta = d ? d.metadata : null;
    var baseName = buildFilename(meta || {}, 'png').replace('.png', '');
    var b64 = opts.dataURI.split(',')[1] || '';
    var blob = base64ToBlob(b64, 'image/png');
    var suffix = opts.isPrimary ? '' : '_var_' + (opts.candIdx + 1);
    triggerDownload(blob, baseName + suffix + '.png');
  };

  backdrop.classList.add('open');
  // Focus the close button so Esc/Tab work naturally.
  var closeBtn = document.getElementById('lightbox-close');
  if (closeBtn) closeBtn.focus();
}

function closeLightbox() {
  var backdrop = document.getElementById('variation-lightbox');
  if (backdrop) backdrop.classList.remove('open');
}

// Swap the main preview to the chosen variation. Mutates
// window._retrogazeData.image_base64 so subsequent download/save
// flows operate on the promoted variation. Updates the active-state
// border on the thumb strip. Does NOT persist server-side: the
// server-side ordering belongs to whatever was the primary at
// generation time (Bug 1's persistence). This is purely a viewer
// preference for the current session.
function promoteVariationToMain(candIdx, dataURI) {
  var b64 = dataURI.split(',')[1] || '';
  var nativeImg = document.getElementById('result-img-native');
  var zoomedImg = document.getElementById('result-img-zoomed');
  if (nativeImg) nativeImg.src = dataURI;
  if (zoomedImg) zoomedImg.src = dataURI;

  // Update window._retrogazeData so the main download/save buttons
  // pick up the promoted bytes.
  if (window._retrogazeData) {
    window._retrogazeData.image_base64 = b64;
  }

  // Active-state on the thumb strip
  var wraps = document.querySelectorAll('[data-cand-wrap-idx]');
  wraps.forEach(function(w) {
    var i = parseInt(w.getAttribute('data-cand-wrap-idx'), 10);
    if (i === candIdx) {
      w.classList.add('is-active');
    } else {
      w.classList.remove('is-active');
    }
  });

  trackEvent('variation_promoted', { idx: candIdx });
}

// Wire close behavior (backdrop click + Esc + close button). Bound
// once on first call via a guarded init flag.
function initLightboxOnce() {
  if (window._lightboxInited) return;
  window._lightboxInited = true;
  var backdrop = document.getElementById('variation-lightbox');
  if (!backdrop) return;
  backdrop.addEventListener('click', function(e) {
    if (e.target === backdrop) closeLightbox();
  });
  var closeBtn = document.getElementById('lightbox-close');
  if (closeBtn) closeBtn.addEventListener('click', closeLightbox);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && backdrop.classList.contains('open')) {
      closeLightbox();
    }
  });
}
initLightboxOnce();

// Click the main preview's zoomed image to open it in the lightbox.
// Bound once at module load (the element exists in index.html).
(function bindMainPreviewLightbox() {
  var zoomedImg = document.getElementById('result-img-zoomed');
  if (!zoomedImg) return;
  zoomedImg.style.cursor = 'zoom-in';
  zoomedImg.setAttribute('role', 'button');
  zoomedImg.setAttribute('tabindex', '0');
  zoomedImg.setAttribute('aria-label', 'Enlarge main sprite');
  var openMain = function() {
    var d = window._retrogazeData;
    if (!d || !d.image_base64) return;
    var w = 16, h = 16;
    if (d.metadata && d.metadata.dimensions) {
      w = d.metadata.dimensions.width_px || 16;
      h = d.metadata.dimensions.height_px || 16;
    }
    openLightbox({
      dataURI: 'data:image/png;base64,' + d.image_base64,
      widthPx: w,
      heightPx: h,
      isPrimary: true,
    });
  };
  zoomedImg.addEventListener('click', openMain);
  zoomedImg.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openMain();
    }
  });
})();

function createHistoryCard(item) {
  var card = document.createElement('div');
  card.className = 'history-card';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', item.description + ', ' + item.asset_type + ', ' + item.size + ' (opens in new tab)');
  card.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      card.click();
    }
  });

  var imgWrap = document.createElement('div');
  imgWrap.className = 'history-card-img';

  // rg-018: use the short-lived signed URL the server computed in
  // /history. The `generations` bucket is private; getPublicUrl()
  // returned a 404 URL pattern that broke history thumbnails + clicks
  // for every tester since launch.
  if (item.image_url) {
    var img = document.createElement('img');
    img.src = item.image_url;
    img.alt = item.description;
    img.loading = 'lazy';
    imgWrap.appendChild(img);
    // Bug 1 fix: badge the total candidate count when this generation
    // produced more than one. Total = 1 (primary) + N variations.
    var nVar = (item.variation_image_urls || []).length;
    if (nVar > 0) {
      var badge = document.createElement('span');
      badge.className = 'history-card-badge';
      badge.textContent = (nVar + 1) + '\u00d7';  // e.g. "4\u00d7"
      badge.title = (nVar + 1) + ' variations';
      imgWrap.appendChild(badge);
    }
  }

  var desc = document.createElement('div');
  desc.className = 'history-card-desc';
  desc.textContent = item.description;
  desc.title = item.description;

  var meta = document.createElement('div');
  meta.className = 'history-card-meta';
  meta.textContent = item.asset_type + ' \u00b7 ' + item.size + ' \u00b7 ' + item.era;

  card.appendChild(imgWrap);

  // Bug 1 fix: mini-thumb strip for additional variations. Each thumb
  // is its own click target: opens that variation in a new tab,
  // matching the primary's window.open behavior. stopPropagation so
  // the card-level click doesn't also fire on the primary URL.
  if (item.variation_image_urls && item.variation_image_urls.length > 0) {
    var varStrip = document.createElement('div');
    varStrip.className = 'history-card-variations';
    varStrip.setAttribute('aria-label', item.variation_image_urls.length + ' more variations');
    item.variation_image_urls.forEach(function(url, i) {
      var thumb = document.createElement('img');
      thumb.src = url;
      thumb.alt = 'Variation ' + (i + 2);
      thumb.loading = 'lazy';
      thumb.title = 'Variation ' + (i + 2) + ' (open in new tab)';
      thumb.addEventListener('click', function(e) {
        e.stopPropagation();
        window.open(url, '_blank');
      });
      varStrip.appendChild(thumb);
    });
    card.appendChild(varStrip);
  }

  card.appendChild(desc);
  card.appendChild(meta);

  // Click to download: uses the same signed URL as the thumbnail
  // (rg-018). Falls back to a no-op if the server failed to sign
  // (file missing on storage, signing error). If the user keeps the
  // history page open past the 1-hour signed-URL expiry, the URL
  // will 404: refresh the page to re-fetch fresh signed URLs.
  card.addEventListener('click', function() {
    if (item.image_url) {
      window.open(item.image_url, '_blank');
    }
  });

  return card;
}

// Load more button: fallback for browsers without IntersectionObserver
// and an explicit trigger for keyboard/assistive-tech users.
document.getElementById('btn-load-more').addEventListener('click', function() {
  loadHistoryNext();
});

// Infinite scroll: observe the load-more sentinel and auto-fetch the
// next page when it scrolls near the viewport. 300px rootMargin preloads
// the next page just before the user reaches the bottom, so content
// appears without a visible pause. No-op when IntersectionObserver is
// unavailable: the Load More button above covers that case.
if ('IntersectionObserver' in window) {
  var historySentinel = document.getElementById('history-load-more');
  // Stubbed missing nodes are truthy; only observe real Elements.
  if (historySentinel && historySentinel instanceof Element && !historySentinel.__rgStub) {
    var historyScrollObserver = new IntersectionObserver(function(entries) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting && historyHasMore && !historyLoading) {
          loadHistoryNext();
        }
      }
    }, { rootMargin: '300px' });
    historyScrollObserver.observe(historySentinel);
  }
}

/* ============================================================
   Usage Stats
   ============================================================ */
async function loadUsage() {
  if (!isLoggedIn()) return;

  try {
    var resp = await fetch(API_BASE + '/usage', { headers: getAuthHeaders() });
    if (!resp.ok) return;
    var data = await resp.json();

    var usageSummary = document.getElementById('usage-summary');
    if (usageSummary) usageSummary.classList.remove('hidden');

    // Tier badge
    var tier = data.tier || 'free';
    var tierBadge = document.getElementById('usage-tier-badge');
    if (tierBadge) tierBadge.textContent = tier.toUpperCase();

    // Daily meter
    var dailyCount = data.daily_count || 0;
    var dailyLimit = data.daily_limit;
    var dailyText = dailyLimit ? ((dailyLimit - dailyCount) + ' remaining of ' + dailyLimit) : (dailyCount + ' today');
    var dailyCountEl = document.getElementById('meter-daily-count');
    if (dailyCountEl) dailyCountEl.textContent = dailyText;
    var dailyPct = 0;
    if (dailyLimit) {
      dailyPct = Math.min(100, (dailyCount / dailyLimit) * 100);
      var dailyFill = document.getElementById('meter-daily-fill');
      if (dailyFill) {
        dailyFill.style.width = dailyPct + '%';
        dailyFill.className = 'usage-meter-fill' +
          (dailyPct >= 90 ? ' danger' : dailyPct >= 70 ? ' warning' : '');
      }
      var dailyBar = document.getElementById('meter-daily-bar');
      if (dailyBar) dailyBar.setAttribute('aria-valuenow', Math.round(dailyPct));
    }
    var dailyOpenSource = document.getElementById('meter-daily-openSource');
    var dailyNudgeShown = !!(dailyLimit && dailyPct >= 90 && tier === 'free');
    if (dailyOpenSource) {
      dailyOpenSource.classList.toggle('hidden', !dailyNudgeShown);
    }
    if (dailyNudgeShown && !_funnelMeter90Fired.daily) {
      _funnelMeter90Fired.daily = true;
      trackFunnel('usage_meter_90_shown', { meter: 'daily', pct: Math.round(dailyPct) });
    }

    // Monthly meter
    var monthlyCount = data.monthly_count || 0;
    var monthlyLimit = data.monthly_limit;
    var monthlyText = monthlyLimit ? ((monthlyLimit - monthlyCount) + ' remaining of ' + monthlyLimit) : (monthlyCount + ' this month');
    var monthlyCountEl = document.getElementById('meter-monthly-count');
    if (monthlyCountEl) monthlyCountEl.textContent = monthlyText;
    var monthlyPct = 0;
    if (monthlyLimit) {
      monthlyPct = Math.min(100, (monthlyCount / monthlyLimit) * 100);
      var monthlyFill = document.getElementById('meter-monthly-fill');
      if (monthlyFill) {
        monthlyFill.style.width = monthlyPct + '%';
        monthlyFill.className = 'usage-meter-fill' +
          (monthlyPct >= 90 ? ' danger' : monthlyPct >= 70 ? ' warning' : '');
      }
      var monthlyBar = document.getElementById('meter-monthly-bar');
      if (monthlyBar) monthlyBar.setAttribute('aria-valuenow', Math.round(monthlyPct));
    }
    var monthlyOpenSource = document.getElementById('meter-monthly-openSource');
    var monthlyNudgeShown = !!(monthlyLimit && monthlyPct >= 90 && tier === 'free');
    if (monthlyOpenSource) {
      monthlyOpenSource.classList.toggle('hidden', !monthlyNudgeShown);
    }
    if (monthlyNudgeShown && !_funnelMeter90Fired.monthly) {
      _funnelMeter90Fired.monthly = true;
      trackFunnel('usage_meter_90_shown', { meter: 'monthly', pct: Math.round(monthlyPct) });
    }

    // Total
    var usageTotal = document.getElementById('usage-total');
    if (usageTotal) usageTotal.textContent = (data.total_count || 0) + ' total generations';

    // Show inline usage on generate page
    var inlineUsage = document.getElementById('usage-bar-inline');
    var inlineText = document.getElementById('usage-text-inline');
    if (inlineUsage && inlineText) {
      if (dailyLimit) {
        inlineUsage.classList.remove('hidden');
        inlineText.textContent = (dailyLimit - dailyCount) + ' daily generations remaining';
      } else if (monthlyLimit) {
        inlineUsage.classList.remove('hidden');
        inlineText.textContent = (monthlyLimit - monthlyCount) + ' monthly generations remaining';
      } else {
        inlineUsage.classList.add('hidden');
      }
    }

    // Show API key section for pro/studio
    var apiKeySection = document.getElementById('api-key-section');
    if (apiKeySection && (data.tier === 'pro' || data.tier === 'studio')) {
      apiKeySection.classList.remove('hidden');
      loadApiKeys();
    }
  } catch (err) {
    // Silently fail: usage display is non-critical
  }
}

/* ============================================================
   Settings Page
   ============================================================ */
async function loadSettings() {
  if (!isLoggedIn()) return;

  // Load subscription info for the settings page header
  loadSubscription();

  try {
    var resp = await fetch(API_BASE + '/settings', { headers: getAuthHeaders() });
    if (!resp.ok) return;
    var data = await resp.json();

    // Populate form fields
    setSelectValue('setting-era', data.default_era);
    setSelectValue('setting-palette-mood', data.default_palette_mood);
    setSelectValue('setting-outline', data.default_outline);
    setSelectValue('setting-asset-type', data.default_asset_type);
    setSelectValue('setting-size', data.default_size);
    setSelectValue('setting-view', data.default_view);

    // Load saved palettes
    savedPalettes = data.saved_palettes || [];
    renderSavedPalettes();
  } catch (err) {
    // Silently fail
  }

  // Render saved prompt templates
  renderSettingsTemplateList();

  // Also refresh usage
  loadUsage();
}


function setSelectValue(id, value) {
  var el = document.getElementById(id);
  if (el && value) {
    // Check if option exists
    var options = Array.from(el.options);
    var match = options.find(function(o) { return o.value === value; });
    if (match) el.value = value;
  }
}

// Settings form submit
document.getElementById('settings-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  if (!isLoggedIn()) return;

  var payload = {
    default_era: document.getElementById('setting-era').value,
    default_palette_mood: document.getElementById('setting-palette-mood').value,
    default_outline: document.getElementById('setting-outline').value,
    default_asset_type: document.getElementById('setting-asset-type').value,
    default_size: document.getElementById('setting-size').value,
    default_view: document.getElementById('setting-view').value,
  };

  try {
    var headers = getAuthHeaders();
    headers['Content-Type'] = 'application/json';
    var resp = await fetch(API_BASE + '/settings', {
      method: 'PUT',
      headers: headers,
      body: JSON.stringify(payload),
    });

    if (!resp.ok) throw new Error('Failed to save settings');

    // Apply defaults to the generation form
    applyDefaults(payload);

    showToast('Settings saved!', 'success');

    // Show the saved message
    var savedMsg = document.getElementById('settings-saved-msg');
    savedMsg.classList.remove('hidden');
    setTimeout(function() { savedMsg.classList.add('hidden'); }, 2000);
  } catch (err) {
    showToast('Failed to save: ' + err.message, 'error');
  }
});

function applyDefaults(settings) {
  if (settings.default_era) setSelectValue('era', settings.default_era);
  if (settings.default_palette_mood) setSelectValue('palette-mood', settings.default_palette_mood);
  if (settings.default_outline) {
    // Map setting values to form values
    var outlineMap = { 'Black': 'black', 'Dark': 'dark', 'No': 'none' };
    var formVal = outlineMap[settings.default_outline] || settings.default_outline.toLowerCase();
    setSelectValue('outline', formVal);
  }
  if (settings.default_asset_type) setSelectValue('asset-type', settings.default_asset_type);
  if (settings.default_size) setSelectValue('size', settings.default_size);
  if (settings.default_view) setSelectValue('view', settings.default_view);
}

/* ============================================================
   Saved Palettes
   ============================================================ */
var pickedColors = [];
var savedPalettes = [];
var MAX_PALETTE_COLORS = 6;

// Build the palette picker grid (smaller version for settings page)
var pickerGrid = document.getElementById('palette-picker-grid');
if (pickerGrid) {
  pickerGrid.setAttribute('role', 'group');
  pickerGrid.setAttribute('aria-label', 'NES palette colors: click to pick');
  NES_COLORS.forEach(function(hex) {
    var swatch = document.createElement('div');
    swatch.className = 'palette-swatch';
    swatch.style.background = hex;
    swatch.title = hex;
    swatch.setAttribute('role', 'checkbox');
    swatch.setAttribute('aria-checked', 'false');
    swatch.setAttribute('aria-label', hex);
    swatch.setAttribute('tabindex', '0');
    swatch.addEventListener('click', function() {
      togglePickedColor(hex, swatch);
    });
    swatch.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        togglePickedColor(hex, swatch);
      }
    });
    pickerGrid.appendChild(swatch);
  });
}

function togglePickedColor(hex, swatchEl) {
  var idx = pickedColors.indexOf(hex);
  if (idx >= 0) {
    pickedColors.splice(idx, 1);
    swatchEl.classList.remove('selected');
    swatchEl.setAttribute('aria-checked', 'false');
  } else if (pickedColors.length < MAX_PALETTE_COLORS) {
    pickedColors.push(hex);
    swatchEl.classList.add('selected');
    swatchEl.setAttribute('aria-checked', 'true');
  }
  renderPickedColors();
}

function renderPickedColors() {
  var container = document.getElementById('picked-colors');
  clearChildren(container);
  pickedColors.forEach(function(hex, idx) {
    var el = document.createElement('span');
    el.className = 'picked-color';
    el.style.background = hex;
    el.title = hex + ' (click to remove)';
    el.addEventListener('click', function() {
      pickedColors.splice(idx, 1);
      // Deselect in grid
      var gridSwatches = pickerGrid.querySelectorAll('.palette-swatch');
      gridSwatches.forEach(function(s) {
        if (s.style.backgroundColor === el.style.backgroundColor) {
          s.classList.remove('selected');
        }
      });
      renderPickedColors();
    });
    container.appendChild(el);
  });
}

// Save palette button
document.getElementById('btn-save-palette').addEventListener('click', async function() {
  var nameInput = document.getElementById('new-palette-name');
  var name = nameInput.value.trim();

  if (!name) {
    showToast('Enter a name for this palette.', 'warning');
    nameInput.focus();
    return;
  }
  if (pickedColors.length === 0) {
    showToast('Pick at least one color.', 'warning');
    return;
  }

  // Add to local list
  savedPalettes.push({ name: name, colors: pickedColors.slice() });

  // Save to backend
  await savePalettesToBackend();

  // Reset picker
  nameInput.value = '';
  pickedColors = [];
  pickerGrid.querySelectorAll('.palette-swatch.selected').forEach(function(s) {
    s.classList.remove('selected');
  });
  renderPickedColors();
  renderSavedPalettes();
  showToast('Palette "' + name + '" saved!', 'success');
});

async function savePalettesToBackend() {
  if (!isLoggedIn()) return;
  try {
    var headers = getAuthHeaders();
    headers['Content-Type'] = 'application/json';
    await fetch(API_BASE + '/settings', {
      method: 'PUT',
      headers: headers,
      body: JSON.stringify({ saved_palettes: savedPalettes }),
    });
  } catch (err) {
    showToast('Failed to save palettes.', 'error');
  }
}

function renderSavedPalettes() {
  var list = document.getElementById('saved-palette-list');
  var noMsg = document.getElementById('no-palettes-msg');
  clearChildren(list);

  if (savedPalettes.length === 0) {
    noMsg.classList.remove('hidden');
    return;
  }
  noMsg.classList.add('hidden');

  savedPalettes.forEach(function(palette, idx) {
    var item = document.createElement('div');
    item.className = 'saved-palette-item';

    // Color swatches
    var colors = document.createElement('div');
    colors.className = 'saved-palette-item-colors';
    palette.colors.forEach(function(hex) {
      var sw = document.createElement('span');
      sw.className = 'saved-palette-item-swatch';
      sw.style.background = hex;
      sw.title = hex;
      colors.appendChild(sw);
    });

    // Name
    var name = document.createElement('span');
    name.className = 'saved-palette-item-name';
    name.textContent = palette.name;

    // Actions
    var actions = document.createElement('div');
    actions.className = 'saved-palette-item-actions';

    var useBtn = document.createElement('button');
    useBtn.className = 'btn btn--ghost btn--small';
    useBtn.textContent = 'Use';
    useBtn.addEventListener('click', function() {
      applyPaletteToGenerator(palette.colors);
    });

    var delBtn = document.createElement('button');
    delBtn.className = 'btn btn--ghost btn--small';
    delBtn.textContent = 'Del';
    delBtn.style.color = '#CC0000';
    delBtn.addEventListener('click', async function() {
      savedPalettes.splice(idx, 1);
      await savePalettesToBackend();
      renderSavedPalettes();
      showToast('Palette deleted.', 'info');
    });

    actions.appendChild(useBtn);
    actions.appendChild(delBtn);

    item.appendChild(colors);
    item.appendChild(name);
    item.appendChild(actions);
    list.appendChild(item);
  });
}

function applyPaletteToGenerator(colors) {
  // Apply to the main generation form's palette lock
  lockedColors = [];
  document.querySelectorAll('#nes-palette-grid .palette-swatch.selected').forEach(function(el) {
    el.classList.remove('selected');
  });

  colors.forEach(function(hex) {
    if (lockedColors.length < MAX_LOCKED) {
      lockedColors.push(hex);
      // Find and select the matching swatch in the generation form grid
      var gridSwatches = document.querySelectorAll('#nes-palette-grid .palette-swatch');
      gridSwatches.forEach(function(s) {
        if (s.getAttribute('data-color') === hex) {
          s.classList.add('selected');
        }
      });
    }
  });
  updateLockedDisplay();
  navigateTo('generate');
  showToast('Palette applied! Colors locked in generator.', 'success');
}

/* ============================================================
   API Key Management (Pro/Studio only)
   ============================================================ */
var apiKeys = [];
var pendingRevokeKeyId = null;

async function loadApiKeys() {
  if (!isLoggedIn()) return;
  try {
    var resp = await fetch(API_BASE + '/api-keys', { headers: getAuthHeaders() });
    if (!resp.ok) return;
    var data = await resp.json();
    apiKeys = data.keys || [];
    renderApiKeys();
  } catch (err) {
    // Silently fail: key list is non-critical
  }
}

function renderApiKeys() {
  var list = document.getElementById('api-key-list');
  var noMsg = document.getElementById('no-api-keys-msg');
  if (!list) return;
  clearChildren(list);

  var active = apiKeys.filter(function(k) { return !k.revoked_at; });
  if (active.length === 0) {
    if (noMsg) noMsg.classList.remove('hidden');
    return;
  }
  if (noMsg) noMsg.classList.add('hidden');

  active.forEach(function(key) {
    var item = document.createElement('div');
    item.className = 'saved-template-item';

    var prefix = document.createElement('span');
    prefix.className = 'saved-template-item-name';
    prefix.style.fontFamily = 'monospace';
    prefix.style.fontWeight = '400';
    prefix.textContent = key.key_prefix;

    var meta = document.createElement('span');
    meta.className = 'saved-template-item-meta';
    var created = new Date(key.created_at).toLocaleDateString();
    var parts = ['Created ' + created];
    if (key.name && key.name !== 'Default') parts.push(key.name);
    // Per-key usage: monthly call count + last-used timestamp
    var limitDisplay = key.monthly_limit ? String(key.monthly_limit) : '\u221e';
    parts.push(key.monthly_used + '/' + limitDisplay + ' calls');
    if (key.last_used_at) {
      parts.push('Last used ' + new Date(key.last_used_at).toLocaleDateString());
    } else {
      parts.push('Never used');
    }
    meta.textContent = parts.join(' \u00b7 ');

    var actions = document.createElement('div');
    actions.className = 'saved-template-item-actions';

    var revokeBtn = document.createElement('button');
    revokeBtn.className = 'btn btn--ghost btn--small';
    revokeBtn.textContent = 'Revoke';
    revokeBtn.style.color = '#CC0000';
    revokeBtn.addEventListener('click', function() {
      openRevokeApiKeyModal(key);
    });

    actions.appendChild(revokeBtn);
    item.appendChild(prefix);
    item.appendChild(meta);
    item.appendChild(actions);
    list.appendChild(item);
  });
}

function showNewApiKey(key) {
  var display = document.getElementById('api-key-new-display');
  var warning = document.getElementById('api-key-new-warning');
  var valueEl = document.getElementById('api-key-value');
  if (!display || !warning || !valueEl) return;
  valueEl.textContent = key;
  display.classList.remove('hidden');
  warning.classList.remove('hidden');
}

function openRevokeApiKeyModal(key) {
  pendingRevokeKeyId = key.id;
  var prefixEl = document.getElementById('revoke-api-key-prefix');
  var errorEl = document.getElementById('revoke-api-key-error');
  var confirmBtn = document.getElementById('btn-confirm-revoke-api-key');
  if (prefixEl) prefixEl.textContent = key.key_prefix;
  if (errorEl) errorEl.classList.add('hidden');
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = 'Revoke Key';
  }
  document.getElementById('revoke-api-key-modal').classList.add('open');
}

function closeRevokeApiKeyModal() {
  pendingRevokeKeyId = null;
  document.getElementById('revoke-api-key-modal').classList.remove('open');
}

document.getElementById('btn-generate-key').addEventListener('click', async function() {
  if (!isLoggedIn()) return;
  var btn = this;
  btn.disabled = true;
  btn.textContent = 'Creating...';
  try {
    var headers = getAuthHeaders();
    headers['Content-Type'] = 'application/json';
    var resp = await fetch(API_BASE + '/api-keys', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ name: 'Default' }),
    });
    if (!resp.ok) {
      var errData = {};
      try { errData = await resp.json(); } catch (e) {}
      throw new Error(errData.detail || 'Failed to create API key.');
    }
    var data = await resp.json();
    showNewApiKey(data.key);
    await loadApiKeys();
    showToast('API key created.', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create New Key';
  }
});

document.getElementById('btn-copy-key').addEventListener('click', function() {
  var keyValue = document.getElementById('api-key-value').textContent;
  if (keyValue) {
    navigator.clipboard.writeText(keyValue).then(function() {
      showToast('API key copied!', 'success');
    });
  }
});

document.getElementById('btn-close-revoke-api-key').addEventListener('click', closeRevokeApiKeyModal);
document.getElementById('btn-cancel-revoke-api-key').addEventListener('click', closeRevokeApiKeyModal);
document.getElementById('revoke-api-key-modal').addEventListener('click', function(e) {
  if (e.target === this) closeRevokeApiKeyModal();
});
trapFocus(document.getElementById('revoke-api-key-modal'), closeRevokeApiKeyModal);

document.getElementById('btn-confirm-revoke-api-key').addEventListener('click', async function() {
  if (!isLoggedIn() || !pendingRevokeKeyId) return;
  var confirmBtn = this;
  var errorEl = document.getElementById('revoke-api-key-error');
  errorEl.classList.add('hidden');
  confirmBtn.disabled = true;
  confirmBtn.textContent = 'Revoking...';

  try {
    var resp = await fetch(API_BASE + '/api-keys/' + encodeURIComponent(pendingRevokeKeyId), {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!resp.ok) {
      var errData = {};
      try { errData = await resp.json(); } catch (e) {}
      throw new Error(errData.detail || 'Failed to revoke API key.');
    }
    closeRevokeApiKeyModal();
    await loadApiKeys();
    showToast('API key revoked.', 'success');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    confirmBtn.disabled = false;
    confirmBtn.textContent = 'Revoke Key';
  }
});

/* ============================================================
   Delete Profile (Danger Zone): GDPR right to erasure
   ============================================================ */

// The user must type their exact email (or the word DELETE if no email is
// available) to enable the confirm button. Comparison is case-insensitive
// and trimmed.
function deleteProfileExpectedValue() {
  if (currentUser && currentUser.email) return currentUser.email;
  return 'DELETE';
}

function openDeleteProfileModal() {
  if (!isLoggedIn()) return;
  var input = document.getElementById('delete-profile-confirm');
  var confirmBtn = document.getElementById('btn-confirm-delete-profile');
  var errorEl = document.getElementById('delete-profile-error');
  var hintEl = document.getElementById('delete-profile-email-hint');
  var expected = deleteProfileExpectedValue();

  // Tailor the prompt to whatever the user must type.
  if (expected === 'DELETE') {
    // No email on the session: fall back to typing DELETE.
    document.querySelector('label[for="delete-profile-confirm"]').firstChild.textContent =
      'Type DELETE ';
    hintEl.textContent = '';
    input.placeholder = 'DELETE';
  } else {
    document.querySelector('label[for="delete-profile-confirm"]').firstChild.textContent =
      'Type your email ';
    hintEl.textContent = '(' + expected + ')';
    input.placeholder = expected;
  }

  input.value = '';
  confirmBtn.disabled = true;
  errorEl.classList.add('hidden');
  document.getElementById('delete-profile-modal').classList.add('open');
  input.focus();
}

function closeDeleteProfileModal() {
  document.getElementById('delete-profile-modal').classList.remove('open');
}

document.getElementById('btn-delete-profile').addEventListener('click', openDeleteProfileModal);
document.getElementById('btn-close-delete-profile').addEventListener('click', closeDeleteProfileModal);
document.getElementById('delete-profile-modal').addEventListener('click', function(e) {
  if (e.target === this) closeDeleteProfileModal();
});
trapFocus(document.getElementById('delete-profile-modal'), closeDeleteProfileModal);

// Enable the confirm button only when the typed value matches.
document.getElementById('delete-profile-confirm').addEventListener('input', function() {
  var expected = deleteProfileExpectedValue();
  var typed = this.value.trim();
  var match = typed.toLowerCase() === expected.toLowerCase();
  document.getElementById('btn-confirm-delete-profile').disabled = !match;
});

// Confirm submission: call DELETE /profile, then sign out on success.
document.getElementById('delete-profile-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  if (!isLoggedIn()) return;

  var expected = deleteProfileExpectedValue();
  var typed = document.getElementById('delete-profile-confirm').value.trim();
  var errorEl = document.getElementById('delete-profile-error');
  var confirmBtn = document.getElementById('btn-confirm-delete-profile');
  errorEl.classList.add('hidden');

  // Defensive re-check (button is disabled until match, but guard anyway).
  if (typed.toLowerCase() !== expected.toLowerCase()) {
    errorEl.textContent = 'The confirmation text does not match.';
    errorEl.classList.remove('hidden');
    return;
  }

  confirmBtn.disabled = true;
  confirmBtn.textContent = 'DELETING...';

  try {
    var resp = await fetch(API_BASE + '/profile', {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });

    if (resp.status === 409) {
      // Shared-org block: show the server message, do NOT sign out.
      var data409 = {};
      try { data409 = await resp.json(); } catch (e2) {}
      errorEl.textContent = data409.detail || 'You must transfer organization ownership before deleting your profile.';
      errorEl.classList.remove('hidden');
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'DELETE MY PROFILE';
      return;
    }

    if (!resp.ok) {
      var dataErr = {};
      try { dataErr = await resp.json(); } catch (e3) {}
      throw new Error(dataErr.detail || 'Profile deletion failed. Please try again.');
    }

    // Success: sign out and return to the logged-out home/generate state.
    closeDeleteProfileModal();
    if (supabaseClient) {
      await supabaseClient.auth.signOut();
    }
    currentUser = null;
    currentSession = null;
    updateAuthUI();
    showToast('Your profile has been deleted.', 'success');
    navigateTo('generate');
  } catch (err) {
    errorEl.textContent = err.message || 'Profile deletion failed. Please try again.';
    errorEl.classList.remove('hidden');
    confirmBtn.disabled = false;
    confirmBtn.textContent = 'DELETE MY PROFILE';
  }
});

/* ============================================================
   LegacyPlans Page
   ============================================================ */
var legacyPlansInterval = 'monthly';

// Billing interval toggle
document.querySelectorAll('.legacyPlans-toggle-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.legacyPlans-toggle-btn').forEach(function(b) {
      b.classList.remove('active');
      b.setAttribute('aria-checked', 'false');
    });
    btn.classList.add('active');
    btn.setAttribute('aria-checked', 'true');
    legacyPlansInterval = btn.getAttribute('data-interval');
    updateLegacyPlansDisplay();
  });
});

function updateLegacyPlansDisplay() {
  document.querySelectorAll('.legacyPlans-amount[data-monthly]').forEach(function(el) {
    el.textContent = el.getAttribute('data-' + legacyPlansInterval);
  });
  document.querySelectorAll('.legacyPlans-interval[data-monthly]').forEach(function(el) {
    el.textContent = el.getAttribute('data-' + legacyPlansInterval);
  });
}

async function loadLegacyPlans() {
  if (!isLoggedIn()) {
    // Show all openSource buttons, no "current" badge
    showLegacyPlansForTier('free');
    return;
  }

  try {
    var resp = await fetch(API_BASE + '/subscription', { headers: getAuthHeaders() });
    if (!resp.ok) {
      showLegacyPlansForTier('free');
      return;
    }
    var data = await resp.json();
    showLegacyPlansForTier(data.tier || 'free');
  } catch (err) {
    showLegacyPlansForTier('free');
  }
}

function showLegacyPlansForTier(currentTier) {
  var tiers = ['free', 'starter', 'pro', 'studio'];

  tiers.forEach(function(tier) {
    var badge = document.getElementById('legacyPlans-current-' + tier);
    var btns = document.querySelectorAll('.legacyPlans-openSource-btn[data-tier="' + tier + '"]');

    if (tier === currentTier) {
      if (badge) badge.classList.remove('hidden');
      btns.forEach(function(b) { b.classList.add('hidden'); });
    } else {
      if (badge) badge.classList.add('hidden');
      btns.forEach(function(b) {
        b.classList.remove('hidden');
        // For tiers below current, show "DOWNGRADE" (or hide for free)
        if (tier === 'free') {
          b.classList.add('hidden');
        } else if (tiers.indexOf(tier) < tiers.indexOf(currentTier)) {
          b.textContent = 'DOWNGRADE';
          b.className = 'btn btn--ghost btn--small legacyPlans-openSource-btn';
        } else {
          b.textContent = 'OPEN_SOURCE';
          b.className = 'btn btn--primary btn--small legacyPlans-openSource-btn';
        }
      });
    }
  });
}

// OpenSource button clicks
document.querySelectorAll('.legacyPlans-openSource-btn').forEach(function(btn) {
  btn.addEventListener('click', async function() {
    var tier = btn.getAttribute('data-tier');
    if (!tier || tier === 'free') return;

    trackFunnel('openSource_click', { source: 'legacyPlans_page', tier: tier });

    if (!isLoggedIn()) {
      openAuthModal();
      showToast('Not available in the free open-source build.', 'info');
      return;
    }

    btn.disabled = true;
    btn.textContent = 'LOADING...';

    try {
      var resp = await fetch(API_BASE + '/legacyOrder', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeaders()),
        body: JSON.stringify({ tier: tier, interval: legacyPlansInterval, return_url: window.location.origin + window.location.pathname, ref: getStoredLegacyShare(currentUser.id) }),
      });

      if (!resp.ok) {
        var errData = await resp.json().catch(function() { return {}; });
        throw new Error(errData.detail || 'Failed to create legacyOrder.');
      }

      var data = await resp.json();
      if (data.legacyOrder_url) {
        await storePreLegacyOrderTier();
        window.location.href = data.legacyOrder_url;
      } else {
        throw new Error('No legacyOrder URL returned.');
      }
    } catch (err) {
      showToast(err.message || 'LegacyOrder failed. Try again.', 'error');
      btn.disabled = false;
      btn.textContent = 'OPEN_SOURCE';
    }
  });
});

/* ============================================================
   Subscription Section (Settings Page)
   ============================================================ */
async function loadSubscription() {
  if (!isLoggedIn()) return;

  try {
    var resp = await fetch(API_BASE + '/subscription', { headers: getAuthHeaders() });
    if (!resp.ok) return;
    var data = await resp.json();

    // Tier badge
    var tierBadge = document.getElementById('settings-tier-badge');
    if (tierBadge) tierBadge.textContent = (data.tier || 'free').toUpperCase();

    var legacyShareLink = document.getElementById('settings-legacyShare-link');
    if (legacyShareLink && data.legacyShare_code) {
      legacyShareLink.value = 'https://retrogazeai.com/?ref=' + data.legacyShare_code;
    }

    // Subscription status text
    var statusEl = document.getElementById('settings-sub-status');
    if (statusEl) {
      var status = data.subscription_status || 'none';
      statusEl.className = 'subscription-status';
      if (status === 'active') {
        statusEl.textContent = 'Active';
        statusEl.classList.add('status-active');
      } else if (status === 'past_due') {
        statusEl.textContent = 'Past Due';
        statusEl.classList.add('status-past-due');
      } else if (status === 'cancelled') {
        statusEl.textContent = 'Cancelled (active until period ends)';
        statusEl.classList.add('status-cancelled');
      } else if (status === 'paused') {
        statusEl.textContent = data.subscription_pause_mode === 'free' ? 'Active (free legacyShare month)' : 'Paused';
      } else {
        statusEl.textContent = '';
      }
    }

    // Renewal date
    var renewsEl = document.getElementById('settings-renews-at');
    if (renewsEl && data.subscription_renews_at) {
      var d = new Date(data.subscription_renews_at);
      renewsEl.textContent = 'Renews ' + d.toLocaleDateString();
    } else if (renewsEl) {
      renewsEl.textContent = '';
    }

    // Show/hide openSource vs manage billing buttons
    var openSourceBtn = document.getElementById('btn-openSource');
    var billingBtn = document.getElementById('btn-manage-billing');
    if (data.has_subscription) {
      if (openSourceBtn) openSourceBtn.classList.add('hidden');
      if (billingBtn) billingBtn.classList.remove('hidden');
    } else {
      if (openSourceBtn) openSourceBtn.classList.remove('hidden');
      if (billingBtn) billingBtn.classList.add('hidden');
    }
  } catch (err) {
    // Non-critical
  }
}

var copyLegacyShareBtn = document.getElementById('btn-copy-legacyShare');
if (copyLegacyShareBtn) {
  copyLegacyShareBtn.addEventListener('click', function() {
    var input = document.getElementById('settings-legacyShare-link');
    if (!input || !input.value) return;
    navigator.clipboard.writeText(input.value).then(function() {
      showToast('LegacyShare link copied.', 'success');
    }).catch(function() {
      input.select();
      showToast('Select and copy your legacyShare link.', 'info');
    });
  });
}

// Manage Billing button
document.getElementById('btn-manage-billing').addEventListener('click', async function() {
  if (!isLoggedIn()) return;

  var btn = this;
  btn.disabled = true;
  btn.textContent = 'LOADING...';

  try {
    var resp = await fetch(API_BASE + '/billing-portal', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeaders()),
    });
    if (!resp.ok) {
      var errData = await resp.json().catch(function() { return {}; });
      throw new Error(errData.detail || 'Billing is not available in the free open-source build.');
    }
    var data = await resp.json();
    if (data.portal_url) {
      window.open(data.portal_url, '_blank');
    }
  } catch (err) {
    showToast(err.message || 'Billing is not available in the free open-source build.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'MANAGE';
  }
});

/* ============================================================
   OpenSource Nudge: direct LegacyBilling legacyOrder from usage meter + settings
   ============================================================ */
async function initiateOpenSourceLegacyOrder(tier, btn) {
  if (!isLoggedIn()) {
    openAuthModal();
    showToast('Not available in the free open-source build.', 'info');
    return;
  }

  var originalText = btn.textContent;
  btn.style.pointerEvents = 'none';
  btn.textContent = 'LOADING...';

  try {
    var resp = await fetch(API_BASE + '/legacyOrder', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeaders()),
      body: JSON.stringify({ tier: tier, interval: legacyPlansInterval, return_url: window.location.origin + window.location.pathname, ref: getStoredLegacyShare(currentUser.id) }),
    });

    if (!resp.ok) {
      var errData = await resp.json().catch(function() { return {}; });
      throw new Error(errData.detail || 'Failed to create legacyOrder.');
    }

    var data = await resp.json();
    if (data.legacyOrder_url) {
      await storePreLegacyOrderTier();
      window.location.href = data.legacyOrder_url;
    } else {
      throw new Error('No legacyOrder URL returned.');
    }
  } catch (err) {
    showToast(err.message || 'LegacyOrder failed. Try again.', 'error');
    btn.style.pointerEvents = '';
    btn.textContent = originalText;
  }
}

// Settings "OPEN_SOURCE" button: initiates legacyOrder for starter tier
var btnOpenSource = document.getElementById('btn-openSource');
if (btnOpenSource) {
  btnOpenSource.addEventListener('click', function(e) {
    e.preventDefault();
    trackFunnel('openSource_click', { source: 'settings_button', tier: 'starter' });
    initiateOpenSourceLegacyOrder('starter', this);
  });
}

// Usage meter ≥90% "OpenSource" links: initiate legacyOrder for starter tier
var meterDailyOpenSource = document.getElementById('meter-daily-openSource');
if (meterDailyOpenSource) {
  meterDailyOpenSource.addEventListener('click', function(e) {
    e.preventDefault();
    trackFunnel('openSource_click', { source: 'meter_daily', tier: 'starter' });
    initiateOpenSourceLegacyOrder('starter', this);
  });
}

var meterMonthlyOpenSource = document.getElementById('meter-monthly-openSource');
if (meterMonthlyOpenSource) {
  meterMonthlyOpenSource.addEventListener('click', function(e) {
    e.preventDefault();
    trackFunnel('openSource_click', { source: 'meter_monthly', tier: 'starter' });
    initiateOpenSourceLegacyOrder('starter', this);
  });
}

/* ============================================================
   "More Like This": Style Reference Lock
   ============================================================ */
document.getElementById('btn-more-like-this').addEventListener('click', function() {
  var d = window._retrogazeData;
  if (!d || !d.image_base64) return;
  trackEvent('more_like_this');

  // Load the generated image as the reference
  currentRefBase64 = d.image_base64;
  var dataURI = 'data:image/png;base64,' + d.image_base64;
  refPreview.src = dataURI;
  refPreview.classList.remove('hidden');
  clearRefBtn.classList.remove('hidden');
  strengthGroup.style.display = '';

  // Set strength to 70% (close to reference: keeps the style, allows new details)
  strengthSlider.value = 70;
  strengthLabel.textContent = '70%: Close to reference';

  // Switch back to the form
  showState('form');
  showToast('Reference loaded. Adjust strength and description, then generate.', 'info');
});

/* ============================================================
   Prompt Templates: Save / Load / Delete
   ============================================================ */
var TEMPLATES_STORAGE_KEY = 'retrogaze_prompt_templates';

function getLocalTemplates() {
  try {
    return JSON.parse(localStorage.getItem(TEMPLATES_STORAGE_KEY)) || [];
  } catch (e) {
    return [];
  }
}

function saveLocalTemplates(templates) {
  localStorage.setItem(TEMPLATES_STORAGE_KEY, JSON.stringify(templates));
}

function captureFormState() {
  return {
    description:      document.getElementById('description').value.trim(),
    asset_type:       document.getElementById('asset-type').value,
    size:             document.getElementById('size').value,
    view:             document.getElementById('view').value,
    palette_mood:     document.getElementById('palette-mood').value,
    outline:          document.getElementById('outline').value,
    era:              document.getElementById('era').value,
    console:          document.getElementById('console').value,
    scale_factor:     document.getElementById('scale-factor').value,
    export_palette:   document.getElementById('export-palette').value,
    bg_color_on:      document.getElementById('bg-color-toggle').checked,
    background_color: document.getElementById('background-color').value,
    flip_horizontal:  document.getElementById('flip-horizontal').checked,
    strict_size:      (document.getElementById('strict-size') || {}).checked || false,
    palette_colors:   lockedColors.slice(),
  };
}

function applyFormState(tpl) {
  if (tpl.description) document.getElementById('description').value = tpl.description;
  if (tpl.asset_type) setSelectValue('asset-type', tpl.asset_type);
  if (tpl.size) setSelectValue('size', tpl.size);
  if (tpl.view) setSelectValue('view', tpl.view);
  if (tpl.palette_mood) setSelectValue('palette-mood', tpl.palette_mood);
  if (tpl.outline) setSelectValue('outline', tpl.outline);
  if (tpl.era) setSelectValue('era', tpl.era);
  if (tpl.console) {
    setSelectValue('console', tpl.console);
    if (consoleHint && consoleHints[tpl.console]) consoleHint.textContent = consoleHints[tpl.console];
  }
  if (tpl.scale_factor) setSelectValue('scale-factor', tpl.scale_factor);
  if (tpl.export_palette !== undefined) setSelectValue('export-palette', tpl.export_palette);

  // Background color
  var bgToggle = document.getElementById('bg-color-toggle');
  var bgInput = document.getElementById('background-color');
  if (bgToggle && bgInput) {
    bgToggle.checked = !!tpl.bg_color_on;
    bgInput.disabled = !bgToggle.checked;
    if (tpl.background_color) bgInput.value = tpl.background_color;
  }

  // Flip
  var flipCheck = document.getElementById('flip-horizontal');
  if (flipCheck) flipCheck.checked = !!tpl.flip_horizontal;

  // Strict size
  var strictCheck = document.getElementById('strict-size');
  if (strictCheck) strictCheck.checked = !!tpl.strict_size;

  // Palette lock
  if (tpl.palette_colors && tpl.palette_colors.length > 0) {
    applyPaletteToGenerator(tpl.palette_colors);
  } else {
    // Clear palette lock
    lockedColors = [];
    document.querySelectorAll('#nes-palette-grid .palette-swatch.selected').forEach(function(el) {
      el.classList.remove('selected');
    });
    updateLockedDisplay();
  }

  // Show/hide animation options
  var animOpts = document.getElementById('animation-options');
  if (animOpts) {
    animOpts.style.display = (tpl.asset_type === 'spritesheet') ? '' : 'none';
  }
}

var EXAMPLE_PRESET = {
  description:      'a knight with sword and shield',
  asset_type:         'character',
  size:               '16x16',
  view:               'side',
  palette_mood:       'auto',
  outline:            'black',
  era:                'mid',
  console:            'nes',
  scale_factor:       '1',
  export_palette:     '',
  bg_color_on:        false,
  flip_horizontal:    false,
  strict_size:        false,
  palette_colors:     [],
};

var tryExampleBtn = document.getElementById('btn-try-example');
if (tryExampleBtn) {
  tryExampleBtn.addEventListener('click', function() {
    if (currentRefBase64) clearRefBtn.click();
    applyFormState(EXAMPLE_PRESET);
    formError.classList.add('hidden');
    formError.textContent = '';
    var generateBtn = form.querySelector('.btn--generate');
    if (generateBtn) generateBtn.focus();
    trackEvent('example_loaded');
  });
}

function renderTemplateDropdown() {
  var select = document.getElementById('prompt-template-select');
  // Keep the first placeholder option, remove the rest
  while (select.options.length > 1) {
    select.remove(1);
  }

  var templates = getLocalTemplates();
  templates.forEach(function(tpl, idx) {
    var opt = document.createElement('option');
    opt.value = idx;
    opt.textContent = tpl.name + ' (' + tpl.settings.asset_type + ', ' + tpl.settings.size + ')';
    select.appendChild(opt);
  });
}

function renderSettingsTemplateList() {
  var list = document.getElementById('saved-template-list');
  var noMsg = document.getElementById('no-templates-msg');
  if (!list) return;
  clearChildren(list);

  var templates = getLocalTemplates();
  if (templates.length === 0) {
    if (noMsg) noMsg.classList.remove('hidden');
    return;
  }
  if (noMsg) noMsg.classList.add('hidden');

  templates.forEach(function(tpl, idx) {
    var item = document.createElement('div');
    item.className = 'saved-template-item';

    var name = document.createElement('span');
    name.className = 'saved-template-item-name';
    name.textContent = tpl.name;

    var meta = document.createElement('span');
    meta.className = 'saved-template-item-meta';
    var parts = [tpl.settings.asset_type, tpl.settings.size, tpl.settings.era];
    if (tpl.settings.description) {
      parts.push('"' + tpl.settings.description.slice(0, 30) + (tpl.settings.description.length > 30 ? '...' : '') + '"');
    }
    meta.textContent = parts.join(' \u00b7 ');

    var actions = document.createElement('div');
    actions.className = 'saved-template-item-actions';

    var loadBtn = document.createElement('button');
    loadBtn.className = 'btn btn--ghost btn--small';
    loadBtn.textContent = 'Load';
    loadBtn.addEventListener('click', function() {
      applyFormState(tpl.settings);
      navigateTo('generate');
      showToast('Template "' + tpl.name + '" loaded.', 'success');
    });

    var delBtn = document.createElement('button');
    delBtn.className = 'btn btn--ghost btn--small';
    delBtn.textContent = 'Del';
    delBtn.style.color = '#CC0000';
    delBtn.addEventListener('click', function() {
      var templates = getLocalTemplates();
      templates.splice(idx, 1);
      saveLocalTemplates(templates);
      renderSettingsTemplateList();
      renderTemplateDropdown();
      showToast('Template deleted.', 'info');
    });

    actions.appendChild(loadBtn);
    actions.appendChild(delBtn);

    item.appendChild(name);
    item.appendChild(meta);
    item.appendChild(actions);
    list.appendChild(item);
  });
}

// Load template from dropdown
document.getElementById('prompt-template-select').addEventListener('change', function() {
  var idx = parseInt(this.value, 10);
  if (isNaN(idx)) return;

  var templates = getLocalTemplates();
  if (templates[idx]) {
    applyFormState(templates[idx].settings);
    trackEvent('template_loaded', { template_name: templates[idx].name });
    showToast('Template "' + templates[idx].name + '" loaded.', 'success');
  }
  // Reset dropdown to placeholder
  this.value = '';
});

// ---------------------------------------------------------------------------
// Feedback modal
// ---------------------------------------------------------------------------

function openFeedbackModal() {
  document.getElementById('feedback-category').value = 'bug';
  document.getElementById('feedback-message').value = '';
  document.getElementById('feedback-error').classList.add('hidden');
  document.getElementById('feedback-modal').classList.add('open');
  document.getElementById('feedback-message').focus();
}

function closeFeedbackModal() {
  document.getElementById('feedback-modal').classList.remove('open');
}

document.getElementById('btn-feedback').addEventListener('click', openFeedbackModal);
document.getElementById('btn-close-feedback').addEventListener('click', closeFeedbackModal);
document.getElementById('btn-cancel-feedback').addEventListener('click', closeFeedbackModal);
document.getElementById('feedback-modal').addEventListener('click', function(e) {
  if (e.target === this) closeFeedbackModal();
});
trapFocus(document.getElementById('feedback-modal'), closeFeedbackModal);

document.getElementById('feedback-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('feedback-error');
  var sendBtn = document.getElementById('btn-send-feedback');
  errorEl.classList.add('hidden');

  var message = document.getElementById('feedback-message').value.trim();
  if (!message) {
    errorEl.textContent = 'Please enter a message.';
    errorEl.classList.remove('hidden');
    return;
  }

  var payload = {
    message: message,
    category: document.getElementById('feedback-category').value,
    context: currentPage,
  };

  sendBtn.disabled = true;
  sendBtn.textContent = 'Sending...';

  try {
    var resp = await fetch(API_BASE + '/feedback', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, getAuthHeaders()),
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      var errData = {};
      try { errData = await resp.json(); } catch (_) {}
      throw new Error(errData.detail || 'Failed to send feedback.');
    }

    closeFeedbackModal();
    showToast('Thanks for your feedback!', 'success');
  } catch (err) {
    errorEl.textContent = err.message || 'Failed to send feedback.';
    errorEl.classList.remove('hidden');
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
  }
});

// Open save prompt modal
document.getElementById('btn-save-prompt').addEventListener('click', function() {
  document.getElementById('save-prompt-modal').classList.add('open');
  document.getElementById('prompt-template-name').value = '';
  document.getElementById('prompt-template-name').focus();
});

// Close save prompt modal
function closeSavePromptModal() {
  document.getElementById('save-prompt-modal').classList.remove('open');
}
document.getElementById('btn-close-save-prompt').addEventListener('click', closeSavePromptModal);
document.getElementById('save-prompt-modal').addEventListener('click', function(e) {
  if (e.target === this) closeSavePromptModal();
});
trapFocus(document.getElementById('save-prompt-modal'), closeSavePromptModal);

// Save prompt form submit
document.getElementById('save-prompt-form').addEventListener('submit', function(e) {
  e.preventDefault();
  var errorEl = document.getElementById('save-prompt-error');
  errorEl.classList.add('hidden');

  var name = document.getElementById('prompt-template-name').value.trim();
  if (!name) {
    errorEl.textContent = 'Please enter a name for this template.';
    errorEl.classList.remove('hidden');
    return;
  }

  var templates = getLocalTemplates();

  // Check for duplicate names
  var duplicate = templates.some(function(t) { return t.name === name; });
  if (duplicate) {
    errorEl.textContent = 'A template with this name already exists.';
    errorEl.classList.remove('hidden');
    return;
  }

  // Limit to 20 templates
  if (templates.length >= 20) {
    errorEl.textContent = 'Maximum 20 templates. Delete some first.';
    errorEl.classList.remove('hidden');
    return;
  }

  var settings = captureFormState();
  templates.push({ name: name, settings: settings });
  saveLocalTemplates(templates);

  renderTemplateDropdown();
  renderSettingsTemplateList();

  document.getElementById('save-prompt-modal').classList.remove('open');
  trackEvent('template_saved', { template_name: name });
  showToast('Template "' + name + '" saved!', 'success');
});

// Initialize template dropdown on load
renderTemplateDropdown();

/* ============================================================
   Post-LegacyOrder Return Handling
   ============================================================ */

// Capture the user's tier *before* redirecting to LegacyBilling so
// checkPostLegacyOrder() can detect the change when the user returns.
async function storePreLegacyOrderTier() {
  try {
    var resp = await fetch(API_BASE + '/subscription', { headers: getAuthHeaders() });
    if (resp.ok) {
      var data = await resp.json();
      sessionStorage.setItem('preLegacyOrderTier', data.tier || 'free');
    }
  } catch (e) { /* non-critical */ }
}

function checkPostLegacyOrder() {
  if (window.location.search.indexOf('legacyOrder=success') === -1) return;

  var preLegacyOrderTier = sessionStorage.getItem('preLegacyOrderTier');
  sessionStorage.removeItem('preLegacyOrderTier');

  // Clean up the URL
  if (window.history && window.history.replaceState) {
    window.history.replaceState({}, '', window.location.pathname);
  }

  if (!isLoggedIn()) {
    showToast('Subscription activated! Open the app to continue.', 'success');
    return;
  }

  showToast('Processing your subscription…', 'info');

  // Poll /subscription until the webhook lands and the tier changes.
  // LegacyBilling's webhook is async: it can take several seconds to
  // arrive after the user returns. We poll every 2s for up to 30s.
  var attempts = 0;
  var maxAttempts = 15;

  (async function poll() {
    attempts++;
    try {
      var resp = await fetch(API_BASE + '/subscription', { headers: getAuthHeaders() });
      if (resp.ok) {
        var data = await resp.json();
        var tier = data.tier || 'free';
        var tierChanged = preLegacyOrderTier && tier !== preLegacyOrderTier;
        var newSub = !preLegacyOrderTier && data.has_subscription && tier !== 'free';

        if (tierChanged || newSub) {
          loadUsage();
          loadSubscription();
          showToast('Subscription activated! Welcome.', 'success');
          return;
        }
      }
    } catch (e) { /* retry on next tick */ }

    if (attempts >= maxAttempts) {
      // Webhook hasn't landed yet: refresh once more and ask the user to
      // check back shortly rather than leaving them stuck on "free".
      loadUsage();
      loadSubscription();
      showToast('Subscription is processing. If access has not updated, refresh in a moment.', 'info');
      return;
    }
    setTimeout(poll, 2000);
  })();
}

/* ============================================================
   Init
   ============================================================ */
showState('form');
updateAuthUI();
initSupabase().then(function() {
  checkPostLegacyOrder();
  if (isLoggedIn()) {
    loadSubscription();
    loadUsage();
  }
});
