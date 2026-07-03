/* Progressive enhancement for the procurement request form (CSP: no inline scripts).

   - select[data-combobox]            type-and-search dropdown over the native select;
                                      with data-combobox-create="<hidden input name>" an
                                      unknown name can be created on save (e.g. vendor)
   - select[multiple][data-tags]      pill-style tag picker; existing tags are suggested
                                      while typing, new ones need an explicit "+ add"
                                      click and are submitted as hidden new_tags inputs
   - form[data-request-form]          live total/VAT preview from the price fields, with
                                      the chosen currency echoed into [data-currency-echo]
   - button[data-delivery-days]       sets the expected-delivery date to today + N days

   Without JS the native selects stay usable; only the live preview is missing. */

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

  /* ——— Tag pills with type-ahead and explicit "+ add" for new tags ——— */

  function enhanceTags(select) {
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
    input.placeholder = 'Type to add tags…';
    input.className = 'min-w-32 flex-1 border-0 p-1 text-sm focus:outline-none focus:ring-0';
    box.appendChild(input);
    wrapper.insertBefore(box, select);
    var panel = makePanel(wrapper);

    function pill(label, isNew, onRemove) {
      var el = document.createElement('span');
      el.className =
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ' +
        (isNew ? 'bg-amber-100 text-amber-800' : 'bg-teal-100 text-teal-800');
      el.textContent = label + (isNew ? ' (new)' : '');
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'ml-0.5 font-bold hover:opacity-60';
      remove.setAttribute('aria-label', 'Remove tag ' + label);
      remove.textContent = '×';
      remove.addEventListener('click', onRemove);
      el.appendChild(remove);
      return el;
    }

    function renderPills() {
      Array.prototype.slice.call(box.querySelectorAll('span')).forEach(function (el) { el.remove(); });
      Array.prototype.forEach.call(select.options, function (opt) {
        if (!opt.selected) return;
        box.insertBefore(pill(opt.text, false, function () {
          opt.selected = false;
          renderPills();
        }), input);
      });
      Array.prototype.forEach.call(
        select.form.querySelectorAll('input[name="new_tags"]'),
        function (hidden) {
          box.insertBefore(pill(hidden.value, true, function () {
            hidden.remove();
            renderPills();
          }), input);
        }
      );
    }

    function newTagNames() {
      return Array.prototype.map.call(
        select.form.querySelectorAll('input[name="new_tags"]'),
        function (hidden) { return hidden.value.toLowerCase(); }
      );
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
      hidden.name = 'new_tags';
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
      var taken = newTagNames();
      var rows = Array.prototype.filter.call(select.options, function (opt) {
        return !opt.selected && (!query || opt.text.toLowerCase().indexOf(query) !== -1);
      }).slice(0, 20).map(function (opt) {
        return { label: opt.text, onPick: function () { addExisting(opt); } };
      });
      var known = Array.prototype.some.call(select.options, function (opt) {
        return opt.text.toLowerCase() === query;
      });
      if (typed && !known && taken.indexOf(query) === -1) {
        rows.push({ label: '+ Add tag “' + typed + '”', hint: 'new', onPick: function () { addNew(typed); } });
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

    renderPills();
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
    var form = document.querySelector('form[data-request-form]');
    if (!form) return;
    form.querySelectorAll('select[data-combobox]').forEach(enhanceCombobox);
    form.querySelectorAll('select[data-tags]').forEach(enhanceTags);
    bindTotals(form);
    bindDeliveryShortcuts(form);
  });
})();
