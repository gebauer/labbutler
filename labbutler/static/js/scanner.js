/* Data Matrix label scanner (inventory/scan.html). Decodes with the vendored
   @zxing/library UMD build (global `ZXing`) and submits the decoded code through
   the page's regular POST form, so CSRF and the redirect are handled by the
   browser. Hooks are data attributes, keeping the CSP at `script-src 'self'`:

   - [data-scanner]         page root; script is a no-op without it
   - [data-scanner-video]   <video> viewfinder
   - [data-scanner-status]  status/error line
   - [data-scanner-code]    the form's code input (shared with manual entry)
*/
document.addEventListener('DOMContentLoaded', function () {
  var root = document.querySelector('[data-scanner]');
  if (!root) return;

  var video = root.querySelector('[data-scanner-video]');
  var status = root.querySelector('[data-scanner-status]');
  var codeInput = root.querySelector('[data-scanner-code]');

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    video.hidden = true;
    status.textContent = 'Camera not available (needs HTTPS) — type the ID below instead.';
    return;
  }

  var reader = new ZXing.BrowserDatamatrixCodeReader();
  var submitted = false;

  reader
    .decodeFromConstraints({ video: { facingMode: 'environment' } }, video, function (result) {
      if (!result || submitted) return;
      submitted = true; // the callback keeps firing between decode and navigation
      reader.reset();
      codeInput.value = result.getText();
      codeInput.form.requestSubmit();
    })
    .then(function () {
      status.textContent = 'Point the camera at the Data Matrix label.';
    })
    .catch(function () {
      video.hidden = true;
      status.textContent = 'Could not start the camera — type the ID below instead.';
    });

  // Release the camera on navigation away (incl. BFCache) — not just on success.
  window.addEventListener('pagehide', function () { reader.reset(); });
});
