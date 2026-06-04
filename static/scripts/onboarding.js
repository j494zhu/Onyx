/* ══════════════════════════════════════════════════════════════
   ONYX — Onboarding & Settings JS
   Wizard navigation, tag selection, card selection, form submit
   ══════════════════════════════════════════════════════════════ */

// ── Shared utilities ──────────────────────────────────────────
function isOnOnboardingPage() {
  return !!document.querySelector('.onboard-slides');
}

function isOnSettingsPage() {
  return !!document.querySelector('.settings-form');
}

// ── Choice card toggling (single-select per field group) ──────
function initChoiceCards(container) {
  container.querySelectorAll('.card-row').forEach(function (row) {
    row.addEventListener('click', function (e) {
      var card = e.target.closest('.choice-card');
      if (!card) return;
      row.querySelectorAll('.choice-card').forEach(function (c) {
        c.classList.remove('is-selected');
      });
      card.classList.add('is-selected');
    });
  });
}

// ── Tag chip toggling (multi-select) ──────────────────────────
function initTagChips(container) {
  container.querySelectorAll('.tag-row[data-multi]').forEach(function (row) {
    row.addEventListener('click', function (e) {
      var chip = e.target.closest('.tag-chip');
      if (!chip) return;
      chip.classList.toggle('is-selected');
    });
  });
}

// ── Gather form data from DOM ─────────────────────────────────
function collectFormData(container) {
  var data = {};

  // Time inputs by id
  var timeIds = [
    'wakeup', 'bedtime',
    'bfast-start', 'bfast-end',
    'lunch-start', 'lunch-end',
    'dinner-start', 'dinner-end',
    'peak-start', 'peak-end',
  ];
  timeIds.forEach(function (id) {
    var el = container.querySelector('#' + id);
    if (el && el.value) {
      var fieldName = id.replace(/-/g, '_');
      data[fieldName] = el.value;
    }
  });
  // Direct name-based inputs
  container.querySelectorAll('input[name], textarea[name]').forEach(function (el) {
    if (el.name) data[el.name] = el.value;
  });

  // Text input by id
  var goalEl = container.querySelector('#primary-goal');
  if (goalEl) data['primary_goal'] = goalEl.value.trim();

  // Textarea by id
  var sgEl = container.querySelector('#secondary-goals');
  if (sgEl) {
    var goals = sgEl.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    data['secondary_goals'] = goals;
  }

  // Choice cards (single-select)
  container.querySelectorAll('.card-row').forEach(function (row) {
    var field = row.dataset.field || row.dataset.settingsField;
    if (!field) return;
    var selected = row.querySelector('.choice-card.is-selected');
    if (selected) {
      data[field] = selected.dataset.value;
    }
  });

  // Tag chips (multi-select)
  container.querySelectorAll('.tag-row[data-multi]').forEach(function (row) {
    var field = row.dataset.field || row.dataset.settingsField;
    if (!field) return;
    var selected = [];
    row.querySelectorAll('.tag-chip.is-selected').forEach(function (chip) {
      selected.push(chip.dataset.value);
    });
    data[field] = selected;
  });

  return data;
}

// ── Build review summary ─────────────────────────────────────
function updateReview() {
  var data = collectFormData(document);

  var rhythmParts = [];
  if (data.wakeup) rhythmParts.push('Wake ' + data.wakeup);
  if (data.bedtime) rhythmParts.push('Sleep ' + data.bedtime);
  var rhythm = rhythmParts.join(' \u00B7 ') || 'Not set';
  var meals = [];
  if (data.bfast_start && data.bfast_end) meals.push('Breakfast ' + data.bfast_start + '-' + data.bfast_end);
  if (data.lunch_start && data.lunch_end) meals.push('Lunch ' + data.lunch_start + '-' + data.lunch_end);
  if (data.dinner_start && data.dinner_end) meals.push('Dinner ' + data.dinner_start + '-' + data.dinner_end);
  var reviewRhythm = rhythm + (meals.length ? '\n' + meals.join(' \u00B7 ') : '');
  var rhyEl = document.getElementById('review-rhythm');
  if (rhyEl) rhyEl.innerText = reviewRhythm;

  var styleParts = [];
  if (data.chronotype) styleParts.push(data.chronotype === 'morning' ? 'Morning Person' : data.chronotype === 'night_owl' ? 'Night Owl' : 'Flexible');
  if (data.peak_start && data.peak_end) styleParts.push('Peak ' + data.peak_start + '-' + data.peak_end);
  if (data.daily_burden) styleParts.push(data.daily_burden.charAt(0).toUpperCase() + data.daily_burden.slice(1) + ' burden');
  if (data.work_style) styleParts.push('Style: ' + data.work_style.join(', '));
  var styEl = document.getElementById('review-style');
  if (styEl) styEl.innerText = styleParts.join(' \u00B7 ') || 'Not set';

  var goalParts = [];
  if (data.primary_goal) goalParts.push('Primary: ' + data.primary_goal);
  if (data.interests && data.interests.length) goalParts.push('Interests: ' + data.interests.join(', '));
  if (data.ai_role && data.ai_role.length) goalParts.push('AI Role: ' + data.ai_role.join(', '));
  if (data.secondary_goals && data.secondary_goals.length) goalParts.push('Also: ' + data.secondary_goals.join(', '));
  var golEl = document.getElementById('review-goals');
  if (golEl) golEl.innerText = goalParts.join('\n') || 'Not set';
}

