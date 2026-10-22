"use strict";
(async () => {
  const byId = (id) => document.getElementById(id);
  const message = (text) => { byId("message").textContent = text; };
  async function api(data) {
    const response = await fetch("/api/remote-upload", data ? {
      method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content}, body: JSON.stringify(data)
    } : {});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Request failed");
    return body;
  }
  async function refresh() {
    try {
      const body = await api();
      const selected = byId("backend").value;
      byId("backend").replaceChildren(...Object.keys(body.backends).map((name) => {
        const option = document.createElement("option"); option.value = name; option.textContent = name; return option;
      }));
      if (body.backends[selected]) byId("backend").value = selected;
      byId("status").textContent = JSON.stringify(body.backends, null, 2);
      byId("transfers").replaceChildren(...Object.entries(body.backends).flatMap(([backend, info]) => (info.transfers || []).map((transfer) => {
        const line = document.createElement("p");
        const mib = (bytes) => (bytes / 1048576).toFixed(1);
        const percent = transfer.bytes_total ? Math.min(100, transfer.bytes_sent / transfer.bytes_total * 100).toFixed(1) : "0";
        line.textContent = `${backend}: ${transfer.name} — ${transfer.state} — ${percent}% (${mib(transfer.bytes_sent)} / ${mib(transfer.bytes_total)} MiB), ${mib(transfer.bytes_per_second)} MiB/s`;
        return line;
      })));
      if (!Object.keys(body.backends).length) message("No backend configured. Set UA_REMOTE_UPLOAD_BACKENDS on the UA host.");
    } catch (error) { message(error.message); }
  }
  async function submit(data) {
    try { message(JSON.stringify(await api(data))); await refresh(); } catch (error) { message(error.message); }
  }
  byId("remote-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submit({backend: byId("backend").value, action: "execute", source: byId("source").value, trackers: byId("trackers").value.split(",").map((s) => s.trim()).filter(Boolean), return_after: Number(byId("hours").value) * 3600});
  });
  byId("refresh").addEventListener("click", refresh);
  byId("tick").addEventListener("click", () => submit({backend: byId("backend").value, action: "tick"}));
  await refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 3000);
})();
