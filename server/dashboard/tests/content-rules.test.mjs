import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

// Minimal DOM for exercising the actual policy editor's load/edit/save flow.
class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {};
    this.value = ""; this.checked = false; this.className = "";
  }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute() {}
  add(option) { this.append(option); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() { this.listeners.click?.(); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  descendants() { return this.children.flatMap(child => [child, ...(child.descendants?.() || [])]); }
  querySelector(selector) {
    const field = selector.match(/data-field="([^"]+)"/)?.[1];
    return this.descendants().find(child => child.dataset?.field === field);
  }
}

function setup() {
  const ids = Object.fromEntries(["app-rules", "domain-allow", "domain-block", "safe-search",
    "domain-categories", "add-app-rule", "save-content-policy", "save-policy-button"].map(id => [id, new Element()]));
  globalThis.document = {
    createElement: tag => new Element(tag), createTextNode: text => ({textContent: text}),
    getElementById: id => ids[id],
    querySelectorAll: selector => selector === ".app-rule" ? ids["app-rules"].children :
      ids["domain-categories"].descendants().filter(child => child.tag === "input" && child.checked),
  };
  globalThis.Option = class extends Element {
    constructor(text, value) { super("option"); this.textContent = text; this.value = value; }
  };
  return ids;
}

const source = fs.readFileSync(new URL("../static/js/content-rules.js", import.meta.url), "utf8");
const {fillContentRules, readContentRules, initContentRules} = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

test("content policy round trip preserves hashes, empty blocked categories and disabled SafeSearch", () => {
  setup();
  const payload = {apps: [{name: "game.exe", sha256: "a".repeat(64), action: "block"}],
    domains: {allow: ["school.edu.vn"], block: ["example.com"], blocked_categories: [], safe_search: false}};
  fillContentRules(payload);
  assert.deepEqual(readContentRules(), payload);
});

test("default and delete remove app rules while other edits survive save", () => {
  const ids = setup();
  fillContentRules({apps: [{name: "one.exe", action: "allow"}, {name: "two.exe", action: "block"}], domains: []});
  initContentRules();
  ids["app-rules"].children[0].querySelector('[data-field="action"]').value = "default";
  const second = ids["app-rules"].children[1];
  second.descendants().find(child => child.tag === "button").click();
  ids["add-app-rule"].click();
  const row = ids["app-rules"].children.at(-1);
  row.querySelector('[data-field="name"]').value = "new.exe";
  ids["domain-block"].value = " example.com \n\n second.example.com ";
  const saved = readContentRules();
  assert.deepEqual(saved.apps, [{name: "new.exe", sha256: null, action: "block"}]);
  assert.deepEqual(saved.domains.block, ["example.com", "second.example.com"]);
  let saves = 0;
  ids["save-policy-button"].addEventListener("click", () => saves++);
  ids["save-content-policy"].click();
  assert.equal(saves, 1);
});
