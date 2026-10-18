const BACKEND = "https://goldchat-frankfurt.onrender.com";

export default {
  async fetch(request, env) {
    const incoming = new URL(request.url);
    const path = incoming.pathname;

    if (path.startsWith("/api/") || path === "/ws" || path === "/healthz") {
      const target = new URL(path + incoming.search, BACKEND);
      const headers = new Headers(request.headers);
      headers.delete("host");
      const upstream = new Request(target, { method: request.method, headers, body: request.body, redirect: "manual" });
      return fetch(upstream);
    }

    // The original HTML uses /static/* while the Pages upload stores assets at /.
    if (path.startsWith("/static/")) {
      const assetUrl = new URL(request.url);
      assetUrl.pathname = path.slice("/static".length);
      return env.ASSETS.fetch(new Request(assetUrl, request));
    }

    return env.ASSETS.fetch(request);
  },
};
