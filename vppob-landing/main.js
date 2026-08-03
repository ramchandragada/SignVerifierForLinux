/* VPPOB landing – lightweight interactions */
(function () {
  'use strict';

  // Current year in footer
  var yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  /*
   * Lead form handling.
   *
   * By default the form opens a pre-filled email to sales@thegstco.com so it
   * works with zero backend setup. To collect leads automatically instead,
   * create a free form endpoint (e.g. Formspree) and paste it below — the form
   * will POST to it and show an inline success message.
   */
  var FORM_ENDPOINT = ''; // e.g. 'https://formspree.io/f/xxxxxxx'
  var CONTACT_EMAIL = 'sales@thegstco.com';

  var form = document.getElementById('lead-form');
  var status = document.getElementById('form-status');
  if (!form) return;

  function setStatus(msg, type) {
    if (!status) return;
    status.textContent = msg;
    status.className = 'form-note' + (type ? ' ' + type : '');
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();

    var name = form.name.value.trim();
    var phone = form.phone.value.trim();
    var email = form.email.value.trim();
    var state = form.state.value.trim();
    var consent = form.consent.checked;

    if (!name || !phone || !email) {
      setStatus('Please fill in your name, phone and email.', 'error');
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setStatus('Please enter a valid email address.', 'error');
      return;
    }
    if (!consent) {
      setStatus('Please accept the Privacy Policy to continue.', 'error');
      return;
    }

    // Backend submission if configured
    if (FORM_ENDPOINT) {
      setStatus('Sending…', '');
      fetch(FORM_ENDPOINT, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: new FormData(form)
      })
        .then(function (r) {
          if (r.ok) {
            form.reset();
            setStatus('Thanks! We’ve received your request and will call you back shortly.', 'success');
          } else {
            setStatus('Something went wrong. Please call or WhatsApp us instead.', 'error');
          }
        })
        .catch(function () {
          setStatus('Network error. Please call or WhatsApp us instead.', 'error');
        });
      return;
    }

    // Fallback: open a pre-filled email
    var subject = encodeURIComponent('VPPOB enquiry from ' + name);
    var body = encodeURIComponent(
      'Name: ' + name + '\n' +
      'Phone: ' + phone + '\n' +
      'Email: ' + email + '\n' +
      'State to register in: ' + (state || 'Not specified') + '\n'
    );
    window.location.href = 'mailto:' + CONTACT_EMAIL + '?subject=' + subject + '&body=' + body;
    setStatus('Opening your email app… If nothing happens, email us at ' + CONTACT_EMAIL + '.', 'success');
  });
})();
