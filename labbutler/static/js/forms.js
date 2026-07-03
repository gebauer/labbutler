/* Progressive enhancement for the procurement request and inventory item forms
   (CSP: no inline scripts).

   - select[data-combobox]            type-and-search dropdown over the native select;
                                      with data-combobox-create="<hidden input name>" an
                                      unknown name can be created on save (e.g. vendor)
   - select[multiple][data-tags]      pill-style tag picker; existing tags are suggested
                                      while typing, new ones need an explicit "+ add"
                                      click and are submitted as hidden new_tags inputs
   - select[multiple][data-hazards]   pill-style GHS statement picker over the fixed
                                      catalog (no on-the-fly creation); pills show the
                                      code, tooltips show the full statement
   - button[data-ghs-lookup]          fetches GHS suggestions for the form's CAS number
                                      from data-ghs-url and merges them into the pickers
   - form[data-request-form]          live total/VAT preview from the price fields, with
                                      the chosen currency echoed into [data-currency-echo]
   - button[data-delivery-days]       sets the expected-delivery date to today + N days

   Without JS the native selects stay usable; only the typeahead pickers, live preview
   and CAS lookup are missing. */

(function () {
  'use strict';

  var PANEL_CLASS =
    'absolute z-30 mt-1 max-h-56 w-full overflow-auto rounded border border-gray-300 bg-white py-1 text-sm shadow-lg';
  var OPTION_CLASS = 'cursor-pointer px-3 py-1.5';
  var ACTIVE_CLASS = 'bg-teal-50 text-teal-800';

  function textInput(placeholder) {
    var input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.placeholder = placeholder || '';
    input.className =
      'w-full rounded border border-gray-300 px-3 py-2 text-sm ' +
      'focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500';
    return input;
  }

  /* Shared dropdown panel: rows are {label, hint, onPick}; keyboard moves the active row. */
  function makePanel(wrapper) {
    var panel = document.createElement('div');
    panel.className = PANEL_CLASS + ' hidden';
    wrapper.appendChild(panel);
    var state = { rows: [], active: -1 };

    function render(rows) {
      state.rows = rows;
      state.active = rows.length ? 0 : -1;
      panel.textContent = '';
      rows.forEach(function (row, index) {
        var el = document.createElement('div');
        el.className = OPTION_CLASS + (index === state.active ? ' ' + ACTIVE_CLASS : '');
        el.textContent = row.label;
        if (row.hint) {
          var hint = document.createElement('span');
          hint.className = 'ml-1 text-xs text-gray-400';
          hint.textContent = row.hint;
          el.appendChild(hint);
        }
        el.addEventListener('mousedown', function (event) {
          event.preventDefault(); // keep focus in the input
          row.onPick();
        });
        panel.appendChild(el);
      });
      panel.classList.toggle('hidden', rows.length === 0);
    }

    function move(delta) {
      if (!state.rows.length) return;
      state.active = (state.active + delta + state.rows.length) % state.rows.length;
      Array.prototype.forEach.call(panel.children, function (el, index) {
        el.className = OPTION_CLASS + (index === state.active ? ' ' + ACTIVE_CLASS : '');
      });
      panel.children[state.active].scrollIntoView({ block: 'nearest' });
    }

    return {
      render: render,
      move: move,
      pickActive: function () {
        if (state.active >= 0) state.rows[state.active].onPick();
        return state.active >= 0;
      },
      close: function () { render([]); },
      isOpen: function () { return !panel.classList.contains('hidden'); },
    };
  }

  function bindPanelKeys(input, panel, openPanel) {
    input.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!panel.isOpen()) openPanel(); else panel.move(event.key === 'ArrowDown' ? 1 : -1);
      } else if (event.key === 'Enter') {
        if (panel.isOpen()) {
          event.preventDefault(); // don't submit the form while picking
          panel.pickActive();
        } else if (input.value.trim()) {
          event.preventDefault();
          openPanel();
        }
      } else if (event.key === 'Escape' && panel.isOpen()) {
        event.stopPropagation();
        panel.close();
      }
    });
    input.addEventListener('blur', function () {
      setTimeout(panel.close, 150);
    });
  }

  /* ——— Type-and-search single select, optionally with on-the-fly create ——— */

  function enhanceCombobox(select) {
    var createFieldName = select.getAttribute('data-combobox-create');
    var createInput = createFieldName
      ? select.form.querySelector('input[name="' + createFieldName + '"]')
      : null;

    var wrapper = document.createElement('div');
    wrapper.className = 'relative';
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add('hidden');
    select.setAttribute('tabindex', '-1');

    var input = textInput('Type to search…');
    wrapper.insertBefore(input, select);
    var panel = makePanel(wrapper);

    var options = Array.prototype.filter.call(select.options, function (opt) {
      return opt.value !== '';
    });

    function currentLabel() {
      if (createInput && createInput.value) return createInput.value;
      var selected = select.options[select.selectedIndex];
      return selected && selected.value ? selected.text : '';
    }

    function choose(value, label) {
      select.value = value;
      if (createInput) createInput.value = '';
      input.value = label;
      panel.close();
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function chooseNew(name) {
      select.value = '';
      createInput.value = name;
      input.value = name;
      panel.close();
    }

    function openPanel() {
      var query = input.value.trim().toLowerCase();
      var rows = options
        .filter(function (opt) { return !query || opt.text.toLowerCase().indexOf(query) !== -1; })
        .slice(0, 50)
        .map(function (opt) {
          return { label: opt.text, onPick: function () { choose(opt.value, opt.text); } };
        });
      var typed = input.value.trim();
      var exact = options.some(function (opt) { return opt.text.toLowerCase() === typed.toLowerCase(); });
      if (createInput && typed && !exact) {
        rows.push({ label: '+ Create “' + typed + '”', hint: 'new', onPick: function () { chooseNew(typed); } });
      }
      panel.render(rows);
    }

    input.addEventListener('input', function () {
      // Typing invalidates the previous pick until something is chosen again.
      select.value = '';
      if (createInput) createInput.value = '';
      openPanel();
    });
    input.addEventListener('focus', function () { input.select(); openPanel(); });
    input.addEventListener('blur', function () {
      setTimeout(function () { input.value = currentLabel(); }, 150);
    });
    bindPanelKeys(input, panel, openPanel);

    input.value = currentLabel();
  }

  /* ——— Pill multi-selects with type-ahead (tags, GHS statements) ———

     config: placeholder    input placeholder text
             createName     hidden-input name for on-the-fly creation, or null
             createLabel    row label for the create action (given the typed text)
             pillLabel      pill text for a selected option (default: option text)
             pillTitle      pill tooltip (default: none)
             rowBreak       (prevOpt, opt) -> true starts a new pill line here
             afterRender    called after every pill re-render                       */

  function enhancePillSelect(select, config) {
    var wrapper = document.createElement('div');
    wrapper.className = 'relative';
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add('hidden');
    select.setAttribute('tabindex', '-1');

    var box = document.createElement('div');
    box.className =
      'flex flex-wrap items-center gap-1.5 rounded border border-gray-300 bg-white px-2 py-1.5 ' +
      'focus-within:border-gray-500 focus-within:ring-1 focus-within:ring-gray-500';
    var input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.placeholder = config.placeholder;
    input.className = 'min-w-32 flex-1 border-0 p-1 text-sm focus:outline-none focus:ring-0';
    box.appendChild(input);
    wrapper.insertBefore(box, select);
    var panel = makePanel(wrapper);
    var pillLabel = config.pillLabel || function (opt) { return opt.text; };
    var pillTitle = config.pillTitle || function () { return ''; };

    function pill(label, title, isNew, onRemove) {
      var el = document.createElement('span');
      el.className =
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ' +
        (isNew ? 'bg-amber-100 text-amber-800' : 'bg-teal-100 text-teal-800');
      el.textContent = label + (isNew ? ' (new)' : '');
      if (title) el.title = title;
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'ml-0.5 font-bold hover:opacity-60';
      remove.setAttribute('aria-label', 'Remove ' + label);
      remove.textContent = '×';
      remove.addEventListener('click', onRemove);
      el.appendChild(remove);
      return el;
    }

    function newEntryInputs() {
      if (!config.createName) return [];
      return Array.prototype.slice.call(
        select.form.querySelectorAll('input[name="' + config.createName + '"]')
      );
    }

    function renderPills() {
      Array.prototype.slice.call(box.querySelectorAll('span')).forEach(function (el) { el.remove(); });
      var previous = null;
      Array.prototype.forEach.call(select.options, function (opt) {
        if (!opt.selected) return;
        if (previous && config.rowBreak && config.rowBreak(previous, opt)) {
          var lineBreak = document.createElement('span');
          lineBreak.className = 'basis-full';
          box.insertBefore(lineBreak, input);
        }
        previous = opt;
        box.insertBefore(pill(pillLabel(opt), pillTitle(opt), false, function () {
          opt.selected = false;
          renderPills();
        }), input);
      });
      newEntryInputs().forEach(function (hidden) {
        box.insertBefore(pill(hidden.value, '', true, function () {
          hidden.remove();
          renderPills();
        }), input);
      });
      if (config.afterRender) config.afterRender();
    }

    function addExisting(opt) {
      opt.selected = true;
      input.value = '';
      panel.close();
      renderPills();
      input.focus();
    }

    function addNew(name) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = config.createName;
      hidden.value = name;
      select.form.appendChild(hidden);
      input.value = '';
      panel.close();
      renderPills();
      input.focus();
    }

    function openPanel() {
      var typed = input.value.trim();
      var query = typed.toLowerCase();
      var taken = newEntryInputs().map(function (hidden) { return hidden.value.toLowerCase(); });
      var rows = Array.prototype.filter.call(select.options, function (opt) {
        return !opt.selected && (!query || opt.text.toLowerCase().indexOf(query) !== -1);
      }).slice(0, 20).map(function (opt) {
        return { label: opt.text, onPick: function () { addExisting(opt); } };
      });
      var known = Array.prototype.some.call(select.options, function (opt) {
        return opt.text.toLowerCase() === query;
      });
      if (config.createName && typed && !known && taken.indexOf(query) === -1) {
        rows.push({ label: config.createLabel(typed), hint: 'new', onPick: function () { addNew(typed); } });
      }
      panel.render(rows);
    }

    input.addEventListener('input', openPanel);
    input.addEventListener('focus', openPanel);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Backspace' && !input.value) {
        var last = input.previousElementSibling;
        if (last) last.querySelector('button').click();
      }
    });
    bindPanelKeys(input, panel, openPanel);
    box.addEventListener('click', function () { input.focus(); });
    // Fired after programmatic selection changes (e.g. the CAS lookup applying codes).
    select.addEventListener('lb:sync', renderPills);

    renderPills();
  }

  function enhanceTags(select) {
    enhancePillSelect(select, {
      placeholder: 'Type to add tags…',
      createName: 'new_tags',
      createLabel: function (typed) { return '+ Add tag “' + typed + '”'; },
    });
  }

  var PICTOGRAM_NAMES = {
    GHS01: 'Explosive', GHS02: 'Flammable', GHS03: 'Oxidizing',
    GHS04: 'Gas under pressure', GHS05: 'Corrosive', GHS06: 'Acute toxicity',
    GHS07: 'Harmful / irritant', GHS08: 'Serious health hazard',
    GHS09: 'Environmental hazard',
  };

  function enhanceHazards(select) {
    // Option text is "H225 — Highly flammable…"; pills show only the code. H/EUH
    // statements and P statements render on separate lines for easy checking.
    var strip = null;

    // Pictograms are derived from the selected H-codes (each option carries its
    // data-pictograms), so removing a wrong statement removes its symbol too.
    function renderPictograms() {
      if (!strip) {
        strip = document.createElement('div');
        strip.className = 'mt-1.5 flex flex-wrap items-center gap-1.5';
        var wrapper = select.parentNode;
        wrapper.parentNode.insertBefore(strip, wrapper.nextSibling);
      }
      strip.textContent = '';
      var base = select.getAttribute('data-icon-base') || '';
      var codes = [];
      Array.prototype.forEach.call(select.options, function (opt) {
        if (!opt.selected) return;
        (opt.getAttribute('data-pictograms') || '').split(' ').forEach(function (code) {
          if (code && codes.indexOf(code) === -1) codes.push(code);
        });
      });
      codes.sort();
      codes.forEach(function (code) {
        var icon = document.createElement('img');
        icon.src = base + code + '.svg';
        icon.alt = code;
        icon.title = (PICTOGRAM_NAMES[code] || code) + ' (' + code + ')';
        icon.className = 'h-10 w-10';
        strip.appendChild(icon);
      });
    }

    enhancePillSelect(select, {
      placeholder: 'Type a code or keyword (H225, flammable…)',
      createName: null,
      pillLabel: function (opt) { return opt.value; },
      pillTitle: function (opt) { return opt.text; },
      rowBreak: function (previous, opt) {
        return previous.value.charAt(0) !== 'P' && opt.value.charAt(0) === 'P';
      },
      afterRender: renderPictograms,
    });
  }

  /* ——— CAS number → GHS suggestions (server proxies PubChem) ——— */

  function bindGhsLookup(button) {
    var form = button.form;
    var status = form.querySelector('[data-ghs-status]');
    var say = function (text) { if (status) status.textContent = text; };
    var addLine = function (className) {
      var line = document.createElement('div');
      line.className = className;
      status.appendChild(line);
      return line;
    };

    button.addEventListener('click', function () {
      var casInput = form.querySelector('[name="cas_number"]');
      var cas = casInput ? casInput.value.trim() : '';
      if (!/^\d{2,7}-\d{2}-\d$/.test(cas)) {
        say('Enter a CAS number (e.g. 64-17-5) first.');
        return;
      }
      button.disabled = true;
      say('Looking up ' + cas + ' …');
      fetch(button.getAttribute('data-ghs-url') + '?cas=' + encodeURIComponent(cas), {
        headers: { Accept: 'application/json' },
      })
        .then(function (response) {
          if (!response.ok) throw new Error('HTTP ' + response.status);
          return response.json();
        })
        .then(function (data) { apply(data, cas); })
        .catch(function () {
          say('Lookup failed — you can still pick statements manually.');
        })
        .then(function () { button.disabled = false; });
    });

    function percentLabel(percent) {
      return percent === null ? '' : ' (' + (Math.round(percent * 10) / 10) + '%)';
    }

    function selectCode(hazardSelect, code) {
      var opt = hazardSelect.querySelector('option[value="' + code + '"]');
      if (!opt || opt.selected) return false;
      opt.selected = true;
      return true;
    }

    function apply(data, cas) {
      if (!data.found) {
        say('No GHS data found for ' + cas + '.');
        return;
      }
      status.textContent = '';
      var notes = [];

      // Merge, never overwrite: majority-reported codes are added to the current
      // selection (each a removable pill), an existing signal word is left alone.
      var hazardSelect = form.querySelector('select[data-hazards]');
      var added = 0;
      var rare = [];
      if (hazardSelect) {
        data.hazards.forEach(function (hazard) {
          if (!hazard.suggested) {
            rare.push(hazard);
          } else if (selectCode(hazardSelect, hazard.code)) {
            added += 1;
          }
        });
        hazardSelect.dispatchEvent(new Event('lb:sync'));
      }
      notes.push(added ? 'Added ' + added + ' statement' + (added === 1 ? '' : 's') + '.'
                       : 'No new statements to add.');

      var signalSelect = form.querySelector('[name="signal_word"]');
      if (signalSelect && data.signal_word) {
        if (!signalSelect.value) {
          signalSelect.value = data.signal_word;
          notes.push('Signal word: ' + data.signal_word + '.');
        } else if (signalSelect.value !== data.signal_word) {
          notes.push('PubChem suggests signal word “' + data.signal_word + '” (kept yours).');
        }
      }
      // Pictograms are not rendered here: the strip under the statement picker
      // derives them live from the selected codes instead.
      var summary = addLine('flex flex-wrap items-center gap-2 text-xs text-gray-600');
      summary.textContent = notes.join(' ');

      var caveat = document.createElement('span');
      caveat.className = 'text-amber-700';
      caveat.textContent =
        'Best-effort guess — verify against the vendor’s SDS / product page.';
      summary.appendChild(caveat);

      // Codes only a minority of ECHA notifiers report: offered, not auto-selected.
      if (rare.length) {
        var row = addLine('mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-gray-500');
        var intro = document.createElement('span');
        intro.textContent = 'Rarely reported — click to add:';
        row.appendChild(intro);
        rare.forEach(function (hazard) {
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className =
            'rounded-full border border-dashed border-gray-400 px-2 py-0.5 text-xs ' +
            'text-gray-600 hover:bg-gray-100';
          chip.textContent = '+ ' + hazard.code + percentLabel(hazard.percent);
          chip.title = hazard.text;
          chip.addEventListener('click', function () {
            selectCode(hazardSelect, hazard.code);
            hazardSelect.dispatchEvent(new Event('lb:sync'));
            chip.remove();
          });
          row.appendChild(chip);
        });
      }
    }
  }

  /* ——— Live total & VAT preview ——— */

  function bindTotals(form) {
    var rate = parseFloat(form.getAttribute('data-vat-rate')) || 0;
    var totalEl = form.querySelector('[data-total-display]');
    var vatEl = form.querySelector('[data-vat-display]');
    if (!totalEl || !vatEl) return;

    function field(name) { return form.querySelector('[name="' + name + '"]'); }
    function num(name) { return parseFloat(field(name).value) || 0; }

    function recalculate() {
      var currency = field('currency').value || 'EUR';
      var subtotal = num('unit_price') * (parseInt(field('pack_count').value, 10) || 0)
        + num('shipping_cost');
      var included = field('includes_taxes').checked;
      // Round the VAT to cents first and derive the total from it, so the two lines
      // shown agree with each other and with the DB's numeric(…,2) rounding.
      var cents = function (value) { return Math.round(value * 100) / 100; };
      var vat, total;
      if (included) {
        total = cents(subtotal);
        vat = cents(subtotal - subtotal / (1 + rate));
      } else {
        vat = cents(subtotal * rate);
        total = cents(subtotal) + vat;
      }
      var pct = (rate * 100).toFixed(rate * 100 % 1 ? 1 : 0);
      totalEl.textContent = total.toFixed(2) + ' ' + currency;
      vatEl.textContent = included
        ? 'includes ' + vat.toFixed(2) + ' ' + currency + ' VAT (' + pct + '%)'
        : '+ ' + vat.toFixed(2) + ' ' + currency + ' VAT (' + pct + '%) added';
      Array.prototype.forEach.call(
        form.querySelectorAll('[data-currency-echo]'),
        function (el) { el.textContent = currency; }
      );
    }

    form.addEventListener('input', recalculate);
    form.addEventListener('change', recalculate);
    recalculate();
  }

  function bindDeliveryShortcuts(form) {
    var input = form.querySelector('input[name="expected_delivery"]');
    if (!input) return;
    form.querySelectorAll('button[data-delivery-days]').forEach(function (button) {
      button.addEventListener('click', function () {
        var target = new Date();
        target.setDate(target.getDate() + parseInt(button.getAttribute('data-delivery-days'), 10));
        var pad = function (n) { return String(n).padStart(2, '0'); };
        // Local date, not toISOString(): UTC would shift the day near midnight.
        input.value = target.getFullYear() + '-' + pad(target.getMonth() + 1) + '-' + pad(target.getDate());
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('select[data-combobox]').forEach(enhanceCombobox);
    document.querySelectorAll('select[data-tags]').forEach(enhanceTags);
    document.querySelectorAll('select[data-hazards]').forEach(enhanceHazards);
    document.querySelectorAll('button[data-ghs-lookup]').forEach(bindGhsLookup);
    var form = document.querySelector('form[data-request-form]');
    if (form) {
      bindTotals(form);
      bindDeliveryShortcuts(form);
    }
  });
})();
