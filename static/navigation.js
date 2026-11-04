(() => {
    const backLink = document.querySelector("[data-safe-back]");
    if (!backLink || backLink.getAttribute("aria-disabled") === "true") return;

    try {
        const target = new URL(backLink.href, window.location.origin);
        const validPath = target.origin === window.location.origin
            && target.pathname !== "/"
            && target.pathname !== window.location.pathname;
        if (!validPath) backLink.href = "/inicio";
    } catch (_) {
        backLink.href = "/inicio";
    }
})();
