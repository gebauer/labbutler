/* Dashboard widget ordering: drag to rearrange (SortableJS), persisted per browser in
   localStorage. External file (not inline) so the CSP can stay `script-src 'self'`. */
document.addEventListener('DOMContentLoaded', function () {
  var grid = document.getElementById('dashboard-grid');
  if (!grid || !window.Sortable) return;
  var STORE = 'labbutler-dashboard-order';
  try {
    JSON.parse(localStorage.getItem(STORE) || '[]').reverse().forEach(function (key) {
      var el = grid.querySelector('[data-key="' + key + '"]');
      if (el) grid.insertBefore(el, grid.firstChild);
    });
  } catch (e) { /* ignore a corrupt saved order */ }
  Sortable.create(grid, {
    handle: '[data-drag]', animation: 150,
    onEnd: function () {
      var keys = Array.prototype.map.call(grid.children, function (c) { return c.dataset.key; });
      localStorage.setItem(STORE, JSON.stringify(keys));
    }
  });
});