// ── Build JSON payload compatible with _update_profile_from_form ──
function buildPayload() {
  var data = collectFormData(document);
  // Map onboarding IDs to model field names
  var idToField = {
    'wakeup': 'typical_wakeup',
    'bedtime': 'typical_bedtime',
    'bfast_start': 'breakfast_window_start',
    'bfast_end': 'breakfast_window_end',
    'lunch_start': 'lunch_window_start',
    'lunch_end': 'lunch_window_end',
    'dinner_start': 'dinner_window_start',
    'dinner_end': 'dinner_window_end',
    'peak_start': 'peak_start',
    'peak_end': 'peak_end',
  };
  Object.keys(idToField).forEach(function (id) {
    if (data[id] !== undefined) {
      data[idToField[id]] = data[id];
      delete data[id];
    }
  });
  return data;
}

// ═══════════════════════════════════════════════════════════
// ONBOARDING WIZARD
// ═══════════════════════════════════════════════════════════
if (isOnOnboardingPage()) {
  var slides = document.querySelectorAll('.onboard-slide');
  var dots = document.querySelectorAll('.onboard-dot');
  var btnBack = document.getElementById('btn-back');
  var btnNext = document.getElementById('btn-next');
  var btnSkip = document.getElementById('btn-skip');
  var currentStep = 0;
  var totalSteps = slides.length;

  function showStep(step) {
    slides.forEach(function (s, i) {
      s.classList.toggle('is-active', i === step);
    });
    dots.forEach(function (d, i) {
      d.classList.remove('is-active', 'is-done');
      if (i === step) d.classList.add('is-active');
      if (i < step) d.classList.add('is-done');
    });
    btnBack.disabled = step === 0;
    if (step === totalSteps - 1) {
      btnNext.textContent = 'Complete Setup';
      btnSkip.style.display = 'none';
      updateReview();
    } else {
      btnNext.textContent = 'Next';
      btnSkip.style.display = '';
    }
    currentStep = step;
  }

  function goTo(step) { showStep(step); }

  btnBack.addEventListener('click', function () {
    if (currentStep > 0) goTo(currentStep - 1);
  });

  btnNext.addEventListener('click', function () {
    if (currentStep < totalSteps - 1) {
      goTo(currentStep + 1);
    } else {
      // Final submit
      btnNext.disabled = true;
      btnNext.textContent = 'SAVING...';
      var payload = buildPayload();
      fetch('/onboarding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.redirect) window.location.href = d.redirect;
        })
        .catch(function () {
          btnNext.disabled = false;
          btnNext.textContent = 'Complete Setup';
        });
    }
  });

  btnSkip.addEventListener('click', function () {
    // Submit with empty data (just redirects)
    fetch('/onboarding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.redirect) window.location.href = d.redirect;
      });
  });

  // Review "Edit" buttons
  document.querySelectorAll('.review-block__edit').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var step = parseInt(btn.dataset.goto, 10);
      if (!isNaN(step)) goTo(step);
    });
  });

  // Init UI interactions
  initChoiceCards(document);
  initTagChips(document);
}

// ═══════════════════════════════════════════════════════════
// SETTINGS PAGE
// ═══════════════════════════════════════════════════════════
if (isOnSettingsPage()) {
  initChoiceCards(document);
  initTagChips(document);

  var form = document.getElementById('settings-form');
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var payload = buildPayload();
    // Handle secondary goals textarea
    var sgEl = document.getElementById('settings-secondary');
    if (sgEl) {
      var goals = sgEl.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      payload['secondary_goals'] = goals;
    }
    // Collect name-based form fields
    form.querySelectorAll('input[name], textarea[name]').forEach(function (el) {
      if (el.name && payload[el.name] === undefined) {
        payload[el.name] = el.value;
      }
    });

    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = 'SAVING...';

    fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        window.location.href = '/';
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = 'Save Changes';
      });
  });
}
