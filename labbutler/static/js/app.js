/* Site-wide behaviours kept out of templates so the CSP can stay `script-src 'self'`
   (no inline event handlers). Hooks are data attributes:

   - [data-autosubmit]        submit the surrounding form when the value changes
   - [data-action-template]   like autosubmit, but first set the form's action from the
                              template URL, replacing "__value__" with the chosen value
   - [data-print]             open the browser print dialog on click
   - [data-stop-propagation]  keep clicks from bubbling (e.g. actions inside a <summary>)
*/
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
