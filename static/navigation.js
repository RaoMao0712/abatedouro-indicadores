(() => {
    const backLink = document.querySelector("[data-safe-back]");
    if (!backLink || backLink.getAttribute("aria-disabled") === "true") return;

    try {
        const previous = document.referrer ? new URL(document.referrer) : null;
        const sameOrigin = previous && previous.origin === window.location.origin;
        const validPath = sameOrigin && previous.pathname !== "/" && previous.pathname !== window.location.pathname;
        if (validPath) backLink.href = previous.href;
    } catch (_) {
        // O href para Início permanece como fallback seguro.
    }
})();
