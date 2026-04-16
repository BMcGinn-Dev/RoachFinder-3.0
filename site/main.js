/**
 * RoachFinder 3.0 — Shared JS Utilities
 */

// ── Mobile nav toggle ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
    const hamburger = document.querySelector(".hamburger");
    const mobileNav = document.querySelector(".mobile-nav");
    const overlay = document.querySelector(".mobile-overlay");

    if (hamburger) {
        hamburger.addEventListener("click", function () {
            mobileNav.classList.toggle("open");
            overlay.classList.toggle("open");
        });
    }

    if (overlay) {
        overlay.addEventListener("click", function () {
            mobileNav.classList.remove("open");
            overlay.classList.remove("open");
        });
    }

    // Close mobile nav when a link is tapped
    document.querySelectorAll(".mobile-nav a").forEach(a => {
        a.addEventListener("click", () => {
            mobileNav?.classList.remove("open");
            overlay?.classList.remove("open");
        });
    });
});

// ── Fetch JSON helper ──────────────────────────────────────────
async function fetchJSON(path) {
    try {
        const resp = await fetch(path);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.error(`Failed to load ${path}:`, err);
        return null;
    }
}

// ── Format win percentage ──────────────────────────────────────
function winPct(wins, losses) {
    const total = wins + losses;
    if (total === 0) return "0.000";
    return ((wins / total) * 100).toFixed(3);
}

// ── Animated counter ───────────────────────────────────────────
/**
 * Animate a number count-up inside an element.
 * @param {HTMLElement} el     Target element (textContent is replaced).
 * @param {number} target      Final value.
 * @param {Object} opts        { decimals, suffix, duration (ms) }
 */
function animateCount(el, target, opts = {}) {
    if (!el) return;
    const decimals = opts.decimals ?? 0;
    const suffix   = opts.suffix   ?? "";
    const duration = opts.duration ?? 900;

    // Respect reduced-motion preference
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        el.textContent = target.toFixed(decimals) + suffix;
        el.setAttribute("data-animated", "true");
        return;
    }

    const start = 0;
    const startTime = performance.now();

    function tick(now) {
        const elapsed = now - startTime;
        const p = Math.min(elapsed / duration, 1);
        // ease-out cubic
        const eased = 1 - Math.pow(1 - p, 3);
        const current = start + (target - start) * eased;
        el.textContent = current.toFixed(decimals) + suffix;
        if (p < 1) {
            requestAnimationFrame(tick);
        } else {
            el.textContent = target.toFixed(decimals) + suffix;
        }
    }

    el.setAttribute("data-animated", "true");
    requestAnimationFrame(tick);
}

/**
 * Fire the count-up animation once the element scrolls into view.
 */
function countUpWhenVisible(el, target, opts = {}) {
    if (!el) return;
    if (!("IntersectionObserver" in window)) {
        animateCount(el, target, opts);
        return;
    }
    const io = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                animateCount(el, target, opts);
                io.disconnect();
            }
        });
    }, { threshold: 0.2 });
    io.observe(el);
}
