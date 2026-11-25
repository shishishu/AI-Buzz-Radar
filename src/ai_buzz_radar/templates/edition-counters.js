(() => {
  const buttons = [...document.querySelectorAll("button[data-counter]")];
  const live = location.origin === "https://shishishu.github.io" && location.pathname.startsWith("/radar/");
  const prefix = "ai-buzz-radar:";
  const status = document.querySelector("#counter-status");

  function stored(key) {
    try { return localStorage.getItem(prefix + key); } catch { return null; }
  }
  function save(key, value) {
    try { localStorage.setItem(prefix + key, String(value)); } catch { /* Private browsing. */ }
  }
  async function counter(action, key) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const url = new URL("https://abacus.jasoncameron.dev/" + action + "/shishishu.github.io/radar-" + key);
      url.searchParams.set("t", Date.now());
      const response = await fetch(url, {
        cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal
      });
      const data = await response.json();
      if (action === "get" && response.status === 404 && data.error === "Key not found") return 0;
      if (!response.ok || !Number.isSafeInteger(data.value) || data.value < 0) throw Error("counter unavailable");
      return data.value;
    } finally { clearTimeout(timeout); }
  }
  function show(element, key, value) {
    const last = stored("total:" + key);
    const values = [element.dataset.value, last, value]
      .filter(n => n != null && /^\d+$/.test(n)).map(Number).filter(Number.isSafeInteger);
    if (!values.length) return;
    const total = Math.max(...values);
    element.dataset.value = total;
    element.textContent = total.toLocaleString();
    if (value != null && (last === null || total !== Number(last))) save("total:" + key, total);
  }
  async function refresh(element, key) {
    try { show(element, key, await counter("get", key)); }
    catch {
      show(element, key);
      // A read is safe to retry even when the previous request reached the server.
      setTimeout(async () => {
        try { show(element, key, await counter("get", key)); }
        catch { show(element, key); }
      }, 3000);
    }
  }
  function liked(button) {
    return button.getAttribute("aria-pressed") === "true" || stored("liked:" + button.dataset.counter) === "1";
  }
  function renderButton(button) {
    button.setAttribute("aria-pressed", String(liked(button)));
    button.disabled = !live || liked(button) || button.hasAttribute("aria-busy");
  }
  for (const button of buttons) {
    const key = button.dataset.counter;
    const element = button.querySelector(".total");
    show(element, key);
    renderButton(button);
    if (!live) continue;
    refresh(element, key);
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.setAttribute("aria-busy", "true");
      renderButton(button);
      status.textContent = "";
      async function vote() {
        if (liked(button)) return;
        const total = await counter("hit", key);
        save("liked:" + key, "1");
        button.setAttribute("aria-pressed", "true");
        show(element, key, total);
      }
      try {
        if (navigator.locks) await navigator.locks.request(prefix + key, vote);
        else await vote();
      } catch {
        status.textContent = document.documentElement.lang === "en"
          ? "Could not confirm your like." : "暂时无法确认点赞。";
        refresh(element, key);
      } finally {
        button.removeAttribute("aria-busy");
        renderButton(button);
      }
    });
  }
  const views = document.getElementById("views");
  show(views, "views");
  if (!live) return;
  window.addEventListener("storage", () => {
    show(views, "views");
    for (const button of buttons) {
      show(button.querySelector(".total"), button.dataset.counter);
      renderButton(button);
    }
  });
  // Count each document load once. Switching language or opening a card stays in this document.
  counter("hit", "views").then(value => show(views, "views", value))
    .catch(() => refresh(views, "views"));
})();
