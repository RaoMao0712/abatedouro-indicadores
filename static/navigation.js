(() => {
    const body = document.body;
    const drawer = document.querySelector("[data-nav-drawer]");
    const openButton = document.querySelector("[data-nav-open]");
    const closeButton = document.querySelector("[data-nav-close]");
    const overlay = document.querySelector("[data-nav-overlay]");

    if (!drawer || !openButton || !closeButton || !overlay) {
        return;
    }

    let focusBeforeOpen = null;

    const focusableElements = () => Array.from(drawer.querySelectorAll(
        'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
    ));

    const closeDrawer = ({ restoreFocus = true } = {}) => {
        body.classList.remove("fd-nav-open");
        openButton.setAttribute("aria-expanded", "false");
        openButton.setAttribute("aria-label", "Abrir menu de navegação");
        overlay.hidden = true;
        if (restoreFocus && focusBeforeOpen) {
            focusBeforeOpen.focus();
        }
    };

    const openDrawer = () => {
        focusBeforeOpen = document.activeElement;
        body.classList.add("fd-nav-open");
        openButton.setAttribute("aria-expanded", "true");
        openButton.setAttribute("aria-label", "Fechar menu de navegação");
        overlay.hidden = false;
        closeButton.focus();
    };

    openButton.addEventListener("click", () => {
        if (body.classList.contains("fd-nav-open")) {
            closeDrawer();
        } else {
            openDrawer();
        }
    });

    closeButton.addEventListener("click", () => closeDrawer());
    overlay.addEventListener("click", () => closeDrawer());

    drawer.addEventListener("click", (event) => {
        if (event.target.closest("a") && window.matchMedia("(max-width: 900px)").matches) {
            closeDrawer({ restoreFocus: false });
        }
    });

    document.addEventListener("keydown", (event) => {
        if (!body.classList.contains("fd-nav-open")) {
            return;
        }

        if (event.key === "Escape") {
            event.preventDefault();
            closeDrawer();
            return;
        }

        if (event.key !== "Tab") {
            return;
        }

        const focusable = focusableElements();
        if (!focusable.length) {
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    window.addEventListener("resize", () => {
        if (!window.matchMedia("(max-width: 900px)").matches) {
            closeDrawer({ restoreFocus: false });
        }
    });
})();
