// Trap 9: the page asks for a city list with GET; this worker answers it and also POSTs.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname === "/api/cities") {
    e.waitUntil(fetch("/api/apply?trap=9", { method: "POST", body: url.searchParams.get("q") || "" }));
  }
});
