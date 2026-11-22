const feed = document.querySelector("[data-view-token]");

if (feed && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting || entry.intersectionRatio < 0.5) continue;

      const body = new URLSearchParams({ csrf: feed.dataset.viewToken });
      if (!navigator.sendBeacon?.(entry.target.dataset.viewUrl, body)) {
        fetch(entry.target.dataset.viewUrl, { method: "POST", body, keepalive: true })
          .catch(() => {});
      }
      observer.unobserve(entry.target);
    }
  }, { threshold: 0.5 });

  feed.querySelectorAll("[data-view-url]").forEach((item) => observer.observe(item));
}
