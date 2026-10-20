const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../web_ui/static/js/comparisons.js"),
  "utf8",
);

class Element {
  constructor() {
    this.children = [];
    this.value = "";
    this.disabled = false;
    this.textContent = "";
    this.onclick = null;
    this.onchange = null;
  }
  append(...nodes) {
    this.children.push(...nodes);
  }
  replaceChildren(...nodes) {
    this.children = nodes;
  }
}

class Headers {
  constructor(initial = {}) {
    this.values = new Map(Object.entries(initial));
  }
  has(name) {
    return [...this.values.keys()].some(
      (key) => key.toLowerCase() === name.toLowerCase(),
    );
  }
  set(name, value) {
    this.values.set(name, value);
  }
  get(name) {
    return [...this.values.entries()].find(
      ([key]) => key.toLowerCase() === name.toLowerCase(),
    )?.[1];
  }
}

test("comparisons page sends CSRF on browse and completes the UI workflow", async () => {
  const ids = [
    "roots",
    "up",
    "home",
    "location",
    "files",
    "sources",
    "render",
    "count",
    "frames",
    "message",
    "results",
  ];
  const elements = new Map(ids.map((id) => [id, new Element()]));
  elements.get("count").value = "4";
  elements.get("frames").value = "";
  const requests = [];
  let statusPolls = 0;
  const context = vm.createContext({
    window: { UA_COMPARISON_CSRF: "synthetic-csrf" },
    document: {
      getElementById: (id) => elements.get(id),
      createElement: () => new Element(),
    },
    Headers,
    setTimeout,
    clearTimeout,
    Promise,
    Number,
    JSON,
    encodeURIComponent,
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      let payload;
      if (url === "/api/browse_roots") {
        payload = {
          success: true,
          items: [{ name: "media", path: "/media", type: "folder" }],
        };
      } else if (url.includes("/api/browse?")) {
        payload = {
          success: true,
          items: [
            { name: "one.mkv", path: "/media/one.mkv", type: "file" },
            { name: "two.mkv", path: "/media/two.mkv", type: "file" },
          ],
        };
      } else if (url === "/api/comparisons" && options.method === "POST") {
        payload = { success: true, id: "job-1" };
      } else if (url === "/api/comparisons/job-1") {
        statusPolls += 1;
        payload = { success: true, status: "completed", files: ["001-01-One.png"] };
      } else {
        throw new Error(`Unexpected request: ${url}`);
      }
      return { ok: true, json: async () => payload };
    },
  });

  vm.runInContext(source, context);
  await new Promise((resolve) => setImmediate(resolve));

  elements.get("roots").value = "/media";
  elements.get("roots").onchange();
  await new Promise((resolve) => setImmediate(resolve));
  const browseRequest = requests.find((request) =>
    request.url.includes("/api/browse?"),
  );
  assert.ok(browseRequest, "selecting a browse root should load its files");
  assert.equal(
    browseRequest.options.headers.get("X-CSRF-Token"),
    "synthetic-csrf",
  );

  elements.get("files").children[0].onclick();
  elements.get("files").children[1].onclick();
  elements.get("render").onclick();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  const post = requests.find(
    (request) => request.url === "/api/comparisons" && request.options.method === "POST",
  );
  assert.ok(post);
  assert.equal(post.options.headers.get("X-CSRF-Token"), "synthetic-csrf");
  assert.equal(JSON.parse(post.options.body).sources.length, 2);
  assert.equal(statusPolls, 1);
  assert.match(elements.get("results").children[0].textContent, /Download/);
});
