async function api(path, options = {}) {
  const hasBody = options.body !== undefined;
  const init = {
    headers: hasBody ? { "Content-Type": "application/json" } : {},
    ...options,
  };
  if (hasBody && !init.headers["Content-Type"]) {
    init.headers["Content-Type"] = "application/json";
  }
  const token = localStorage.getItem("token");
  if (token) {
    init.headers = { ...init.headers, "X-Token": token };
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}
