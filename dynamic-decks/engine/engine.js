/* ==========================================================================
   DynamicDecks engine
   Navigation, scaling, step reveals, slide lifecycle, resting state,
   presenter view, notes, overview and print. One copy, shared by every deck.
   Do not edit per deck: slide content talks to the engine only through
   attributes, the deck:* events and the `deck` object described below.

   Events dispatched on a slide (they bubble to document):
     deck:enter  the slide became current and may animate
     deck:rest   the slide must show its final frame now, with no motion
     deck:step   the step index was set   detail: { step, total, direction }
     deck:leave  the slide is no longer current
   ========================================================================== */
(function () {
  'use strict';

  var W = 1920, H = 1080;
  var KEY = '__dynamicdecks';
  var root = document.documentElement;
  var deckEl = document.querySelector('main.deck') || document.querySelector('.deck');
  if (!deckEl) return;

  var slides = Array.prototype.filter.call(deckEl.children, function (el) {
    return el.tagName === 'SECTION' && el.classList.contains('slide');
  });
  if (!slides.length) { root.classList.add('deck-ready'); return; }

  /* ---- Mode ------------------------------------------------------------- */
  var params;
  try { params = new URLSearchParams(location.search); } catch (e) { params = { get: function () { return null; } }; }
  var embedKind = params.get('deck-embed') || (/^deck-embed-/.test(window.name) ? window.name.replace('deck-embed-', '') : '');
  var isEmbed = !!embedKind && window.parent !== window;
  var isPresenter = !isEmbed && (window.name === 'deck-presenter' || /(^#|&)presenter\b/.test(location.hash));
  var isMain = !isEmbed && !isPresenter;
  root.classList.add(isEmbed ? 'deck-embed' : isPresenter ? 'deck-presenter' : 'deck-main');

  var reducedMotion = false;
  try { reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
  if (reducedMotion) root.classList.add('deck-no-motion');

  /* ---- Small helpers ---------------------------------------------------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function meta(name) {
    var m = document.querySelector('meta[name="deck:' + name + '"]');
    return m ? m.getAttribute('content') || '' : '';
  }
  function fire(slide, type, detail) {
    try { slide.dispatchEvent(new CustomEvent(type, { bubbles: true, detail: detail || {} })); }
    catch (e) { console.error('[deck] ' + type + ' handler failed on slide ' + slide.dataset.slideNumber, e); }
  }
  function token(name, node) {
    return getComputedStyle(node || deckEl).getPropertyValue(name).trim();
  }
  function toMs(v, node) {
    if (typeof v === 'number') return v;
    if (v == null) return 0;
    var s = String(v).trim();
    if (s.indexOf('--') === 0) s = token(s, node);
    var m = /^(-?[\d.]+)(ms|s)?$/.exec(s);
    if (!m) return 0;
    return parseFloat(m[1]) * (m[2] === 's' ? 1000 : 1);
  }
  function globalRest() { return root.classList.contains('deck-rest'); }
  function isRest(slide) {
    return globalRest() || reducedMotion || !!(slide && slide.classList.contains('is-rest'));
  }
  function track(slide, fn) {
    if (!slide) return;
    (slide._deckCleanups || (slide._deckCleanups = [])).push(fn);
  }
  function cleanup(slide) {
    var list = slide._deckCleanups;
    if (!list) return;
    slide._deckCleanups = [];
    list.forEach(function (fn) { try { fn(); } catch (e) {} });
  }

  /* ---- Per-slide scoped CSS -------------------------------------------- */
  function skipString(s, i) {
    var q = s[i];
    for (var j = i + 1; j < s.length; j++) {
      if (s[j] === '\\') { j++; continue; }
      if (s[j] === q) return j;
    }
    return s.length - 1;
  }
  // Wraps a slide's own CSS in a nesting block so it can only reach that
  // slide. Inside it, `&` is the slide itself. @keyframes stay global.
  function scopeCss(css, sel) {
    css = css.replace(/\/\*[\s\S]*?\*\//g, '');
    var hoist = /@(?:-webkit-)?(?:keyframes|font-face|property)\b/y;
    var drop = /@(?:import|charset|namespace)\b/y;
    var hoisted = '', body = '', i = 0, n = css.length, depth = 0;
    while (i < n) {
      var ch = css[i];
      if (depth === 0 && ch === '@') {
        hoist.lastIndex = i; drop.lastIndex = i;
        var isHoist = hoist.test(css), isDrop = !isHoist && drop.test(css);
        if (isHoist || isDrop) {
          var d = 0, end = n;
          for (var j = i; j < n; j++) {
            var c = css[j];
            if (c === '"' || c === "'") { j = skipString(css, j); continue; }
            if (c === '{') d++;
            else if (c === '}') { d--; if (d === 0) { end = j + 1; break; } }
            else if (c === ';' && d === 0) { end = j + 1; break; }
          }
          if (isHoist) hoisted += css.slice(i, end) + '\n';
          i = end;
          continue;
        }
      }
      if (ch === '"' || ch === "'") {
        var k = skipString(css, i);
        body += css.slice(i, k + 1); i = k + 1;
        continue;
      }
      if (ch === '{') depth++; else if (ch === '}') depth--;
      body += ch; i++;
    }
    return hoisted + sel + '{' + body + '}';
  }

  /* ---- Slide preparation ------------------------------------------------ */
  var footerText = meta('footer');
  var seenIds = {};
  slides.forEach(function (slide, n) {
    var id = slide.id && !seenIds[slide.id] ? slide.id : 's' + (n + 1);
    seenIds[id] = true;
    slide.dataset.slideId = id;
    slide.dataset.slideNumber = String(n + 1);
    // Position of every authored element (slide number, then child indexes).
    // Edit mode uses it to name an element; anything added later has none.
    (function stamp(node, path) {
      node._deckPath = path;
      for (var c = 0; c < node.children.length; c++) stamp(node.children[c], path + '.' + (c + 1));
    })(slide, String(n + 1));
    slide.style.setProperty('--slide-number', String(n + 1));
    slide.setAttribute('aria-roledescription', 'slide');
    slide.setAttribute('aria-hidden', 'true');

    Array.prototype.forEach.call(slide.querySelectorAll('style[data-slide-scope]'), function (st) {
      if (st._deckScoped) return;
      st.textContent = scopeCss(st.textContent, '.deck .slide[data-slide-id="' + id + '"]');
      st._deckScoped = true;
    });

    // Step reveals
    var stepEls = Array.prototype.slice.call(slide.querySelectorAll('[data-step]'));
    var explicitMax = 0;
    stepEls.forEach(function (s) {
      var v = parseInt(s.getAttribute('data-step'), 10);
      if (v > 0 && v > explicitMax) explicitMax = v;
    });
    var auto = explicitMax;
    stepEls.forEach(function (s) {
      var v = parseInt(s.getAttribute('data-step'), 10);
      s._deckStep = v > 0 ? v : ++auto;
    });
    slide._deckStepEls = stepEls;
    slide._deckSteps = Math.max(auto, parseInt(slide.getAttribute('data-steps'), 10) || 0);

    // Animation helpers
    Array.prototype.forEach.call(slide.querySelectorAll('[data-stagger]'), function (parent) {
      Array.prototype.forEach.call(parent.children, function (child, i) {
        if (!child.style.getPropertyValue('--i')) child.style.setProperty('--i', String(i));
      });
    });
    Array.prototype.forEach.call(slide.querySelectorAll('[data-anim="draw"]'), function (node) {
      var shapes = typeof node.getTotalLength === 'function' ? [node] :
        node.querySelectorAll('path, line, polyline, polygon, circle, ellipse, rect');
      Array.prototype.forEach.call(shapes, function (sh) {
        if (!sh.hasAttribute('pathLength')) sh.setAttribute('pathLength', '1');
      });
    });
    Array.prototype.forEach.call(slide.querySelectorAll('[data-count]'), function (node) {
      node._deckCountText = node.textContent;
    });

    // Footer (part of the frame; layouts decide where it is shown)
    if (!slide.querySelector(':scope > .slide-footer')) {
      var f = el('footer', 'slide-footer');
      f.appendChild(el('span', 'slide-footer-logo'));
      f.appendChild(el('span', 'slide-footer-text', footerText));
      f.appendChild(el('span', 'slide-number', String(n + 1)));
      f.setAttribute('aria-hidden', 'true');
      slide.appendChild(f);
    }
  });

  /* ---- Count-up helper -------------------------------------------------- */
  function runCount(node) {
    var slide = node.closest('.slide');
    var text = node._deckCountText;
    var m = /-?\d[\d,]*(?:\.\d+)?/.exec(text || '');
    if (!m || isRest(slide)) return;
    var raw = m[0];
    var target = parseFloat(raw.replace(/,/g, ''));
    var decimals = (raw.split('.')[1] || '').length;
    var commas = raw.indexOf(',') >= 0;
    var from = parseFloat(node.getAttribute('data-count-from')) || 0;
    var dur = toMs(node.getAttribute('data-count-duration') || '--dur-count', node) || toMs('--dur-slow', node) * 1.5 || 1200;
    var pre = text.slice(0, m.index), post = text.slice(m.index + raw.length);
    function fmt(v) {
      var s = v.toFixed(decimals);
      if (commas) {
        var parts = s.split('.');
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        s = parts.join('.');
      }
      return pre + s + post;
    }
    var start = null, id = 0, done = false;
    function frame(t) {
      if (done) return;
      if (start === null) start = t;
      var p = Math.min(1, (t - start) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      node.textContent = p >= 1 ? text : fmt(from + (target - from) * eased);
      if (p < 1) id = requestAnimationFrame(frame);
    }
    node.textContent = fmt(from);
    id = requestAnimationFrame(frame);
    track(slide, function () { done = true; cancelAnimationFrame(id); node.textContent = text; });
  }
  function runCounts(slide, stepNumber) {
    Array.prototype.forEach.call(slide.querySelectorAll('[data-count]'), function (node) {
      var holder = node.closest('[data-step]');
      if (stepNumber == null ? !holder : (holder && holder._deckStep === stepNumber)) runCount(node);
    });
  }

  /* ---- Typing helper ------------------------------------------------------
     data-type types an element's text when its slide (or step) appears.
     Every character keeps its place while hidden, so nothing reflows as the
     text arrives. Several typed elements on a slide take turns, in source
     order. At rest the whole text simply shows.                             */
  function typeChars(node) {
    if (node._deckTypeChars) return node._deckTypeChars;
    var keepSpace = /^pre/.test(getComputedStyle(node).whiteSpace);
    var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
    var texts = [], t, chars = [];
    while ((t = walker.nextNode())) texts.push(t);
    texts.forEach(function (tn) {
      var parent = tn.parentNode;
      if (!parent || (parent.closest && parent.closest('svg, script, style'))) return;
      var value = keepSpace ? tn.nodeValue : tn.nodeValue.replace(/\s+/g, ' ');
      if (!value.trim() && !keepSpace) return;
      var frag = document.createDocumentFragment();
      Array.from(value).forEach(function (ch) {
        var s = el('span', 'deck-type-ch', ch);
        frag.appendChild(s);
        chars.push(s);
      });
      parent.replaceChild(frag, tn);
    });
    node._deckTypeChars = chars;
    return chars;
  }
  function typeReset(node) {
    node.classList.remove('deck-typing');
    (node._deckTypeChars || []).forEach(function (c) { c.classList.remove('is-typed', 'is-caret'); });
  }
  function runTypes(slide, stepNumber) {
    if (isRest(slide)) return;
    var nodes = Array.prototype.filter.call(slide.querySelectorAll('[data-type]'), function (node) {
      var holder = node.closest('[data-step]');
      return stepNumber == null ? !holder : (holder && holder._deckStep === stepNumber);
    });
    if (!nodes.length) return;
    var stopped = false, id = 0, timer = 0;
    nodes.forEach(function (node) { typeChars(node); typeReset(node); node.classList.add('deck-typing'); });
    function typeOne(at) {
      if (stopped || at >= nodes.length) return;
      var node = nodes[at], chars = node._deckTypeChars;
      var perSecond = parseFloat(node.getAttribute('data-type-speed')) || 42;
      var wait = node.hasAttribute('data-type-delay') ? toMs(node.getAttribute('data-type-delay'), node) :
        toMs(at === 0 && stepNumber == null ? '--dur-base' : '--dur-fast', node);
      var start = null, shownChars = 0;
      function frame(t) {
        if (stopped) return;
        if (start === null) start = t;
        var want = Math.max(0, Math.min(chars.length, Math.floor((t - start) * perSecond / 1000)));
        if (want > shownChars) {
          if (shownChars) chars[shownChars - 1].classList.remove('is-caret');
          while (shownChars < want) chars[shownChars++].classList.add('is-typed');
          chars[shownChars - 1].classList.add('is-caret');
        }
        if (shownChars < chars.length) { id = requestAnimationFrame(frame); return; }
        node.classList.remove('deck-typing');
        var last = chars[chars.length - 1];
        if (last && !node.hasAttribute('data-type-caret')) last.classList.remove('is-caret');
        try { node.dispatchEvent(new CustomEvent('deck:typed', { bubbles: true })); }
        catch (e) { console.error('[deck] deck:typed handler failed', e); }
        typeOne(at + 1);
      }
      timer = setTimeout(function () { id = requestAnimationFrame(frame); }, wait);
    }
    typeOne(0);
    track(slide, function () {
      stopped = true;
      cancelAnimationFrame(id);
      clearTimeout(timer);
      nodes.forEach(typeReset);
    });
  }

  /* ---- State ------------------------------------------------------------ */
  var cur = -1, step = 0;          // logical position
  var shown = -1;                  // slide currently on the stage
  var blanked = false;
  // The progress bar is off unless the deck asks for it with
  // data-progress="on"; L shows or hides it while presenting.
  var progressOn = deckEl.getAttribute('data-progress') === 'on';
  var peer = null;                 // the other window (presenter <-> audience)
  var editOn = false;              // edit mode: pick an element to reference

  function stepsOf(i) { return slides[i] ? slides[i]._deckSteps : 0; }

  function applySteps(slide, s, direction, silent) {
    slide._deckStepEls.forEach(function (node) {
      node.classList.toggle('is-step-shown', node._deckStep <= s);
      node.classList.toggle('is-step-current', node._deckStep === s);
    });
    slide.dataset.stepIndex = String(s);
    if (!silent) fire(slide, 'deck:step', { step: s, total: slide._deckSteps, direction: direction || 0 });
  }

  function leave(slide) {
    cleanup(slide);
    slide.classList.remove('is-active', 'is-entered', 'is-rest');
    slide.setAttribute('aria-hidden', 'true');
    fire(slide, 'deck:leave');
  }

  var leavingTimer = 0;
  function renderStage(i, s, opts) {
    var slide = slides[i];
    var changed = i !== shown;
    if (changed) {
      var old = slides[shown];
      if (old) {
        leave(old);
        var fade = toMs('--dur-slide');
        if (fade > 0 && !isRest(slide) && !opts.rest) {
          old.classList.add('is-leaving');
          clearTimeout(leavingTimer);
          leavingTimer = setTimeout(function () {
            slides.forEach(function (x) { x.classList.remove('is-leaving'); });
          }, fade + 30);
        }
      }
      shown = i;
      var restEntry = !!opts.rest || opts.direction === -1 || globalRest() || editOn;
      var rest = restEntry || reducedMotion;
      slide.classList.toggle('is-rest', restEntry);
      slide.classList.add('is-active');
      slide.setAttribute('aria-hidden', 'false');
      void slide.offsetWidth;
      slide.classList.add('is-entered');
      applySteps(slide, s, opts.direction, true);
      if (rest) fire(slide, 'deck:rest', { step: s, total: slide._deckSteps });
      else {
        fire(slide, 'deck:enter', { step: s, total: slide._deckSteps, direction: opts.direction || 0 });
        runCounts(slide, null);
        runTypes(slide, null);
      }
      fire(slide, 'deck:step', { step: s, total: slide._deckSteps, direction: opts.direction || 0 });
    } else {
      var before = parseInt(slide.dataset.stepIndex, 10) || 0;
      applySteps(slide, s, opts.direction);
      if (s > before && !isRest(slide)) {
        for (var k = before + 1; k <= s; k++) { runCounts(slide, k); runTypes(slide, k); }
      }
    }
    deckEl.style.setProperty('--deck-progress', slides.length > 1 ? String(i / (slides.length - 1)) : '1');
    deckEl.classList.toggle('is-chrome-hidden', slide.getAttribute('data-progress') === 'off');
    updateNotesOverlay();
  }

  function go(i, s, opts) {
    opts = opts || {};
    i = Math.max(0, Math.min(slides.length - 1, i | 0));
    var total = stepsOf(i);
    s = (s === -1 || globalRest() || editOn || s == null && opts.direction === -1) ? total : Math.max(0, Math.min(total, s | 0));
    if (i === cur && s === step && !opts.force) return;
    var direction = opts.direction || (i > cur ? 1 : i < cur ? -1 : s > step ? 1 : -1);
    if (opts.direction === 0) direction = 0;
    cur = i; step = s;
    var ropts = { direction: direction, rest: !!opts.rest };
    if (isPresenter) renderPresenter(ropts);
    else renderStage(i, s, ropts);
    if (isMain) writeHash();
    if (!opts.remote) sendState();
  }
  function next() {
    if (step < stepsOf(cur)) go(cur, step + 1, { direction: 1 });
    else if (cur < slides.length - 1) go(cur + 1, 0, { direction: 1 });
  }
  function prev() {
    if (step > 0) go(cur, step - 1, { direction: -1 });
    else if (cur > 0) go(cur - 1, -1, { direction: -1 });
  }

  /* ---- Hash (deep links, reload) ---------------------------------------- */
  function readHash() {
    var h = decodeURIComponent((location.hash || '').replace(/^#/, '')).split('&')[0];
    if (!h || h === 'presenter') return 0;
    if (/^\d+$/.test(h)) return Math.max(0, Math.min(slides.length - 1, parseInt(h, 10) - 1));
    for (var i = 0; i < slides.length; i++) if (slides[i].id === h) return i;
    return 0;
  }
  function writeHash() {
    var h = '#' + (cur + 1);
    if (location.hash === h) return;
    try { history.replaceState(null, '', h); } catch (e) { try { location.hash = h; } catch (e2) {} }
  }

  /* ---- Scaling ---------------------------------------------------------- */
  function fit() {
    if (root.classList.contains('deck-overview')) { layoutOverview(); return; }
    var scale = Math.min(window.innerWidth / W, window.innerHeight / H);
    root.style.setProperty('--deck-scale', String(scale > 0 ? scale : 1));
  }

  /* ---- Resting state (print, overview) ---------------------------------- */
  function setRest(on) {
    if (on === globalRest()) return;
    root.classList.toggle('deck-rest', on);
    slides.forEach(function (slide, i) {
      if (on) {
        cleanup(slide);
        slide.classList.add('is-entered');
        applySteps(slide, slide._deckSteps, 0, true);
        fire(slide, 'deck:rest', { step: slide._deckSteps, total: slide._deckSteps });
        fire(slide, 'deck:step', { step: slide._deckSteps, total: slide._deckSteps, direction: 0 });
      } else if (i === shown) {
        slide.classList.add('is-rest');
        applySteps(slide, step, 0);
      } else {
        slide.classList.remove('is-entered');
        applySteps(slide, 0, 0, true);
      }
    });
  }

  /* ---- Messaging between windows ---------------------------------------- */
  function post(win, msg) {
    if (!win) return;
    msg[KEY] = 1;
    try { if (!win.closed) win.postMessage(msg, '*'); } catch (e) {}
  }
  function sendState() {
    if (isEmbed) return;
    post(peer, { t: 'state', i: cur, s: step, blank: blanked, progress: progressOn, variant: root.dataset.variant || '' });
  }
  function setVariant(v, remote) {
    if (!v || v === root.dataset.variant) return;
    root.dataset.variant = v;
    if (isPresenter) frames.forEach(function (f) { post(f.contentWindow, { t: 'variant', variant: v }); });
    if (!remote) sendState();
  }
  function cycleVariant() {
    var list = (root.dataset.variants || '').split(/\s+/).filter(Boolean);
    if (list.length < 2) { toast('This theme has a single variant.'); return; }
    var at = list.indexOf(root.dataset.variant);
    setVariant(list[(at + 1) % list.length]);
  }
  function setBlank(on, remote) {
    blanked = !!on;
    if (isMain) root.classList.toggle('deck-blanked', blanked);
    if (isPresenter && pv) pv.status.textContent = blanked ? 'Audience screen is blank' : linkText();
    if (!remote) sendState();
  }
  function setProgress(on, remote) {
    progressOn = !!on;
    deckEl.classList.toggle('is-progress-on', progressOn);
    if (!remote) {
      // The audience sees the bar itself; the presenter window does not.
      if (isPresenter) toast(progressOn ? 'Progress bar shown on the audience screen' : 'Progress bar hidden');
      sendState();
    }
  }

  var lastPong = 0, gotState = false;
  window.addEventListener('message', function (e) {
    var d = e.data;
    if (!d || d[KEY] !== 1) return;
    if (isEmbed) {
      if (e.source !== window.parent) return;
      if (d.t === 'show') go(d.i, d.s, { rest: !!d.rest, remote: true, force: !!d.rest, direction: d.rest ? 0 : undefined });
      else if (d.t === 'variant') setVariant(d.variant, true);
      return;
    }
    if (d.t === 'ready' && isPresenter) { renderPresenter({}); return; }
    if (d.t === 'ping' && isMain) {
      var fresh = peer !== e.source;
      peer = e.source;
      post(peer, { t: 'pong' });
      if (fresh || d.want) sendState();
      return;
    }
    if (d.t === 'pong' && isPresenter) { lastPong = Date.now(); updateLink(); return; }
    if (d.t === 'state') {
      if (isMain && e.source !== peer) peer = e.source;
      if (isPresenter) { lastPong = Date.now(); gotState = true; updateLink(); }
      if (d.variant) setVariant(d.variant, true);
      if (typeof d.blank === 'boolean' && d.blank !== blanked) setBlank(d.blank, true);
      if (typeof d.progress === 'boolean' && d.progress !== progressOn) setProgress(d.progress, true);
      go(d.i, d.s, { remote: true });
    }
  });

  // Shown inside another page, such as an AI assistant's preview pane. Previews
  // usually cannot open a second window or print, so those two say so.
  var framed = false;
  try { framed = window.self !== window.top; } catch (e) { framed = true; }
  var PREVIEW_HINT = ' does not work in a preview. Download this file and open it in your browser.';

  function openPresenter() {
    var url = location.href.replace(/#.*$/, '') + '#presenter';
    var w = null;
    try { w = window.open(url, 'deck-presenter', 'popup=yes,width=1180,height=720'); } catch (e) {}
    if (!w) {
      toast(framed ? 'The presenter window' + PREVIEW_HINT :
        'The presenter window was blocked. Allow pop-ups for this page, then press S again.');
      return;
    }
    peer = w;
    try { w.focus(); } catch (e) {}
  }

  /* ---- UI layer --------------------------------------------------------- */
  var ui = el('div', 'deck-ui');
  var toastEl = el('div', 'deck-toast');
  toastEl.setAttribute('role', 'status');
  ui.appendChild(toastEl);
  var toastTimer = 0;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-visible'); }, 4200);
  }

  function notesHtml(i) {
    var a = slides[i] && slides[i].querySelector(':scope > aside.notes');
    return a ? a.innerHTML.trim() : '';
  }
  function fillNotes(target, i) {
    var html = notesHtml(i);
    target.innerHTML = html || '<p class="deck-notes-empty">No notes for this slide.</p>';
  }

  var notesOverlay, notesBody;
  function updateNotesOverlay() {
    if (notesBody && root.classList.contains('deck-show-notes')) fillNotes(notesBody, cur);
  }

  /* ---- Main window UI --------------------------------------------------- */
  var gotoEl, gotoBuf = '';
  if (isMain) {
    ui.appendChild(el('div', 'deck-blank'));
    notesOverlay = el('div', 'deck-notes-overlay');
    notesOverlay.appendChild(el('h6', '', 'Speaker notes'));
    notesBody = el('div', 'deck-notes-body');
    notesOverlay.appendChild(notesBody);
    ui.appendChild(notesOverlay);
    gotoEl = el('div', 'deck-goto');
    ui.appendChild(gotoEl);
  }

  /* ---- Help panel: opens with ? or H from any state, in either window ---- */
  function toggleHelp(on) {
    root.classList.toggle('deck-show-help', on === undefined ? !root.classList.contains('deck-show-help') : on);
  }
  if (!isEmbed) {
    var help = el('div', 'deck-help');
    var keys = isMain ?
      '<dt><kbd>&rarr;</kbd> <kbd>Space</kbd> <kbd>PgDn</kbd></dt><dd>Next</dd>' +
      '<dt><kbd>&larr;</kbd> <kbd>PgUp</kbd></dt><dd>Back</dd>' +
      '<dt><kbd>F</kbd></dt><dd>Full screen</dd>' +
      '<dt><kbd>S</kbd></dt><dd>Presenter window with notes&nbsp;<span class="deck-help-star">*</span></dd>' +
      '<dt><kbd>N</kbd></dt><dd>Notes on this screen</dd>' +
      '<dt><kbd>O</kbd></dt><dd>Overview of all slides</dd>' +
      '<dt><kbd>B</kbd></dt><dd>Blank the screen</dd>' +
      '<dt><kbd>T</kbd></dt><dd>Switch light and dark</dd>' +
      '<dt><kbd>L</kbd></dt><dd>Show or hide the progress bar</dd>' +
      '<dt><kbd>Home</kbd> <kbd>End</kbd></dt><dd>First and last slide</dd>' +
      '<dt><kbd>12</kbd> <kbd>Enter</kbd></dt><dd>Jump to a slide number</dd>' +
      '<dt><kbd>P</kbd></dt><dd>Print or save as PDF&nbsp;<span class="deck-help-star">*</span></dd>' +
      '<dt><kbd>Shift</kbd> <kbd>P</kbd></dt><dd>Print slides with notes&nbsp;<span class="deck-help-star">*</span></dd>' +
      '<dt><kbd>E</kbd></dt><dd>Edit mode: pick an element to reference</dd>' +
      '<dt><kbd>&uarr;</kbd> <kbd>&darr;</kbd></dt><dd>In edit mode: wider or narrower pick</dd>' +
      '<dt><kbd>?</kbd> <kbd>H</kbd></dt><dd>Show or hide this panel</dd>'
      :
      '<dt><kbd>&rarr;</kbd> <kbd>Space</kbd> <kbd>PgDn</kbd></dt><dd>Next</dd>' +
      '<dt><kbd>&larr;</kbd> <kbd>PgUp</kbd></dt><dd>Back</dd>' +
      '<dt><kbd>Home</kbd> <kbd>End</kbd></dt><dd>First and last slide</dd>' +
      '<dt><kbd>12</kbd> <kbd>Enter</kbd></dt><dd>Jump to a slide number</dd>' +
      '<dt><kbd>B</kbd></dt><dd>Blank the audience screen</dd>' +
      '<dt><kbd>T</kbd></dt><dd>Switch light and dark</dd>' +
      '<dt><kbd>L</kbd></dt><dd>Show or hide the audience progress bar</dd>' +
      '<dt><kbd>F</kbd></dt><dd>Full screen for this window</dd>' +
      '<dt><kbd>?</kbd> <kbd>H</kbd></dt><dd>Show or hide this panel</dd>';
    help.innerHTML =
      '<div class="deck-help-panel" role="dialog" aria-label="Hotkeys">' +
      '<button type="button" class="deck-help-close" data-act="close" aria-label="Close">&times;</button>' +
      '<h2>Hotkeys</h2>' +
      '<dl class="deck-help-keys">' + keys + '</dl>' +
      (isMain ? '<p class="deck-help-note"><span class="deck-help-star">*</span> Works once you download this file and open it in your browser, not in an AI assistant&rsquo;s preview.</p>' :
        '<p class="deck-help-note">Notes, overview, print and edit mode are in the audience window.</p>') +
      '</div>';
    help.addEventListener('click', function (e) {
      if (e.target === help || e.target.closest('button[data-act="close"]')) toggleHelp(false);
    });
    ui.appendChild(help);
  }
  if (!isEmbed) document.body.appendChild(ui);

  function toggleFullscreen() {
    var d = document, e = root;
    var active = d.fullscreenElement || d.webkitFullscreenElement;
    try {
      if (active) (d.exitFullscreen || d.webkitExitFullscreen).call(d);
      else (e.requestFullscreen || e.webkitRequestFullscreen).call(e);
    } catch (err) { toast('Full screen is not available here.'); }
  }

  /* ---- Overview --------------------------------------------------------- */
  var ovSel = 0, ovCols = 4;
  function layoutOverview() {
    var w = window.innerWidth;
    ovCols = w >= 1500 ? 5 : w >= 1000 ? 4 : w >= 640 ? 3 : 2;
    var gap = 20, pad = 28 * 2 + 18;
    var zoom = (w - pad - gap * (ovCols - 1)) / ovCols / W;
    root.style.setProperty('--ov-cols', String(ovCols));
    root.style.setProperty('--ov-zoom', String(Math.max(0.05, zoom)));
  }
  function selectOverview(i) {
    ovSel = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach(function (s, n) { s.classList.toggle('is-ov-selected', n === ovSel); });
    try { slides[ovSel].scrollIntoView({ block: 'nearest' }); } catch (e) {}
  }
  function toggleOverview(target) {
    var on = !root.classList.contains('deck-overview');
    if (on) {
      setRest(true);
      root.classList.add('deck-overview');
      root.classList.remove('deck-show-notes');
      layoutOverview();
      selectOverview(cur);
    } else {
      root.classList.remove('deck-overview');
      slides.forEach(function (s) { s.classList.remove('is-ov-selected'); });
      setRest(false);
      fit();
      window.scrollTo(0, 0);
      var to = target == null ? cur : target;
      if (to !== cur) go(to, 0, { direction: 1 });
    }
  }

  /* ---- Print ------------------------------------------------------------ */
  var notesPages = [];
  function endPrintNotes() {
    if (!root.classList.contains('deck-print-notes')) return;
    notesPages.forEach(function (p) {
      p.page.parentNode.insertBefore(p.slide, p.page);
      p.page.parentNode.removeChild(p.page);
    });
    notesPages = [];
    root.classList.remove('deck-print-notes');
    var st = document.getElementById('deck-print-page');
    if (st) st.parentNode.removeChild(st);
  }
  function printNotes(opts) {
    opts = opts || {};
    endPrintNotes();
    var letter = /^(en-US|en-CA|es-US|es-MX|fr-CA)\b/i.test(navigator.language || 'en-US');
    var w = letter ? 720 : 703;
    var st = el('style');
    st.id = 'deck-print-page';
    // The page supplies its own header and footer: the print date, the deck's
    // title and page numbers. Browsers that support this (Chrome and Edge) then
    // leave out their own, which would also print the file's path.
    var quote = function (text) { return '"' + String(text).replace(/[\\"]/g, '\\$&').replace(/\s+/g, ' ') + '"'; };
    var when = '';
    try { when = new Date().toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }); } catch (e) {}
    var edge = 'font: 8pt system-ui, sans-serif; color: #555;';
    st.textContent = '@page { size: ' + (letter ? '8.5in 11in' : '210mm 297mm') + '; margin: ' + (letter ? '0.5in' : '12mm') + ';' +
      ' @top-left { content: ' + quote(when) + '; ' + edge + ' }' +
      ' @top-center { content: ' + quote(document.title) + '; ' + edge + ' }' +
      ' @bottom-left { content: ""; }' +
      ' @bottom-right { content: counter(page) " / " counter(pages); ' + edge + ' } }';
    document.head.appendChild(st);
    root.style.setProperty('--np-w', w + 'px');
    root.style.setProperty('--np-scale', String(w / W));
    root.classList.add('deck-print-notes');
    setRest(true);
    slides.forEach(function (slide, i) {
      var page = el('div', 'deck-np-page');
      var title = slide.querySelector('.slide-title, h1, h2');
      page.appendChild(el('div', 'deck-np-head', 'Slide ' + (i + 1) + ' of ' + slides.length +
        (title ? '  -  ' + title.textContent.replace(/\s+/g, ' ').trim() : '')));
      var thumb = el('div', 'deck-np-thumb');
      slide.parentNode.insertBefore(page, slide);
      thumb.appendChild(slide);
      page.appendChild(thumb);
      var notes = el('div', 'deck-np-notes');
      notes.innerHTML = notesHtml(i) || '';
      page.appendChild(notes);
      notesPages.push({ page: page, slide: slide });
    });
    if (opts.print !== false) window.print();
  }
  function printDeck(withNotes) {
    if (framed) {
      toast((withNotes ? 'Printing slides with notes' : 'Saving the slides as a PDF') + PREVIEW_HINT);
      if (withNotes) return;               // the notes layout is undone after printing, which a preview never reports
    }
    if (withNotes) printNotes(); else window.print();
  }
  window.addEventListener('beforeprint', function () {
    if (root.classList.contains('deck-overview')) toggleOverview();
    setRest(true);
  });
  window.addEventListener('afterprint', function () {
    endPrintNotes();
    setRest(false);
  });

  /* ---- Presenter view --------------------------------------------------- */
  var pv = null, frames = [];
  var timerStart = 0, timerAcc = 0, timerOn = false;
  function fmtTime(ms) {
    var t = Math.floor(ms / 1000), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }
  function linkText() {
    if (!window.opener) return 'Not linked to an audience window';
    return Date.now() - lastPong < 5000 ? 'Linked to the audience window' : 'Looking for the audience window';
  }
  function updateLink() {
    if (!pv || blanked) return;
    pv.status.textContent = linkText();
    pv.status.classList.toggle('is-linked', !!window.opener && Date.now() - lastPong < 5000);
  }
  function embedUrl(kind) {
    var u = location.href.replace(/#.*$/, '');
    return u + (u.indexOf('?') >= 0 ? '&' : '?') + 'deck-embed=' + kind;
  }
  function buildPresenter() {
    document.title = 'Presenter - ' + document.title;
    var wrap = el('div', 'deck-pv');
    var top = el('div', 'deck-pv-top');
    var count = el('span', 'deck-pv-count');
    var stepEl = el('span', 'deck-pv-step');
    var status = el('span', 'deck-pv-status');
    var timer = el('span', 'deck-pv-timer', '0:00');
    timer.title = 'Click to pause or resume';
    var clock = el('span', 'deck-pv-clock');
    top.appendChild(count); top.appendChild(stepEl); top.appendChild(status);
    top.appendChild(el('span', 'deck-pv-spacer'));
    top.appendChild(timer); top.appendChild(clock);

    function frameBox(kind, label) {
      var box = el('div', 'deck-pv-frame');
      var f = document.createElement('iframe');
      f.name = 'deck-embed-' + kind;
      f.title = label;
      f.setAttribute('tabindex', '-1');
      f.setAttribute('aria-hidden', 'true');
      f.src = embedUrl(kind);
      box.appendChild(f);
      box.appendChild(el('div', 'deck-pv-end', 'End of deck'));
      frames.push(f);
      return box;
    }
    var main = el('div', 'deck-pv-main');
    var curBox = frameBox('current', 'Current slide');
    main.appendChild(curBox);
    var side = el('div', 'deck-pv-side');
    side.appendChild(el('div', 'deck-pv-label', 'Next'));
    var nextBox = frameBox('next', 'Next slide');
    side.appendChild(nextBox);
    side.appendChild(el('div', 'deck-pv-label', 'Notes'));
    var notes = el('div', 'deck-pv-notes deck-notes-body');
    side.appendChild(notes);

    var bottom = el('div', 'deck-pv-bottom');
    function btn(label, fn) { var b = el('button', '', label); b.type = 'button'; b.addEventListener('click', function () { fn(); b.blur(); }); bottom.appendChild(b); return b; }
    btn('Back', prev); btn('Next', next);
    btn('Reset timer', function () { timerAcc = 0; timerStart = Date.now(); tick(); });
    var size = 20;
    btn('Smaller notes', function () { size = Math.max(14, size - 2); wrap.style.setProperty('--pv-notes-size', size + 'px'); });
    btn('Larger notes', function () { size = Math.min(40, size + 2); wrap.style.setProperty('--pv-notes-size', size + 'px'); });
    bottom.appendChild(el('span', '', 'Arrow keys and clickers work in either window. Press ? for the shortcuts.'));

    wrap.appendChild(top); wrap.appendChild(main); wrap.appendChild(side); wrap.appendChild(bottom);
    ui.appendChild(wrap);

    timer.addEventListener('click', function () {
      if (timerOn) { timerAcc += Date.now() - timerStart; timerOn = false; }
      else { timerStart = Date.now(); timerOn = true; }
      timer.classList.toggle('is-paused', !timerOn);
    });
    function tick() {
      timer.textContent = fmtTime(timerAcc + (timerOn ? Date.now() - timerStart : 0));
      var d = new Date();
      clock.textContent = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    setInterval(tick, 500);
    tick();
    pv = { count: count, step: stepEl, status: status, notes: notes, nextBox: nextBox, tick: tick };

    peer = window.opener || null;
    function ping() { post(peer, { t: 'ping', want: !gotState }); updateLink(); }
    setInterval(ping, 2000);
    ping();
  }
  var pvFirst = true;
  function renderPresenter(ropts) {
    if (!pv) return;
    pv.count.textContent = (cur + 1) + ' / ' + slides.length;
    var total = stepsOf(cur);
    pv.step.textContent = total ? 'Step ' + step + ' of ' + total : '';
    if (frames[0]) post(frames[0].contentWindow, { t: 'show', i: cur, s: step });
    var hasNext = cur + 1 < slides.length;
    pv.nextBox.classList.toggle('is-end', !hasNext);
    if (hasNext && frames[1]) post(frames[1].contentWindow, { t: 'show', i: cur + 1, s: -1, rest: true });
    fillNotes(pv.notes, cur);
    pv.notes.scrollTop = 0;
    if (!pvFirst && !timerOn && timerAcc === 0 && ropts && ropts.direction) { timerStart = Date.now(); timerOn = true; }
    pvFirst = false;
  }

  /* ---- Input ------------------------------------------------------------ */
  var INTERACTIVE = 'a[href], button, input, select, textarea, summary, label, video, audio, details, [contenteditable], [data-interactive], [data-no-advance]';

  function showGoto() {
    if (!gotoEl) return;
    gotoEl.textContent = 'Go to slide ' + gotoBuf;
    gotoEl.classList.toggle('is-visible', !!gotoBuf);
  }

  function onKey(e) {
    if (e.defaultPrevented) return;
    var t = e.target;
    if (t && t.nodeType === 1 && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    var k = e.key;

    // Help works from every state (edit mode, overview, the presenter window)
    // and is tested before the modifier check, because on some keyboard
    // layouts "?" is typed with AltGr, which reports as Ctrl+Alt.
    var plain = !e.altKey && !e.ctrlKey && !e.metaKey;
    var altGr = e.ctrlKey && e.altKey && !e.metaKey;
    var helpKey = (k === '?' && (plain || altGr)) || (plain && e.shiftKey && e.code === 'Slash') || (plain && (k === 'h' || k === 'H'));
    if (helpKey && !(isMain && blanked)) { toggleHelp(); e.preventDefault(); return; }
    if (!plain) return;

    if (isMain && blanked) { setBlank(false); e.preventDefault(); return; }
    if (root.classList.contains('deck-show-help')) {
      if (k === 'Escape') { toggleHelp(false); e.preventDefault(); }
      return;
    }
    if (root.classList.contains('deck-overview')) {
      var handled = true;
      if (k === 'ArrowRight') selectOverview(ovSel + 1);
      else if (k === 'ArrowLeft') selectOverview(ovSel - 1);
      else if (k === 'ArrowDown') selectOverview(ovSel + ovCols);
      else if (k === 'ArrowUp') selectOverview(ovSel - ovCols);
      else if (k === 'Home') selectOverview(0);
      else if (k === 'End') selectOverview(slides.length - 1);
      else if (k === 'Enter' || k === ' ') toggleOverview(ovSel);
      else if (k === 'Escape' || k === 'o' || k === 'O' || k === 'g' || k === 'G') toggleOverview();
      else handled = false;
      if (handled) e.preventDefault();
      return;
    }
    if (editOn) {
      var used = true;
      if (k === 'Escape' || k === 'e' || k === 'E') setEdit(false);
      else if (k === 'ArrowUp') widenPick();
      else if (k === 'ArrowDown') narrowPick();
      else if (k === 'Enter') copyPick();
      else if (k === 'ArrowRight' || k === 'PageDown' || k === ' ') { if (cur < slides.length - 1) go(cur + 1, -1, { rest: true }); clearPick(); }
      else if (k === 'ArrowLeft' || k === 'PageUp') { if (cur > 0) go(cur - 1, -1, { rest: true }); clearPick(); }
      else used = false;
      if (used) e.preventDefault();
      return;
    }
    if (/^\d$/.test(k)) { gotoBuf = (gotoBuf + k).slice(0, 4); showGoto(); e.preventDefault(); return; }
    if (gotoBuf) {
      var n = parseInt(gotoBuf, 10);
      gotoBuf = ''; showGoto();
      if (k === 'Enter') { if (n >= 1) go(n - 1, 0, { direction: 1 }); e.preventDefault(); return; }
      if (k === 'Escape' || k === 'Backspace') { e.preventDefault(); return; }
    }

    var done = true;
    switch (k) {
      case 'ArrowRight': case 'ArrowDown': case 'PageDown': case 'Enter': next(); break;
      case ' ': case 'Spacebar': if (e.shiftKey) prev(); else next(); break;
      case 'ArrowLeft': case 'ArrowUp': case 'PageUp': case 'Backspace': prev(); break;
      case 'Home': go(0, 0, { direction: 1 }); break;
      case 'End': go(slides.length - 1, 0, { direction: 1 }); break;
      case 'f': case 'F': toggleFullscreen(); break;
      case 'b': case 'B': case '.': setBlank(!blanked); break;
      case 't': case 'T': cycleVariant(); break;
      case 'l': case 'L': setProgress(!progressOn); break;
      case 's': case 'S': if (isMain) openPresenter(); else done = false; break;
      case 'n': case 'N':
        if (isMain) { root.classList.toggle('deck-show-notes'); updateNotesOverlay(); } else done = false;
        break;
      case 'o': case 'O': case 'g': case 'G': if (isMain) toggleOverview(); else done = false; break;
      case 'Escape':
        if (isMain && !(document.fullscreenElement || document.webkitFullscreenElement)) toggleOverview(); else done = false;
        break;
      case 'p': case 'P':
        if (isMain) printDeck(e.shiftKey); else done = false;
        break;
      case 'e': case 'E': if (isMain) setEdit(true); else done = false; break;
      default: done = false;
    }
    if (done) e.preventDefault();
  }

  if (!isEmbed) {
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', fit);
  } else {
    window.addEventListener('resize', fit);
  }

  if (isMain) {
    deckEl.addEventListener('click', function (e) {
      if (e.button) return;
      if (root.classList.contains('deck-overview')) {
        var s = e.target.closest('.slide');
        if (s) toggleOverview(slides.indexOf(s));
        return;
      }
      if (e.target.closest(INTERACTIVE)) return;
      var sel = window.getSelection && window.getSelection();
      if (sel && String(sel).length) return;
      next();
    });
    var tx = 0, ty = 0, tt = 0;
    document.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1) { tt = 0; return; }
      tx = e.touches[0].clientX; ty = e.touches[0].clientY; tt = Date.now();
    }, { passive: true });
    document.addEventListener('touchend', function (e) {
      if (!tt || root.classList.contains('deck-overview')) return;
      var c = e.changedTouches[0], dx = c.clientX - tx, dy = c.clientY - ty;
      if (Date.now() - tt < 800 && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        if (dx < 0) next(); else prev();
        e.preventDefault();
      }
      tt = 0;
    });
    window.addEventListener('hashchange', function () {
      var i = readHash();
      if (i !== cur) go(i, 0, { direction: 1 });
    });
    var idle = 0;
    document.addEventListener('mousemove', function () {
      root.classList.remove('deck-hide-cursor');
      clearTimeout(idle);
      idle = setTimeout(function () {
        if (document.fullscreenElement || document.webkitFullscreenElement) root.classList.add('deck-hide-cursor');
      }, 2500);
    });
  }

  /* ---- Edit mode: pick an element, copy a reference to it ----------------
     A reference reads like  [slide 7 > card 2 > heading "Clickers and keys" @7.4.2.2]
     (with a real "›" between the parts). The words are for the person, the
     quoted text is a cross-check, and the trailing @path is the element's exact
     position in the source, which scripts/locate.py resolves to line numbers. */
  var NAMED = [
    ['slide-title', 'title'], ['slide-eyebrow', 'eyebrow'], ['slide-subtitle', 'subtitle'], ['slide-meta', 'meta line'],
    ['slide-body', 'body'], ['section-number', 'section number'],
    ['big-number-label', 'label'], ['big-number-context', 'context line'], ['big-number', 'big number'],
    ['stat-value', 'value'], ['stat-label', 'label'], ['stat-delta', 'delta'], ['stat', 'stat', 1],
    ['card', 'card', 1], ['col', 'column', 1],
    ['timeline-date', 'date'], ['timeline-title', 'title'], ['timeline-text', 'text'], ['timeline-item', 'timeline item', 1], ['timeline', 'timeline'],
    ['flow-step', 'step', 1], ['flow', 'process'], ['legend-item', 'legend item', 1], ['legend', 'legend'],
    ['chart-figure', 'chart'], ['chart-notes', 'chart notes'], ['chart-bar', 'bar', 1], ['chart-line', 'line', 1],
    ['chart-dot', 'dot', 1], ['chart-slice', 'slice', 1], ['chart-area', 'area'], ['chart-value', 'value label', 1],
    ['chart-category', 'category label', 1], ['chart-series-label', 'series label', 1], ['chart-grid', 'gridline', 1],
    ['chart-axis', 'axis'], ['chart', 'chart drawing'], ['diagram', 'diagram'], ['node', 'box', 1], ['edge', 'connector', 1],
    ['label', 'label', 1], ['quote-by', 'attribution'], ['quote-role', 'role'], ['quote', 'quote'],
    ['callout', 'callout', 1], ['panel', 'panel', 1], ['tag', 'tag', 1], ['icon-badge', 'icon badge'], ['icon', 'icon', 1],
    ['lede', 'lede'], ['source', 'source line'], ['slide-image', 'picture'], ['figure', 'figure'],
    ['next-steps', 'next steps'], ['table', 'table'], ['notes', 'notes']
  ];
  var TAGGED = {
    h1: ['heading', 1], h2: ['heading', 1], h3: ['heading', 1], h4: ['heading', 1], p: ['paragraph', 1], li: ['bullet', 1],
    ul: ['list'], ol: ['list'], img: ['image', 1], table: ['table'], tr: ['row', 1], td: ['cell', 1], th: ['cell', 1],
    blockquote: ['quote'], figure: ['figure'], figcaption: ['caption'], svg: ['graphic', 1], a: ['link', 1],
    pre: ['code block', 1], code: ['code', 1], strong: ['bold text', 1], b: ['bold text', 1], em: ['emphasis', 1],
    span: ['text', 1], div: ['block', 1], article: ['block', 1], g: ['group', 1], text: ['label', 1], rect: ['rectangle', 1],
    circle: ['circle', 1], path: ['shape', 1], line: ['line', 1], canvas: ['canvas', 1], video: ['video', 1]
  };
  var QUIET = { body: 1, block: 1, group: 1, list: 1, text: 1, graphic: 1, 'chart drawing': 1, thead: 1, tbody: 1, figure: 1 };

  function baseLabel(node) {
    var cl = node.classList;
    if (cl) for (var i = 0; i < NAMED.length; i++) if (cl.contains(NAMED[i][0])) return NAMED[i];
    var tag = node.tagName.toLowerCase();
    return TAGGED[tag] ? [tag, TAGGED[tag][0], TAGGED[tag][1]] : [tag, tag, 1];
  }
  function labelOf(node) {
    var base = baseLabel(node), name = base[1];
    if (!base[2] || !node.parentNode) return name;
    var same = Array.prototype.filter.call(node.parentNode.children, function (sib) {
      return sib._deckPath && baseLabel(sib)[1] === name;
    });
    return same.length > 1 ? name + ' ' + (same.indexOf(node) + 1) : name;
  }
  function textOf(node) {
    var out = '';
    (function walk(n) {
      for (var c = n.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3) out += c.nodeValue;
        else if (c.nodeType === 1) {
          var t = c.tagName.toLowerCase();
          if (t === 'style' || t === 'script' || t === 'title' || (t === 'aside' && c.classList.contains('notes'))) continue;
          out += ' ';
          walk(c);
          out += ' ';
        }
      }
    })(node);
    return out.replace(/\s+/g, ' ').trim();
  }
  function snippetOf(node) {
    var text;
    if (node.classList.contains('slide')) {
      var title = node.querySelector('.slide-title');
      text = title && title._deckPath ? textOf(title) : '';
    } else {
      var tip = null;
      for (var c = node.firstElementChild; c; c = c.nextElementSibling) {
        if (c.tagName.toLowerCase() === 'title') { tip = c; break; }
      }
      text = tip ? tip.textContent.replace(/\s+/g, ' ').trim() : textOf(node);
      if (!text) {
        var use = node.tagName.toLowerCase() === 'use' ? node : node.querySelector('use');
        var href = use && (use.getAttribute('href') || '');
        if (href && href.indexOf('#icon-') === 0) return { text: href.slice(6), check: false };
        if (node.tagName === 'IMG' && node.alt) return { text: node.alt.slice(0, 40), check: false };
      }
    }
    if (text.length > 40) text = text.slice(0, 40).replace(/\s+\S*$/, '') + '…';
    return { text: text.replace(/"/g, "'").replace(/\[/g, '(').replace(/\]/g, ')'), check: true };
  }
  function authored(node) {
    // skip anything added at runtime, and the parts of an element that are
    // not things a person would point at (an icon's <use>, an SVG <title>)
    while (node && node !== deckEl && (!node._deckPath || /^(use|title|defs|marker)$/i.test(node.tagName))) node = node.parentNode;
    return node && node._deckPath ? node : null;
  }
  function refFor(node) {
    node = authored(node);
    if (!node) return '';
    var slide = node.closest('.slide'), parts = ['slide ' + slide.dataset.slideNumber];
    if (node !== slide) {
      var chain = [];
      for (var a = node.parentNode; a && a !== slide; a = a.parentNode) {
        if (a._deckPath && !QUIET[baseLabel(a)[1]]) chain.unshift(labelOf(a));
      }
      parts = parts.concat(chain.slice(-2), [labelOf(node)]);
    }
    var snip = snippetOf(node);
    return '[' + parts.join(' › ') + (snip.text ? ' "' + snip.text + '"' : '') + ' @' + node._deckPath + (snip.check ? '' : '~') + ']';
  }

  var pick = null, pickTrail = [], lastRef = '';
  var editBar, editBox, editTag, editField, editMsg;
  function placePick() {
    if (!editBox) return;
    if (!pick || !editOn) { editBox.style.display = 'none'; return; }
    var r = pick.getBoundingClientRect();
    editBox.style.display = 'block';
    editBox.style.left = r.left + 'px';
    editBox.style.top = r.top + 'px';
    editBox.style.width = Math.max(2, r.width) + 'px';
    editBox.style.height = Math.max(2, r.height) + 'px';
    editTag.textContent = refFor(pick).replace(/^\[|\s@[\d.~]+\]$/g, '');
    editTag.classList.toggle('is-below', r.top < 34);
  }
  function setPick(node, keepTrail) {
    pick = node;
    if (!keepTrail) pickTrail = [];
    placePick();
  }
  function clearPick() { setPick(null); }
  function widenPick() {
    if (!pick || pick.classList.contains('slide')) return;
    var up = authored(pick.parentNode);
    if (!up) return;
    pickTrail.push(pick);
    setPick(up, true);
  }
  function narrowPick() {
    if (pickTrail.length) setPick(pickTrail.pop(), true);
  }
  function copyText(text, done) {
    function fallback() {
      var ta = el('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      done(ok);
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
        return;
      }
    } catch (e) {}
    fallback();
  }
  function copyPick() {
    if (!pick) return;
    lastRef = refFor(pick);
    editField.value = lastRef;
    editBar.classList.add('has-ref');
    editBox.classList.remove('is-copied');
    void editBox.offsetWidth;
    editBox.classList.add('is-copied');
    copyText(lastRef, function (ok) {
      editMsg.textContent = ok ? 'Copied. Paste it into your message to your agent.' :
        'Copying was blocked. Select the text and copy it by hand.';
      editBar.classList.toggle('is-blocked', !ok);
      if (!ok) { editField.focus(); editField.select(); }
    });
  }
  function setEdit(on) {
    if (!isMain || on === editOn) return;
    if (on) {
      if (root.classList.contains('deck-overview')) toggleOverview();
      toggleHelp(false);
      root.classList.remove('deck-show-notes');
    }
    editOn = on;
    root.classList.toggle('deck-edit', on);
    clearPick();
    if (on) {
      // show the finished slide, every step revealed, so anything can be picked
      var slide = slides[cur];
      cleanup(slide);
      slide.classList.add('is-rest');
      step = slide._deckSteps;
      applySteps(slide, step, 0, true);
      fire(slide, 'deck:rest', { step: step, total: step });
      fire(slide, 'deck:step', { step: step, total: step, direction: 0 });
      sendState();
      editMsg.textContent = 'Click an element to copy a reference to it.';
      editBar.classList.remove('is-blocked');
    }
  }
  if (isMain) {
    editBox = el('div', 'deck-edit-box');
    editTag = el('span', 'deck-edit-tag');
    editBox.appendChild(editTag);
    ui.appendChild(editBox);

    editBar = el('div', 'deck-edit-bar');
    editBar.setAttribute('role', 'region');
    editBar.setAttribute('aria-label', 'Edit mode');
    editMsg = el('span', 'deck-edit-msg');
    editMsg.setAttribute('role', 'status');
    editField = el('input', 'deck-edit-field');
    editField.type = 'text';
    editField.readOnly = true;
    editField.setAttribute('aria-label', 'Last copied reference');
    editField.addEventListener('focus', function () { editField.select(); });
    editField.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { editField.blur(); setEdit(false); e.preventDefault(); }
    });
    var again = el('button', 'deck-edit-again', 'Copy again');
    again.type = 'button';
    again.addEventListener('click', function () {
      if (!lastRef) return;
      copyText(lastRef, function (ok) {
        editMsg.textContent = ok ? 'Copied again.' : 'Copying was blocked. Select the text and copy it by hand.';
        if (!ok) { editField.focus(); editField.select(); }
      });
    });
    var doneBtn = el('button', '', 'Done');
    doneBtn.type = 'button';
    doneBtn.addEventListener('click', function () { setEdit(false); });
    editBar.appendChild(el('strong', '', 'Edit mode'));
    editBar.appendChild(editMsg);
    editBar.appendChild(editField);
    editBar.appendChild(again);
    editBar.appendChild(doneBtn);
    ui.appendChild(editBar);

    document.addEventListener('mousemove', function (e) {
      if (!editOn) return;
      var hit = document.elementFromPoint(e.clientX, e.clientY);
      if (!hit || ui.contains(hit)) return;
      // the bar steps out of the way when the pointer works near the bottom
      editBar.classList.toggle('is-top', e.clientY > window.innerHeight * 0.7);
      var node = authored(hit);
      if (node && !slides[cur].contains(node)) node = null;
      if (node !== pick && pickTrail.indexOf(node) < 0) setPick(node);
    }, true);
    document.addEventListener('click', function (e) {
      if (!editOn || ui.contains(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
      if (!pick) {
        var node = authored(e.target);
        if (node && slides[cur].contains(node)) setPick(node);
      }
      copyPick();
    }, true);
    window.addEventListener('resize', placePick);
  }

  /* ---- Public API (the `deck` object handed to slide scripts) ----------- */
  var api = {
    get index() { return cur; },
    get step() { return step; },
    get total() { return slides.length; },
    get slides() { return slides.slice(); },
    go: function (i, s) { go(i, s || 0, { direction: 1 }); },
    next: next,
    prev: prev,
    token: token,
    ms: toMs,
    isRest: isRest,
    // Web Animations wrapper: resolves token names, is skipped in resting
    // state, and is cancelled when the slide is left. Animate FROM a start
    // state; the element's own styles are the final frame.
    animate: function (node, keyframes, opts) {
      var slide = node.closest('.slide');
      if (isRest(slide) || typeof node.animate !== 'function') return null;
      opts = opts || {};
      var o = {};
      for (var key in opts) o[key] = opts[key];
      o.duration = toMs(opts.duration == null ? '--dur-base' : opts.duration, node);
      o.delay = toMs(opts.delay || 0, node);
      var ease = opts.easing == null ? '--ease-out' : opts.easing;
      o.easing = String(ease).indexOf('--') === 0 ? token(ease, node) || 'ease-out' : ease;
      if (!o.fill) o.fill = 'backwards';
      var a;
      try { a = node.animate(keyframes, o); }
      catch (err) { o.easing = 'ease-out'; a = node.animate(keyframes, o); }
      track(slide, function () { a.cancel(); });
      return a;
    },
    // Frame loop that stops by itself when the slide is left or put at rest.
    loop: function (slide, fn) {
      if (isRest(slide)) return function () {};
      var id = 0, start = null, last = null, stopped = false;
      function frame(t) {
        if (stopped) return;
        if (start === null) { start = t; last = t; }
        var keep = fn(t - start, t - last);
        last = t;
        if (keep === false) { stopped = true; return; }
        id = requestAnimationFrame(frame);
      }
      id = requestAnimationFrame(frame);
      function stop() { stopped = true; cancelAnimationFrame(id); }
      track(slide, stop);
      return stop;
    },
    // Timer that is cleared when the slide is left or put at rest.
    after: function (slide, delay, fn) {
      if (isRest(slide)) return function () {};
      var id = setTimeout(fn, toMs(delay, slide));
      function stop() { clearTimeout(id); }
      track(slide, stop);
      return stop;
    },
    rest: setRest,
    edit: function (on) { setEdit(on !== false); },
    ref: refFor,
    get lastRef() { return lastRef; },
    printNotes: printNotes,
    endPrintNotes: endPrintNotes,
    toggleOverview: toggleOverview,
    openPresenter: openPresenter,
    setVariant: function (v) { setVariant(v); },
    mode: isEmbed ? 'embed' : isPresenter ? 'presenter' : 'main'
  };
  window.Deck = api;

  /* ---- Slide and deck scripts ------------------------------------------- */
  function runScript(node, slide) {
    try {
      // eslint-disable-next-line no-new-func
      new Function('slide', 'deck', '"use strict";\n' + node.textContent).call(slide || deckEl, slide, api);
    } catch (err) {
      if (slide) slide.setAttribute('data-script-error', String(err && err.message || err));
      console.error('[deck] script failed' + (slide ? ' on slide ' + slide.dataset.slideNumber : ''), err);
    }
  }
  Array.prototype.forEach.call(document.querySelectorAll('script[data-deck][type="text/x-deck"]'), function (node) {
    runScript(node, null);
  });
  slides.forEach(function (slide) {
    Array.prototype.forEach.call(slide.querySelectorAll('script[data-slide-scope][type="text/x-deck"]'), function (node) {
      runScript(node, slide);
    });
  });

  /* ---- Start ------------------------------------------------------------ */
  var chrome = el('div', 'deck-progress');
  chrome.appendChild(el('div', 'deck-progress-bar'));
  chrome.setAttribute('aria-hidden', 'true');
  deckEl.appendChild(chrome);
  deckEl.classList.toggle('is-progress-on', progressOn);

  fit();
  if (isPresenter) {
    buildPresenter();
    go(0, 0, { force: true, remote: true, direction: 0 });
  } else if (isEmbed) {
    go(0, 0, { force: true, remote: true, rest: true, direction: 0 });
    post(window.parent, { t: 'ready', kind: embedKind });
  } else {
    go(readHash(), 0, { force: true, direction: 1 });
  }
  root.classList.add('deck-ready');
})();
