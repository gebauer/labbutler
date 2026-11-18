/* Site-wide behaviours kept out of templates so the CSP can stay `script-src 'self'`
   (no inline event handlers). Hooks are data attributes:

   - [data-autosubmit]        submit the surrounding form when the value changes
   - [data-action-template]   like autosubmit, but first set the form's action from the
                              template URL, replacing "__value__" with the chosen value
   - [data-print]             open the browser print dialog on click
   - [data-stop-propagation]  keep clicks from bubbling (e.g. actions inside a <summary>)
   - form[data-confirm]       ask for confirmation before submitting (destructive actions)
   - [data-copy]              copy the attribute's text to the clipboard, with ✓ feedback
   - every POST form          ignores repeat submits while the first is in flight
*/

/* Double-submit guard. A double click on "Approve" or "Check in" used to send two POSTs.
   Capture phase, so a repeat is swallowed before any other handler sees it. The form is
   marked at once and released on the next tick if a later handler cancelled the submit
   (a declined confirm, a modal that re-submits later), so only a submit that really
   proceeds keeps the lock. The mark expires
   after a few seconds, for POSTs that answer with a download and never navigate away,
   and is cleared when the page is restored from the back/forward cache. */
var SUBMIT_LOCK_MS = 8000;
document.addEventListener('submit', function (event) {
  var form = event.target;
  if ((form.method || '').toLowerCase() !== 'post' || form.target === '_blank') return;
  if (form.hasAttribute('hx-post') || form.hasAttribute('data-hx-post')) return;
  if (form.dataset.submitting) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  form.dataset.submitting = '1';
  form.setAttribute('aria-busy', 'true');
  setTimeout(function () {
    if (event.defaultPrevented) {
      releaseForm(form);
      return;
    }
    setTimeout(function () { releaseForm(form); }, SUBMIT_LOCK_MS);
  }, 0);
}, true);

function releaseForm(form) {
  delete form.dataset.submitting;
  form.removeAttribute('aria-busy');
}

window.addEventListener('pageshow', function (event) {
  if (!event.persisted) return; // only a back/forward-cache restore keeps stale marks
  document.querySelectorAll('form[data-submitting]').forEach(releaseForm);
});

document.addEventListener('submit', function (event) {
  var form = event.target.closest('form[data-confirm]');
  if (form && !window.confirm(form.getAttribute('data-confirm'))) event.preventDefault();
});

document.addEventListener('change', function (event) {
  var el = event.target.closest('[data-autosubmit], [data-action-template]');
  if (!el || !el.form) return;
  var template = el.getAttribute('data-action-template');
  if (template) el.form.action = template.replace('__value__', encodeURIComponent(el.value));
  el.form.submit();
});

document.addEventListener('click', function (event) {
  if (event.target.closest('[data-print]')) window.print();
});

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-stop-propagation]').forEach(function (el) {
    el.addEventListener('click', function (event) { event.stopPropagation(); });
  });
});

document.addEventListener('click', function (event) {
  var button = event.target.closest('[data-copy]');
  if (!button) return;
  navigator.clipboard.writeText(button.getAttribute('data-copy')).then(function () {
    var original = button.textContent;
    button.textContent = '✓ copied';
    setTimeout(function () { button.textContent = original; }, 1200);
  });
});
