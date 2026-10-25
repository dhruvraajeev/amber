// Sets the saved light/dark theme before first paint. A file, not an inline script, so the CSP can keep
// script-src 'self'. Classic (not a module) so it runs before the page renders.
try { if (JSON.parse(localStorage.getItem('amber.theme')) === 'light') document.documentElement.dataset.theme = 'light' } catch {}
