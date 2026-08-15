/* Gallery: per-collection pagination + lazy <model-viewer> for GLB/GLTF.
 *
 * Mesh cards only mount WebGL while they are on the current page and in the
 * viewport. Browsers cap WebGL contexts (~8–16); leaving every GLB live would
 * blank out the first viewers. Images already use loading="lazy".
 */
(() => {
  const MODEL_VIEWER_SRC =
    "https://ajax.googleapis.com/ajax/libs/model-viewer/4.3.1/model-viewer.min.js";
  const FALLBACK_PAGE_SIZE = { image: 12, video: 6, mesh3d: 4 };
  const DEHYDRATE_MS = 400;

  let modelViewerPromise = null;
  let observer = null;
  const dehydrateTimers = new WeakMap();

  function pageSize(grid) {
    const n = Number(grid.dataset.pageSize);
    if (Number.isFinite(n) && n > 0) return Math.floor(n);
    return FALLBACK_PAGE_SIZE[grid.dataset.bucket] || FALLBACK_PAGE_SIZE.image;
  }

  function cards(grid) {
    return [...grid.querySelectorAll(":scope > .gallery-card")];
  }

  function ensureModelViewer() {
    if (window.customElements && customElements.get("model-viewer")) {
      return Promise.resolve();
    }
    if (!modelViewerPromise) {
      modelViewerPromise = import(MODEL_VIEWER_SRC).catch((error) => {
        modelViewerPromise = null;
        throw error;
      });
    }
    return modelViewerPromise;
  }

  function hydrateModel(card) {
    const host = card.querySelector(".gallery-model[data-src]");
    if (!host || host.querySelector("model-viewer")) return;
    const src = host.dataset.src;
    if (!src) return;
    ensureModelViewer()
      .then(() => {
        if (card.hasAttribute("hidden") || host.querySelector("model-viewer")) return;
        const viewer = document.createElement("model-viewer");
        viewer.setAttribute("src", src);
        viewer.setAttribute("alt", host.dataset.alt || "3D model");
        viewer.setAttribute("camera-controls", "");
        viewer.setAttribute("touch-action", "pan-y");
        viewer.setAttribute("shadow-intensity", "1");
        viewer.setAttribute("environment-image", "neutral");
        viewer.setAttribute("loading", "eager");
        viewer.setAttribute("reveal", "auto");
        viewer.setAttribute("interaction-prompt", "none");
        const placeholder = host.querySelector(".gallery-model-placeholder");
        if (placeholder) placeholder.remove();
        host.prepend(viewer);
      })
      .catch(() => {
        const placeholder = host.querySelector(".gallery-model-placeholder");
        if (placeholder) placeholder.textContent = "3D 预览加载失败，请下载";
      });
  }

  function dehydrateModel(card) {
    const host = card.querySelector(".gallery-model");
    if (!host) return;
    const viewer = host.querySelector("model-viewer");
    if (viewer) viewer.remove();
    if (!host.querySelector(".gallery-model-placeholder")) {
      const span = document.createElement("span");
      span.className = "gallery-model-placeholder";
      span.textContent = "3D 预览";
      host.appendChild(span);
    }
  }

  function observeCard(card) {
    if (!observer || !card.querySelector(".gallery-model[data-src]")) return;
    observer.observe(card);
  }

  function showPage(grid, page) {
    const items = cards(grid);
    const size = pageSize(grid);
    const pages = Math.max(1, Math.ceil(items.length / size));
    const current = Math.min(Math.max(1, page), pages);
    grid.dataset.page = String(current);
    items.forEach((card, index) => {
      const onPage = Math.floor(index / size) + 1 === current;
      card.toggleAttribute("hidden", !onPage);
      const pending = dehydrateTimers.get(card);
      if (pending) {
        clearTimeout(pending);
        dehydrateTimers.delete(card);
      }
      if (onPage) observeCard(card);
      else {
        if (observer) observer.unobserve(card);
        dehydrateModel(card);
      }
    });
    const pager = grid.nextElementSibling;
    if (pager && pager.classList.contains("gallery-pager")) {
      renderPager(grid, pager, current, pages);
    }
  }

  function renderPager(grid, nav, current, pages) {
    nav.hidden = pages <= 1;
    if (pages <= 1) {
      nav.innerHTML = "";
      return;
    }
    const id = grid.dataset.galleryId || "gallery";
    const buttons = [];
    buttons.push(
      `<button type="button" data-page="${current - 1}" ${current <= 1 ? "disabled" : ""} aria-label="上一页">上一页</button>`
    );
    for (let i = 1; i <= pages; i += 1) {
      const currentAttr = i === current ? ' aria-current="page"' : "";
      buttons.push(
        `<button type="button" data-page="${i}"${currentAttr} aria-label="第 ${i} 页">${i}</button>`
      );
    }
    buttons.push(
      `<button type="button" data-page="${current + 1}" ${current >= pages ? "disabled" : ""} aria-label="下一页">下一页</button>`
    );
    nav.innerHTML = buttons.join("");
    nav.setAttribute("aria-label", `图库分页 ${id}`);
  }

  function ensurePager(grid) {
    let nav = grid.nextElementSibling;
    if (!nav || !nav.classList.contains("gallery-pager")) {
      nav = document.createElement("nav");
      nav.className = "gallery-pager";
      nav.dataset.galleryPager = grid.dataset.galleryId || "";
      grid.insertAdjacentElement("afterend", nav);
      nav.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-page]");
        if (!button || button.disabled) return;
        const next = Number(button.dataset.page);
        showPage(grid, next);
        const hash = `${grid.dataset.galleryId || "gallery"}-p${next}`;
        if (history.replaceState) {
          history.replaceState(null, "", `#${hash}`);
        } else {
          location.hash = hash;
        }
        grid.scrollIntoView({ block: "start", behavior: "smooth" });
      });
    }
    return nav;
  }

  function pageFromHash(grid) {
    const id = grid.dataset.galleryId;
    if (!id || !location.hash) return 1;
    const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = location.hash.slice(1).match(new RegExp(`^${escaped}-p(\\d+)$`));
    return match ? Number(match[1]) : 1;
  }

  function initObserver() {
    if (observer || !("IntersectionObserver" in window)) {
      return observer;
    }
    observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const card = entry.target;
          const pending = dehydrateTimers.get(card);
          if (entry.isIntersecting) {
            if (pending) {
              clearTimeout(pending);
              dehydrateTimers.delete(card);
            }
            hydrateModel(card);
            return;
          }
          if (pending) return;
          const timer = setTimeout(() => {
            dehydrateTimers.delete(card);
            dehydrateModel(card);
          }, DEHYDRATE_MS);
          dehydrateTimers.set(card, timer);
        });
      },
      { rootMargin: "120px 0px", threshold: 0.05 }
    );
    return observer;
  }

  function initGallery() {
    initObserver();
    document.querySelectorAll(".gallery-grid").forEach((grid) => {
      if (grid.dataset.galleryReady === "1") return;
      grid.dataset.galleryReady = "1";
      ensurePager(grid);
      const items = cards(grid);
      if (!observer) {
        items.forEach((card) => {
          if (!card.hasAttribute("hidden")) hydrateModel(card);
        });
      }
      showPage(grid, pageFromHash(grid));
    });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(initGallery);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initGallery);
  } else {
    initGallery();
  }
})();
