document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.querySelector(".fd-password-toggle");
    const password = document.querySelector("#login-senha");

    if (!toggle || !password) return;

    toggle.addEventListener("click", () => {
        const reveal = password.type === "password";
        password.type = reveal ? "text" : "password";
        toggle.setAttribute("aria-pressed", String(reveal));
        toggle.setAttribute("aria-label", reveal ? "Ocultar senha" : "Mostrar senha");
        password.focus();
    });
});
